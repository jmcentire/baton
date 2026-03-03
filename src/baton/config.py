"""Configuration loading for Baton.

Reads baton.yaml from a project directory and produces a CircuitSpec.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from baton.schemas import CircuitSpec, EdgeSpec, NodeSpec

CONFIG_FILENAME = "baton.yaml"


def load_circuit(project_dir: str | Path) -> CircuitSpec:
    """Load CircuitSpec from baton.yaml in the given directory."""
    path = Path(project_dir) / CONFIG_FILENAME
    if not path.exists():
        raise FileNotFoundError(f"No {CONFIG_FILENAME} found in {project_dir}")
    with open(path) as f:
        raw = yaml.safe_load(f)
    if raw is None:
        return CircuitSpec()
    return _parse_circuit(raw)


def save_circuit(circuit: CircuitSpec, project_dir: str | Path) -> None:
    """Save CircuitSpec to baton.yaml in the given directory."""
    path = Path(project_dir) / CONFIG_FILENAME
    data = _serialize_circuit(circuit)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _parse_circuit(raw: dict) -> CircuitSpec:
    """Parse raw YAML dict into CircuitSpec."""
    nodes = []
    for n in raw.get("nodes", []):
        nodes.append(NodeSpec(**n))
    edges = []
    for e in raw.get("edges", []):
        edges.append(EdgeSpec(**e))
    return CircuitSpec(
        name=raw.get("name", "default"),
        version=raw.get("version", 1),
        nodes=nodes,
        edges=edges,
    )


def _serialize_circuit(circuit: CircuitSpec) -> dict:
    """Convert CircuitSpec to a YAML-serializable dict."""
    data: dict = {
        "name": circuit.name,
        "version": circuit.version,
    }
    if circuit.nodes:
        data["nodes"] = []
        for n in circuit.nodes:
            nd: dict = {"name": n.name, "port": n.port}
            if n.host != "127.0.0.1":
                nd["host"] = n.host
            if n.proxy_mode != "http":
                nd["proxy_mode"] = str(n.proxy_mode)
            if n.contract:
                nd["contract"] = n.contract
            if n.metadata:
                nd["metadata"] = dict(n.metadata)
            data["nodes"].append(nd)
    if circuit.edges:
        data["edges"] = []
        for e in circuit.edges:
            ed: dict = {"source": e.source, "target": e.target}
            if e.label:
                ed["label"] = e.label
            data["edges"].append(ed)
    return data
