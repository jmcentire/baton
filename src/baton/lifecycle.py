"""Circuit lifecycle orchestration.

Manages the circuit through: init -> up -> [slot/swap] -> down
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from baton.adapter import Adapter, BackendTarget
from baton.adapter_control import AdapterControlServer
from baton.config import load_circuit, save_circuit
from baton.process import ProcessManager
from baton.schemas import (
    AdapterState,
    CircuitSpec,
    CircuitState,
    CollapseLevel,
    NodeRole,
    NodeStatus,
    RoutingConfig,
    ServiceSlot,
)
from baton.state import ensure_baton_dir, load_state, save_state

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LifecycleManager:
    """Orchestrates the circuit lifecycle."""

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir)
        self._adapters: dict[str, Adapter] = {}
        self._controls: dict[str, AdapterControlServer] = {}
        self._process_mgr = ProcessManager()
        self._circuit: CircuitSpec | None = None
        self._state: CircuitState | None = None

    @property
    def adapters(self) -> dict[str, Adapter]:
        return dict(self._adapters)

    @property
    def state(self) -> CircuitState | None:
        return self._state

    async def up(self, mock: bool = True) -> CircuitState:
        """Boot the circuit: start all adapters.

        Args:
            mock: If True, adapters start with no backend (503).
                  Mock generation is handled by collapse module.
        """
        self._circuit = load_circuit(self.project_dir)
        ensure_baton_dir(self.project_dir)

        self._state = CircuitState(
            circuit_name=self._circuit.name,
            collapse_level=CollapseLevel.FULL_MOCK if mock else CollapseLevel.FULL_LIVE,
            started_at=_now_iso(),
            updated_at=_now_iso(),
        )

        for node in self._circuit.nodes:
            adapter = Adapter(node)
            await adapter.start()
            self._adapters[node.name] = adapter

            control = AdapterControlServer(adapter)
            await control.start()
            self._controls[node.name] = control

            self._state.adapters[node.name] = AdapterState(
                node_name=node.name,
                status=NodeStatus.LISTENING,
            )

        # Warn if no ingress nodes defined
        if not self._circuit.ingress_nodes:
            logger.warning("No ingress nodes defined. Consider adding --role ingress to entry-point nodes.")

        save_state(self._state, self.project_dir)
        logger.info(f"Circuit '{self._circuit.name}' is up with {len(self._adapters)} nodes")
        return self._state

    async def down(self) -> None:
        """Tear down the circuit: stop all adapters and processes."""
        await self._process_mgr.stop_all()

        for name, control in self._controls.items():
            await control.stop()
        self._controls.clear()

        for name, adapter in self._adapters.items():
            await adapter.drain(timeout=5.0)
            await adapter.stop()
        self._adapters.clear()

        if self._state:
            self._state.adapters.clear()
            self._state.updated_at = _now_iso()
            save_state(self._state, self.project_dir)

        logger.info("Circuit is down")

    async def slot(self, node_name: str, command: str, env: dict[str, str] | None = None) -> None:
        """Slot a live service into a node's adapter.

        Starts the service process, waits for it to be ready,
        then points the adapter at it.
        """
        adapter = self._adapters.get(node_name)
        if adapter is None:
            raise ValueError(f"Node '{node_name}' not found in running circuit")

        if adapter.routing and adapter.routing.locked:
            raise RuntimeError(f"Cannot slot into '{node_name}': routing config is locked")

        node = adapter.node
        if node.role == NodeRole.EGRESS:
            raise ValueError(
                f"Cannot slot a live service into egress node '{node_name}'. "
                "Egress nodes represent external services and should use mock configuration."
            )

        # Service listens on a dynamically assigned port
        service_port = node.port + 20000
        if service_port > 65535:
            service_port = node.port + 5000

        env = dict(env or {})
        env["BATON_SERVICE_PORT"] = str(service_port)
        env["BATON_NODE_NAME"] = node_name

        info = await self._process_mgr.start(node_name, command, env=env)

        # Wait briefly for the service to start
        await asyncio.sleep(0.5)

        adapter.set_backend(BackendTarget(host="127.0.0.1", port=service_port))

        if self._state:
            self._state.adapters[node_name] = AdapterState(
                node_name=node_name,
                status=NodeStatus.ACTIVE,
                adapter_pid=0,
                service=ServiceSlot(
                    command=command,
                    is_mock=False,
                    pid=info.pid,
                    started_at=_now_iso(),
                ),
            )
            if node_name not in self._state.live_nodes:
                self._state.live_nodes.append(node_name)
            self._state.collapse_level = self._compute_collapse_level()
            self._state.updated_at = _now_iso()
            save_state(self._state, self.project_dir)

        logger.info(f"Slotted service into [{node_name}] (pid={info.pid}, port={service_port})")

    async def swap(self, node_name: str, command: str, env: dict[str, str] | None = None) -> None:
        """Hot-swap a service: start new, drain, switch, stop old.

        The new service is running before the old one is removed.
        """
        adapter = self._adapters.get(node_name)
        if adapter is None:
            raise ValueError(f"Node '{node_name}' not found in running circuit")

        if adapter.routing and adapter.routing.locked:
            raise RuntimeError(f"Cannot swap in '{node_name}': routing config is locked")

        old_pid = self._process_mgr.get_pid(node_name)

        node = adapter.node
        service_port = node.port + 20000
        if service_port > 65535:
            service_port = node.port + 5000

        env = dict(env or {})
        env["BATON_SERVICE_PORT"] = str(service_port)
        env["BATON_NODE_NAME"] = node_name

        # Start new process under a temp name
        temp_name = f"{node_name}__swap"
        info = await self._process_mgr.start(temp_name, command, env=env)
        await asyncio.sleep(0.5)

        # Drain old connections
        await adapter.drain(timeout=10.0)

        # Swap backend
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=service_port))

        # Stop old process
        if old_pid is not None:
            await self._process_mgr.stop(node_name)

        # Move temp process to the real name
        if temp_name in self._process_mgr._processes:
            self._process_mgr._processes[node_name] = self._process_mgr._processes.pop(temp_name)

        if self._state:
            self._state.adapters[node_name] = AdapterState(
                node_name=node_name,
                status=NodeStatus.ACTIVE,
                service=ServiceSlot(
                    command=command,
                    is_mock=False,
                    pid=info.pid,
                    started_at=_now_iso(),
                ),
            )
            self._state.updated_at = _now_iso()
            save_state(self._state, self.project_dir)

        logger.info(f"Swapped service in [{node_name}] (new pid={info.pid})")

    async def slot_mock(self, node_name: str) -> None:
        """Replace a live service with nothing (adapter returns 503)."""
        adapter = self._adapters.get(node_name)
        if adapter is None:
            raise ValueError(f"Node '{node_name}' not found in running circuit")

        await self._process_mgr.stop(node_name)
        adapter.set_backend(BackendTarget())

        if self._state:
            self._state.adapters[node_name] = AdapterState(
                node_name=node_name,
                status=NodeStatus.LISTENING,
            )
            if node_name in self._state.live_nodes:
                self._state.live_nodes.remove(node_name)
            self._state.collapse_level = self._compute_collapse_level()
            self._state.updated_at = _now_iso()
            save_state(self._state, self.project_dir)

    async def slot_ab(
        self,
        node_name: str,
        command_a: str,
        command_b: str,
        split: tuple[int, int] = (80, 20),
    ) -> None:
        """Start two instances and configure weighted routing.

        Instance A runs on node.port + 20000, Instance B on node.port + 20001.
        """
        adapter = self._adapters.get(node_name)
        if adapter is None:
            raise ValueError(f"Node '{node_name}' not found in running circuit")

        if adapter.routing and adapter.routing.locked:
            raise RuntimeError(f"Cannot slot_ab into '{node_name}': routing config is locked")

        node = adapter.node
        port_a = node.port + 20000
        if port_a > 65535:
            port_a = node.port + 5000
        port_b = port_a + 1

        env_a = {
            "BATON_SERVICE_PORT": str(port_a),
            "BATON_NODE_NAME": node_name,
        }
        env_b = {
            "BATON_SERVICE_PORT": str(port_b),
            "BATON_NODE_NAME": node_name,
        }

        key_a = f"{node_name}__a"
        key_b = f"{node_name}__b"

        info_a = await self._process_mgr.start(key_a, command_a, env=env_a)
        info_b = await self._process_mgr.start(key_b, command_b, env=env_b)
        await asyncio.sleep(0.5)

        from baton.routing import ab_split
        config = ab_split("127.0.0.1", port_a, port_b, pct_a=split[0])
        adapter.set_routing(config)

        if self._state:
            self._state.adapters[node_name] = AdapterState(
                node_name=node_name,
                status=NodeStatus.ACTIVE,
                service=ServiceSlot(
                    command=f"{command_a} | {command_b}",
                    is_mock=False,
                    pid=info_a.pid,
                    started_at=_now_iso(),
                ),
                routing_config=config.model_dump(),
            )
            if node_name not in self._state.live_nodes:
                self._state.live_nodes.append(node_name)
            self._state.collapse_level = self._compute_collapse_level()
            self._state.updated_at = _now_iso()
            save_state(self._state, self.project_dir)

        logger.info(
            f"Slotted A/B into [{node_name}] "
            f"(a={info_a.pid}:{port_a}, b={info_b.pid}:{port_b}, split={split})"
        )

    async def route_ab(
        self,
        node_name: str,
        command_b: str,
        split: tuple[int, int] = (80, 20),
    ) -> None:
        """Add a second instance to an existing service and configure weighted routing.

        Reuses the already-running service as instance A. Starts command_b as instance B.
        If no service is running, raises ValueError.
        """
        adapter = self._adapters.get(node_name)
        if adapter is None:
            raise ValueError(f"Node '{node_name}' not found in running circuit")

        if adapter.routing and adapter.routing.locked:
            raise RuntimeError(f"Cannot route_ab on '{node_name}': routing config is locked")

        node = adapter.node
        port_a = node.port + 20000
        if port_a > 65535:
            port_a = node.port + 5000

        # Verify instance A is running
        if not self._process_mgr.is_running(node_name) and not adapter.backend.is_configured:
            raise ValueError(
                f"No service running on '{node_name}'. Use 'baton slot' first, "
                "or use 'slot_ab' to start both instances."
            )

        # If service is running under the base name, move it to __a key
        if self._process_mgr.is_running(node_name):
            key_a = f"{node_name}__a"
            if node_name in self._process_mgr._processes:
                self._process_mgr._processes[key_a] = self._process_mgr._processes.pop(node_name)

        port_b = port_a + 1
        env_b = {
            "BATON_SERVICE_PORT": str(port_b),
            "BATON_NODE_NAME": node_name,
        }

        key_b = f"{node_name}__b"
        info_b = await self._process_mgr.start(key_b, command_b, env=env_b)
        await asyncio.sleep(0.5)

        from baton.routing import ab_split
        config = ab_split("127.0.0.1", port_a, port_b, pct_a=split[0])
        adapter.set_routing(config)

        if self._state:
            self._state.adapters[node_name].routing_config = config.model_dump()
            self._state.adapters[node_name].status = NodeStatus.ACTIVE
            self._state.updated_at = _now_iso()
            save_state(self._state, self.project_dir)

        logger.info(
            f"Route A/B on [{node_name}] (a=:{port_a}, b={info_b.pid}:{port_b}, split={split})"
        )

    def set_routing(self, node_name: str, config: RoutingConfig) -> None:
        """Set routing configuration on a node's adapter."""
        adapter = self._adapters.get(node_name)
        if adapter is None:
            raise ValueError(f"Node '{node_name}' not found in running circuit")
        adapter.set_routing(config)

        if self._state and node_name in self._state.adapters:
            self._state.adapters[node_name].routing_config = config.model_dump()
            self._state.updated_at = _now_iso()
            save_state(self._state, self.project_dir)

    def lock_routing(self, node_name: str) -> None:
        """Lock routing config to prevent changes. Bypasses adapter lock via direct assignment."""
        adapter = self._adapters.get(node_name)
        if adapter is None:
            raise ValueError(f"Node '{node_name}' not found in running circuit")

        current = adapter.routing
        if current is None:
            raise ValueError(f"No routing config to lock on '{node_name}'")

        locked = RoutingConfig(
            strategy=current.strategy,
            targets=list(current.targets),
            rules=list(current.rules),
            default_target=current.default_target,
            locked=True,
        )
        # Direct assignment bypasses the lock check
        adapter._routing = locked

        if self._state and node_name in self._state.adapters:
            self._state.adapters[node_name].routing_config = locked.model_dump()
            self._state.updated_at = _now_iso()
            save_state(self._state, self.project_dir)

    def unlock_routing(self, node_name: str) -> None:
        """Unlock routing config to allow changes."""
        adapter = self._adapters.get(node_name)
        if adapter is None:
            raise ValueError(f"Node '{node_name}' not found in running circuit")

        current = adapter.routing
        if current is None:
            raise ValueError(f"No routing config to unlock on '{node_name}'")

        unlocked = RoutingConfig(
            strategy=current.strategy,
            targets=list(current.targets),
            rules=list(current.rules),
            default_target=current.default_target,
            locked=False,
        )
        adapter._routing = unlocked

        if self._state and node_name in self._state.adapters:
            self._state.adapters[node_name].routing_config = unlocked.model_dump()
            self._state.updated_at = _now_iso()
            save_state(self._state, self.project_dir)

    async def restart_service(self, node_name: str) -> None:
        """Restart the service in a node (used by custodian)."""
        if self._state and node_name in self._state.adapters:
            service = self._state.adapters[node_name].service
            if service.command and not service.is_mock:
                await self.slot(node_name, service.command)

    def _compute_collapse_level(self) -> CollapseLevel:
        if not self._state or not self._circuit:
            return CollapseLevel.FULL_MOCK
        total = len(self._circuit.nodes)
        live = len(self._state.live_nodes)
        if live == 0:
            return CollapseLevel.FULL_MOCK
        elif live == total:
            return CollapseLevel.FULL_LIVE
        else:
            return CollapseLevel.PARTIAL
