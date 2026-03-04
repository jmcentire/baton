"""Service registry and circuit derivation.

Pure functions that take service manifests and produce a CircuitSpec.
"""

from __future__ import annotations

from pathlib import Path

from baton.circuit import DEFAULT_PORT_START, DEFAULT_PORT_MAX
from baton.manifest import load_manifest
from baton.schemas import (
    CircuitSpec,
    EdgeSpec,
    NodeSpec,
    ServiceManifest,
)


def load_manifests(service_dirs: list[str | Path]) -> list[ServiceManifest]:
    """Load manifests from multiple service directories.

    Validates that all service names are unique.
    """
    manifests = []
    for d in service_dirs:
        manifests.append(load_manifest(d))
    names = [m.name for m in manifests]
    if len(names) != len(set(names)):
        dupes = {n for n in names if names.count(n) > 1}
        raise ValueError(f"Duplicate service names: {dupes}")
    return manifests


def derive_circuit(
    manifests: list[ServiceManifest],
    circuit_name: str = "default",
) -> CircuitSpec:
    """Derive a CircuitSpec from a list of service manifests.

    1. Create a NodeSpec for each manifest (auto-assign ports if needed).
    2. Set contract = mock_spec or api_spec for mock generation.
    3. For each dependency, create an EdgeSpec (consumer -> provider).
    4. Missing required dependency raises ValueError; optional missing is skipped.
    """
    by_name = {m.name: m for m in manifests}

    # Assign ports
    used_ports: set[int] = set()
    nodes: list[NodeSpec] = []
    for m in manifests:
        port = m.port
        if port == 0:
            port = _next_port(used_ports)
        if port in used_ports:
            raise ValueError(f"Port conflict for service '{m.name}': {port}")
        used_ports.add(port)

        contract = m.mock_spec or m.api_spec
        nodes.append(NodeSpec(
            name=m.name,
            port=port,
            proxy_mode=m.proxy_mode,
            contract=contract,
            role=m.role,
            metadata=dict(m.metadata),
        ))

    # Build edges from dependencies
    edges: list[EdgeSpec] = []
    for m in manifests:
        for dep in m.dependencies:
            if dep.name not in by_name:
                if dep.optional:
                    continue
                raise ValueError(
                    f"Service '{m.name}' depends on '{dep.name}' "
                    f"which is not registered"
                )
            edges.append(EdgeSpec(
                source=m.name,
                target=dep.name,
                label="depends-on",
            ))

    return CircuitSpec(
        name=circuit_name,
        version=1,
        nodes=nodes,
        edges=edges,
    )


def _next_port(used: set[int]) -> int:
    """Find the next available port in the default range."""
    for port in range(DEFAULT_PORT_START, DEFAULT_PORT_MAX + 1):
        if port not in used:
            return port
    raise RuntimeError("No available ports in range")
