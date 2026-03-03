"""Configuration loading for Baton.

Reads baton.yaml from a project directory and produces a CircuitSpec.
Supports both topology-first (baton.yaml nodes/edges) and service-first
(baton-service.yaml manifests) workflows.
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


def load_circuit_from_services(
    project_dir: str | Path,
    service_dirs: list[str | Path] | None = None,
) -> CircuitSpec:
    """Derive CircuitSpec from service manifests.

    If service_dirs is None, discovers them from baton.yaml's 'services'
    key or by scanning subdirectories for baton-service.yaml files.
    """
    from baton.registry import derive_circuit, load_manifests

    base = Path(project_dir)
    if service_dirs is None:
        service_dirs = _discover_service_dirs(base)

    if not service_dirs:
        raise FileNotFoundError("No service directories found")

    manifests = load_manifests(service_dirs)

    circuit_name = "default"
    config_path = base / CONFIG_FILENAME
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
        circuit_name = raw.get("name", "default")

    return derive_circuit(manifests, circuit_name=circuit_name)


def _discover_service_dirs(project_dir: Path) -> list[Path]:
    """Auto-discover service directories.

    1. Check baton.yaml for a 'services' list of paths.
    2. Otherwise, scan immediate subdirectories for baton-service.yaml.
    """
    from baton.manifest import MANIFEST_FILENAME

    config_path = project_dir / CONFIG_FILENAME
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
        if "services" in raw:
            return [project_dir / s for s in raw["services"]]

    dirs = []
    if project_dir.is_dir():
        for child in sorted(project_dir.iterdir()):
            if child.is_dir() and (child / MANIFEST_FILENAME).exists():
                dirs.append(child)
    return dirs


def add_service_path(project_dir: str | Path, service_path: str) -> None:
    """Add a service directory path to baton.yaml's services list."""
    base = Path(project_dir)
    config_path = base / CONFIG_FILENAME
    if not config_path.exists():
        raise FileNotFoundError(f"No {CONFIG_FILENAME} found in {project_dir}")

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    services = raw.get("services", [])
    if service_path not in services:
        services.append(service_path)
    raw["services"] = services

    with open(config_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False)


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
            if n.role != "service":
                nd["role"] = str(n.role)
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
