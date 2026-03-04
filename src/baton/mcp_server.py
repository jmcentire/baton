"""MCP server for Baton circuit orchestration.

Exposes circuit topology, state, routing, metrics, and signals
as MCP resources and tools for Claude integration.

Run via: baton-mcp (stdio transport)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from baton.config import CONFIG_FILENAME, load_circuit, load_circuit_config
from baton.schemas import CircuitConfig, CircuitSpec, CircuitState
from baton.state import (
    BATON_DIR,
    CIRCUIT_FILE,
    STATE_FILE,
    load_circuit_spec,
    load_state,
    read_jsonl,
)
from baton.telemetry import METRICS_FILE
from baton.signals import SIGNALS_FILE

mcp = FastMCP(
    "baton",
    instructions=(
        "Baton is a circuit orchestration tool. Use these resources and tools "
        "to inspect circuit topology, node status, routing configuration, "
        "metrics, and request signals. The project directory defaults to the "
        "current working directory but can be overridden with BATON_PROJECT_DIR."
    ),
)


def _project_dir() -> Path:
    """Resolve the Baton project directory."""
    return Path(os.environ.get("BATON_PROJECT_DIR", ".")).resolve()


def _load_config() -> CircuitConfig | None:
    """Load CircuitConfig from baton.yaml, or None if missing."""
    try:
        return load_circuit_config(_project_dir())
    except FileNotFoundError:
        return None


def _load_spec() -> CircuitSpec | None:
    """Load CircuitSpec from .baton/circuit.json or baton.yaml."""
    d = _project_dir()
    spec = load_circuit_spec(d)
    if spec:
        return spec
    try:
        return load_circuit(d)
    except FileNotFoundError:
        return None


def _load_state() -> CircuitState | None:
    """Load CircuitState from .baton/state.json."""
    return load_state(_project_dir())


def _json_pretty(obj: dict | list) -> str:
    return json.dumps(obj, indent=2, default=str)


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mcp.resource("baton://status")
def resource_status() -> str:
    """Circuit status summary: name, collapse level, live nodes, adapter states."""
    state = _load_state()
    if not state:
        return "No running circuit. Run 'baton up' or 'baton apply' first."

    adapters = {}
    for name, a in state.adapters.items():
        adapters[name] = {
            "status": str(a.status),
            "health": str(a.last_health_verdict),
            "service_command": a.service.command or "(none)",
            "is_mock": a.service.is_mock,
        }

    return _json_pretty({
        "circuit_name": state.circuit_name,
        "collapse_level": str(state.collapse_level),
        "live_nodes": state.live_nodes,
        "started_at": state.started_at,
        "updated_at": state.updated_at,
        "adapters": adapters,
    })


@mcp.resource("baton://topology")
def resource_topology() -> str:
    """Circuit topology: nodes (name, port, role, mode) and edges (source -> target)."""
    spec = _load_spec()
    if not spec:
        return "No circuit topology found. Create baton.yaml first."

    nodes = []
    for n in spec.nodes:
        nodes.append({
            "name": n.name,
            "host": n.host,
            "port": n.port,
            "role": str(n.role),
            "proxy_mode": str(n.proxy_mode),
            "contract": n.contract or None,
            "metadata": dict(n.metadata) if n.metadata else None,
        })

    edges = []
    for e in spec.edges:
        edge = {"source": e.source, "target": e.target}
        if e.label:
            edge["label"] = e.label
        edges.append(edge)

    return _json_pretty({
        "name": spec.name,
        "version": spec.version,
        "nodes": nodes,
        "edges": edges,
    })


@mcp.resource("baton://node/{name}")
def resource_node(name: str) -> str:
    """Full details for a specific node: spec, state, and routing."""
    spec = _load_spec()
    if not spec:
        return "No circuit topology found."

    node = spec.node_by_name(name)
    if not node:
        return f"Node '{name}' not found in circuit."

    result: dict = {
        "name": node.name,
        "host": node.host,
        "port": node.port,
        "role": str(node.role),
        "proxy_mode": str(node.proxy_mode),
        "management_port": node.management_port,
        "contract": node.contract or None,
        "metadata": dict(node.metadata) if node.metadata else None,
        "neighbors": spec.neighbors(name),
        "dependents": spec.dependents(name),
    }

    state = _load_state()
    if state and name in state.adapters:
        a = state.adapters[name]
        result["state"] = {
            "status": str(a.status),
            "health": str(a.last_health_verdict),
            "consecutive_failures": a.consecutive_failures,
            "service": {
                "command": a.service.command or "(none)",
                "is_mock": a.service.is_mock,
                "pid": a.service.pid,
            },
            "routing_config": a.routing_config,
        }

    return _json_pretty(result)


@mcp.resource("baton://routes")
def resource_routes() -> str:
    """Routing configuration for all nodes."""
    config = _load_config()
    state = _load_state()

    routes: dict = {}

    # From baton.yaml config
    if config and config.routing:
        for name, rc in config.routing.items():
            routes[name] = rc.model_dump()

    # Overlay with live state routing
    if state:
        for name, a in state.adapters.items():
            if a.routing_config:
                routes[name] = a.routing_config

    if not routes:
        return "No routing configurations found."

    return _json_pretty(routes)


@mcp.resource("baton://config")
def resource_config() -> str:
    """Full baton.yaml configuration (topology + routing + deploy + security)."""
    config = _load_config()
    if not config:
        return "No baton.yaml found."
    return _json_pretty(config.model_dump())


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def circuit_status(project_dir: str = "") -> str:
    """Get the current circuit status including all adapter states.

    Args:
        project_dir: Project directory (defaults to BATON_PROJECT_DIR or cwd).
    """
    if project_dir:
        os.environ["BATON_PROJECT_DIR"] = project_dir
    return resource_status()


@mcp.tool()
def list_nodes(project_dir: str = "") -> str:
    """List all nodes in the circuit with their role, port, and status.

    Args:
        project_dir: Project directory (defaults to BATON_PROJECT_DIR or cwd).
    """
    if project_dir:
        os.environ["BATON_PROJECT_DIR"] = project_dir

    spec = _load_spec()
    if not spec:
        return "No circuit topology found."

    state = _load_state()
    nodes = []
    for n in spec.nodes:
        entry = {
            "name": n.name,
            "port": n.port,
            "role": str(n.role),
            "mode": str(n.proxy_mode),
        }
        if state and n.name in state.adapters:
            a = state.adapters[n.name]
            entry["status"] = str(a.status)
            entry["health"] = str(a.last_health_verdict)
            entry["is_mock"] = a.service.is_mock
        nodes.append(entry)

    return _json_pretty(nodes)


@mcp.tool()
def node_detail(name: str, project_dir: str = "") -> str:
    """Get full details for a specific node including state and routing.

    Args:
        name: The node name.
        project_dir: Project directory (defaults to BATON_PROJECT_DIR or cwd).
    """
    if project_dir:
        os.environ["BATON_PROJECT_DIR"] = project_dir
    return resource_node(name)


@mcp.tool()
def show_routes(node: str = "", project_dir: str = "") -> str:
    """Show routing configuration. Optionally filter by node name.

    Args:
        node: Filter to a specific node's routing config.
        project_dir: Project directory (defaults to BATON_PROJECT_DIR or cwd).
    """
    if project_dir:
        os.environ["BATON_PROJECT_DIR"] = project_dir

    if not node:
        return resource_routes()

    state = _load_state()
    if state and node in state.adapters:
        rc = state.adapters[node].routing_config
        if rc:
            return _json_pretty(rc)

    config = _load_config()
    if config and node in config.routing:
        return _json_pretty(config.routing[node].model_dump())

    return f"No routing configuration for node '{node}'."


@mcp.tool()
def show_metrics(node: str = "", last_n: int = 10, project_dir: str = "") -> str:
    """Load recent metrics snapshots from .baton/metrics.jsonl.

    Args:
        node: Filter to a specific node's metrics.
        last_n: Number of recent snapshots to return (default 10).
        project_dir: Project directory (defaults to BATON_PROJECT_DIR or cwd).
    """
    if project_dir:
        os.environ["BATON_PROJECT_DIR"] = project_dir

    d = _project_dir()
    records = read_jsonl(d, METRICS_FILE, last_n=last_n)
    if not records:
        return "No metrics data found. Run 'baton up' and generate traffic first."

    if node:
        filtered = []
        for r in records:
            nodes = r.get("nodes", {})
            if node in nodes:
                filtered.append({
                    "timestamp": r.get("timestamp"),
                    "node": nodes[node],
                })
        if not filtered:
            return f"No metrics found for node '{node}'."
        return _json_pretty(filtered)

    return _json_pretty(records)


@mcp.tool()
def show_signals(
    node: str = "",
    path: str = "",
    last_n: int = 50,
    project_dir: str = "",
) -> str:
    """Load recent request signals from .baton/signals.jsonl.

    Args:
        node: Filter to a specific node.
        path: Filter to signals matching this path substring.
        last_n: Number of recent signals to return (default 50).
        project_dir: Project directory (defaults to BATON_PROJECT_DIR or cwd).
    """
    if project_dir:
        os.environ["BATON_PROJECT_DIR"] = project_dir

    d = _project_dir()
    records = read_jsonl(d, SIGNALS_FILE, last_n=last_n)
    if not records:
        return "No signal data found."

    if node:
        records = [r for r in records if r.get("node_name") == node]
    if path:
        records = [r for r in records if path in r.get("path", "")]

    if not records:
        return "No signals match the filter criteria."

    return _json_pretty(records)


@mcp.tool()
def signal_stats(node: str = "", project_dir: str = "") -> str:
    """Per-path signal statistics: count, avg latency, error rate.

    Args:
        node: Filter to a specific node.
        project_dir: Project directory (defaults to BATON_PROJECT_DIR or cwd).
    """
    if project_dir:
        os.environ["BATON_PROJECT_DIR"] = project_dir

    d = _project_dir()
    records = read_jsonl(d, SIGNALS_FILE)
    if not records:
        return "No signal data found."

    if node:
        records = [r for r in records if r.get("node_name") == node]

    # Aggregate per path
    stats: dict[str, dict] = {}
    for r in records:
        p = r.get("path", "")
        if p not in stats:
            stats[p] = {"count": 0, "latencies": [], "errors": 0}
        stats[p]["count"] += 1
        stats[p]["latencies"].append(r.get("latency_ms", 0))
        if r.get("status_code", 0) >= 400:
            stats[p]["errors"] += 1

    result = {}
    for p, s in stats.items():
        count = s["count"]
        avg_lat = sum(s["latencies"]) / count if count else 0
        result[p] = {
            "count": count,
            "avg_latency_ms": round(avg_lat, 2),
            "error_count": s["errors"],
            "error_rate": round(s["errors"] / count, 4) if count else 0,
        }

    return _json_pretty(result)


@mcp.tool()
def show_topology(project_dir: str = "") -> str:
    """Show the circuit topology (nodes and edges).

    Args:
        project_dir: Project directory (defaults to BATON_PROJECT_DIR or cwd).
    """
    if project_dir:
        os.environ["BATON_PROJECT_DIR"] = project_dir
    return resource_topology()


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


@mcp.prompt()
def circuit_overview() -> str:
    """Full circuit overview: topology, state, and routing in one block."""
    parts = []

    spec = _load_spec()
    if spec:
        parts.append(f"## Circuit: {spec.name} (v{spec.version})")
        parts.append(f"Nodes: {len(spec.nodes)}, Edges: {len(spec.edges)}")
        parts.append("")
        parts.append("### Nodes")
        for n in spec.nodes:
            parts.append(f"- {n.name} (:{n.port}, {n.role}, {n.proxy_mode})")
        parts.append("")
        parts.append("### Edges")
        for e in spec.edges:
            label = f" [{e.label}]" if e.label else ""
            parts.append(f"- {e.source} -> {e.target}{label}")
    else:
        parts.append("No circuit topology found.")

    parts.append("")
    state = _load_state()
    if state:
        parts.append("### Runtime State")
        parts.append(f"Collapse: {state.collapse_level}")
        parts.append(f"Live nodes: {', '.join(state.live_nodes) or 'none'}")
        for name, a in state.adapters.items():
            svc = "mock" if a.service.is_mock else a.service.command or "none"
            parts.append(f"- {name}: {a.status} / {a.last_health_verdict} ({svc})")
    else:
        parts.append("No runtime state (circuit not running).")

    return "\n".join(parts)


def main():
    """Run the Baton MCP server (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
