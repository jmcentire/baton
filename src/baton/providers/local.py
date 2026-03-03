"""Local deployment provider.

Deploys circuit nodes as local processes using the LifecycleManager.
This is the default provider for development and testing.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from baton.adapter import BackendTarget
from baton.collapse import build_mock_server, compute_mock_backends
from baton.config import load_circuit
from baton.lifecycle import LifecycleManager
from baton.schemas import CircuitSpec, CircuitState, CollapseLevel, DeploymentTarget, NodeStatus

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalProvider:
    """Deploy circuit as local processes."""

    def __init__(self) -> None:
        self._mgr: LifecycleManager | None = None
        self._mock_server = None

    async def deploy(self, circuit: CircuitSpec, target: DeploymentTarget) -> CircuitState:
        """Deploy circuit locally.

        Config options:
            project_dir: Project directory (required)
            mock: "true" to start with all mocks (default: "true")
            live: Comma-separated node names to slot with their manifest commands
        """
        project_dir = target.config.get("project_dir", ".")
        mock = target.config.get("mock", "true").lower() == "true"

        self._mgr = LifecycleManager(project_dir)
        state = await self._mgr.up(mock=mock)

        if mock:
            live_names = set()
            live_csv = target.config.get("live", "")
            if live_csv:
                live_names = {n.strip() for n in live_csv.split(",") if n.strip()}

            mock_server = build_mock_server(circuit, live_nodes=live_names, project_dir=project_dir)
            backends = compute_mock_backends(circuit, live_nodes=live_names)

            await mock_server.start()
            self._mock_server = mock_server

            for node_name, bt in backends.items():
                adapter = self._mgr.adapters.get(node_name)
                if adapter:
                    adapter.set_backend(bt)
                    if state.adapters.get(node_name):
                        state.adapters[node_name].status = NodeStatus.ACTIVE

            state.live_nodes = list(live_names)
            if live_names:
                if len(live_names) == len(circuit.nodes):
                    state.collapse_level = CollapseLevel.FULL_LIVE
                else:
                    state.collapse_level = CollapseLevel.PARTIAL
            else:
                state.collapse_level = CollapseLevel.FULL_MOCK

        logger.info(f"Local deploy complete: {len(state.adapters)} nodes")
        return state

    async def teardown(self, circuit: CircuitSpec, target: DeploymentTarget) -> None:
        """Tear down local deployment."""
        if self._mock_server:
            await self._mock_server.stop()
            self._mock_server = None
        if self._mgr:
            await self._mgr.down()
            self._mgr = None
        logger.info("Local teardown complete")

    async def status(self, circuit: CircuitSpec, target: DeploymentTarget) -> CircuitState:
        """Return current state of local deployment."""
        if self._mgr and self._mgr.state:
            return self._mgr.state
        return CircuitState(
            circuit_name=circuit.name,
            collapse_level=CollapseLevel.FULL_MOCK,
        )
