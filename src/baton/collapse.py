"""Circuit collapse algorithm.

Compresses the circuit by replacing non-live nodes with a single MockServer
process that serves all their contracts simultaneously.
"""

from __future__ import annotations

import logging
from pathlib import Path

from baton.adapter import BackendTarget
from baton.mock import MockServer, load_routes
from baton.schemas import CircuitSpec

logger = logging.getLogger(__name__)


def build_mock_server(
    circuit: CircuitSpec,
    live_nodes: set[str],
    project_dir: str | Path = ".",
) -> MockServer:
    """Build a MockServer for all non-live nodes.

    For each mocked node:
    - If it has a contract, load routes from the spec
    - Otherwise, add default health/status routes

    The MockServer listens on each mocked node's port directly,
    so adapters for mocked nodes should point to localhost:<node_port+20000>.
    We actually use the service port convention (port + 20000) so the
    adapter can still sit in front.
    """
    mock = MockServer()

    for node in circuit.nodes:
        if node.name in live_nodes:
            continue

        service_port = node.port + 20000
        if service_port > 65535:
            service_port = node.port + 5000

        if node.contract:
            spec_path = str(Path(project_dir) / node.contract)
            routes = load_routes(spec_path)
            if routes:
                mock.add_routes(service_port, routes)
                logger.info(
                    f"Mock [{node.name}] loaded {len(routes)} routes "
                    f"from {node.contract} on port {service_port}"
                )
            else:
                mock.add_default_routes(service_port)
                logger.info(f"Mock [{node.name}] using defaults on port {service_port}")
        else:
            mock.add_default_routes(service_port)
            logger.info(f"Mock [{node.name}] using defaults on port {service_port}")

    return mock


def compute_mock_backends(
    circuit: CircuitSpec,
    live_nodes: set[str],
) -> dict[str, BackendTarget]:
    """Compute backend targets for mocked nodes.

    Returns a mapping of node_name -> BackendTarget pointing to the
    mock server's port for that node.
    """
    backends: dict[str, BackendTarget] = {}
    for node in circuit.nodes:
        if node.name in live_nodes:
            continue

        service_port = node.port + 20000
        if service_port > 65535:
            service_port = node.port + 5000

        backends[node.name] = BackendTarget(host="127.0.0.1", port=service_port)

    return backends
