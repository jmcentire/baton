"""Aggregated dashboard for circuit-wide metrics.

Collects metrics from all adapters into a single snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from baton.adapter import Adapter
from baton.schemas import CircuitSpec, CircuitState, HealthVerdict, NodeRole


@dataclass
class NodeSnapshot:
    """Single node's metrics at a point in time."""

    name: str
    role: str = "service"
    status: str = "unknown"
    health: str = "unknown"
    requests_total: int = 0
    requests_failed: int = 0
    error_rate: float = 0.0
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    active_connections: int = 0
    routing_strategy: str | None = None
    routing_locked: bool = False


@dataclass
class DashboardSnapshot:
    """Point-in-time snapshot of all node metrics."""

    timestamp: str = ""
    nodes: dict[str, NodeSnapshot] = field(default_factory=dict)


async def collect(
    adapters: dict[str, Adapter],
    state: CircuitState,
    circuit: CircuitSpec,
) -> DashboardSnapshot:
    """Collect metrics from all adapters into a snapshot."""
    snapshot = DashboardSnapshot(
        timestamp=datetime.now(timezone.utc).isoformat()
    )

    node_roles = {n.name: n.role for n in circuit.nodes}

    for name, adapter in adapters.items():
        m = adapter.metrics
        health = await adapter.health_check()

        error_rate = 0.0
        if m.requests_total > 0:
            error_rate = m.requests_failed / m.requests_total

        adapter_state = state.adapters.get(name)
        status_str = str(adapter_state.status) if adapter_state else "unknown"

        role = node_roles.get(name, NodeRole.SERVICE)

        routing_strategy = None
        routing_locked = False
        if adapter.routing:
            routing_strategy = str(adapter.routing.strategy)
            routing_locked = adapter.routing.locked
        else:
            routing_strategy = "single"

        snapshot.nodes[name] = NodeSnapshot(
            name=name,
            role=str(role),
            status=status_str,
            health=str(health.verdict),
            requests_total=m.requests_total,
            requests_failed=m.requests_failed,
            error_rate=round(error_rate, 4),
            latency_p50=m.p50(),
            latency_p95=m.p95(),
            active_connections=m.active_connections,
            routing_strategy=routing_strategy,
            routing_locked=routing_locked,
        )

    return snapshot


def format_table(snapshot: DashboardSnapshot) -> str:
    """Format snapshot as a human-readable table."""
    if not snapshot.nodes:
        return "No nodes in snapshot."

    header = f"{'Node':<14} {'Role':<10} {'Status':<10} {'Health':<10} {'Reqs':>6} {'Err%':>6} {'p50':>8} {'p95':>8} {'Routing'}"
    lines = [header, "-" * len(header)]

    for node in snapshot.nodes.values():
        err_pct = f"{node.error_rate * 100:.1f}%" if node.requests_total > 0 else "—"
        p50 = f"{node.latency_p50:.0f}ms" if node.latency_p50 > 0 else "—"
        p95 = f"{node.latency_p95:.0f}ms" if node.latency_p95 > 0 else "—"
        routing = node.routing_strategy or "single"
        if node.routing_locked:
            routing += " (locked)"

        lines.append(
            f"{node.name:<14} {node.role:<10} {node.status:<10} {node.health:<10} "
            f"{node.requests_total:>6} {err_pct:>6} {p50:>8} {p95:>8} {routing}"
        )

    return "\n".join(lines)
