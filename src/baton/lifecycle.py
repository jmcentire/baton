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
from baton.config import load_circuit, load_circuit_config, save_circuit
from baton.dora import EventType, record_event
from baton.process import ProcessManager
from baton.schemas import (
    AdapterState,
    CircuitConfig,
    CircuitSpec,
    CircuitState,
    CollapseLevel,
    EdgePolicy,
    NodeRole,
    NodeStatus,
    RoutingConfig,
    SecurityConfig,
    ServiceSlot,
)
from baton.state import ensure_baton_dir, load_state, save_circuit_spec, save_state
from baton.tracing import SpanExporter, create_span_exporter

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_node_policy(circuit: CircuitSpec, node_name: str) -> EdgePolicy | None:
    """Collect edge policies targeting a node and merge with most-restrictive logic."""
    policies = [e.policy for e in circuit.edges if e.target == node_name and e.policy is not None]
    if not policies:
        return None
    if len(policies) == 1:
        return policies[0]
    # Merge: min timeout, max retries, min backoff, min nonzero threshold
    timeout = min(p.timeout_ms for p in policies)
    retries = max(p.retries for p in policies)
    backoff = min(p.retry_backoff_ms for p in policies)
    thresholds = [p.circuit_breaker_threshold for p in policies if p.circuit_breaker_threshold > 0]
    threshold = min(thresholds) if thresholds else 0
    return EdgePolicy(
        timeout_ms=timeout, retries=retries,
        retry_backoff_ms=backoff, circuit_breaker_threshold=threshold,
    )


def _build_ssl_context(tls_config) -> "ssl.SSLContext | None":
    """Create an SSL context from TLS config if cert/key exist."""
    import ssl
    from pathlib import Path as _Path
    if tls_config.mode == "off":
        return None
    cert_path = _Path(tls_config.cert) if tls_config.cert else None
    key_path = _Path(tls_config.key) if tls_config.key else None
    if cert_path and key_path and cert_path.exists() and key_path.exists():
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert_path), str(key_path))
        return ctx
    return None


class LifecycleManager:
    """Orchestrates the circuit lifecycle."""

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir)
        self._adapters: dict[str, Adapter] = {}
        self._controls: dict[str, AdapterControlServer] = {}
        self._process_mgr = ProcessManager()
        self._circuit: CircuitSpec | None = None
        self._state: CircuitState | None = None
        self._span_exporter: SpanExporter | None = None
        self._cert_manager = None  # CertificateManager
        self._federation_server = None  # FederationServer
        self._federation_manager = None  # FederationManager
        self._federation_task: asyncio.Task | None = None

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

        import os
        self._state = CircuitState(
            circuit_name=self._circuit.name,
            collapse_level=CollapseLevel.FULL_MOCK if mock else CollapseLevel.FULL_LIVE,
            owner_pid=os.getpid(),
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
        # Stop federation
        if self._federation_manager:
            self._federation_manager.stop()
        if self._federation_task and not self._federation_task.done():
            self._federation_task.cancel()
            try:
                await self._federation_task
            except asyncio.CancelledError:
                pass
            self._federation_task = None
        if self._federation_server:
            await self._federation_server.stop()
            self._federation_server = None
        self._federation_manager = None

        # Stop cert manager
        if self._cert_manager:
            self._cert_manager.stop()
            self._cert_manager = None

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
        record_event(
            self.project_dir, EventType.DEPLOY, node_name,
            detail=f"slot command={command} port={service_port} pid={info.pid}",
        )

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
        record_event(
            self.project_dir, EventType.SWAP, node_name,
            detail=f"hot-swap command={command} pid={info.pid}",
        )

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

    async def start_canary(
        self,
        node_name: str,
        command: str,
        canary_pct: int = 10,
        **controller_opts,
    ) -> "CanaryController":
        """Start a canary deployment with automatic promotion/rollback.

        Starts the canary instance on port+20001, configures canary routing
        at the initial percentage, and returns a running CanaryController.
        """
        from baton.canary import CanaryController
        from baton.routing import canary as canary_routing

        adapter = self._adapters.get(node_name)
        if adapter is None:
            raise ValueError(f"Node '{node_name}' not found in running circuit")

        if adapter.routing and adapter.routing.locked:
            raise RuntimeError(f"Cannot start canary on '{node_name}': routing config is locked")

        node = adapter.node

        # Stable runs on port+20000 (already running from a previous slot)
        port_stable = node.port + 20000
        if port_stable > 65535:
            port_stable = node.port + 5000

        # Verify stable instance is running
        if not self._process_mgr.is_running(node_name) and not adapter.backend.is_configured:
            raise ValueError(
                f"No service running on '{node_name}'. Use 'baton slot' first."
            )

        # Move existing process to __stable key
        if self._process_mgr.is_running(node_name):
            key_stable = f"{node_name}__stable"
            if node_name in self._process_mgr._processes:
                self._process_mgr._processes[key_stable] = self._process_mgr._processes.pop(node_name)

        # Start canary instance
        port_canary = port_stable + 1
        env = {
            "BATON_SERVICE_PORT": str(port_canary),
            "BATON_NODE_NAME": node_name,
        }
        key_canary = f"{node_name}__canary"
        await self._process_mgr.start(key_canary, command, env=env)
        await asyncio.sleep(0.5)

        # Set initial canary routing
        config = canary_routing("127.0.0.1", port_stable, port_canary, canary_pct=canary_pct)
        adapter.set_routing(config)

        if self._state and node_name in self._state.adapters:
            self._state.adapters[node_name].routing_config = config.model_dump()
            self._state.adapters[node_name].status = NodeStatus.ACTIVE
            self._state.updated_at = _now_iso()
            save_state(self._state, self.project_dir)

        record_event(
            self.project_dir, EventType.CANARY_START, node_name,
            detail=f"canary_pct={canary_pct} command={command}",
        )

        controller = CanaryController(
            adapter, node_name, self, project_dir=self.project_dir,
            **controller_opts,
        )
        return controller

    async def restart_service(self, node_name: str) -> None:
        """Restart the service in a node (used by custodian)."""
        if self._state and node_name in self._state.adapters:
            service = self._state.adapters[node_name].service
            if service.command and not service.is_mock:
                await self.slot(node_name, service.command)

    async def _apply_via_provider(self, config: CircuitConfig) -> CircuitState:
        """Delegate apply to a deployment provider (non-local)."""
        from baton.providers import create_provider
        from baton.schemas import DeploymentTarget

        spec = config.to_circuit_spec()
        provider = create_provider(config.deploy.provider)
        target = DeploymentTarget(
            provider=config.deploy.provider,
            region=config.deploy.region,
            namespace=config.deploy.namespace,
            config={
                "project_dir": str(self.project_dir),
                "project": config.deploy.project,
                **({"build": "true"} if config.deploy.build else {}),
                **({"image_template": config.deploy.image} if config.deploy.image else {}),
            },
        )
        state = await provider.deploy(spec, target)
        self._state = state
        save_state(state, self.project_dir)
        return state

    async def apply(self, config: CircuitConfig) -> CircuitState:
        """Converge running state to match the declarative CircuitConfig.

        1. No running state -> boot circuit + apply routing
        2. Same topology, different routing -> update routing in-place
        3. Topology changed -> incremental add/remove or reboot
        4. Same config twice -> no-op (idempotent)
        5. Non-local provider -> delegate to provider
        """
        if config.deploy.provider != "local":
            return await self._apply_via_provider(config)

        current_state = load_state(self.project_dir)
        desired_spec = config.to_circuit_spec()

        actions = _compute_convergence_actions(config, desired_spec, current_state, self._circuit)

        for action_type, data in actions:
            if action_type == "boot":
                # Full boot from scratch
                import os
                self._circuit = desired_spec
                ensure_baton_dir(self.project_dir)
                self._state = CircuitState(
                    circuit_name=desired_spec.name,
                    collapse_level=CollapseLevel.FULL_MOCK,
                    owner_pid=os.getpid(),
                    started_at=_now_iso(),
                    updated_at=_now_iso(),
                )
                ssl_ctx = _build_ssl_context(config.security.tls)

                # Create span exporter from observability config
                self._span_exporter = create_span_exporter(
                    config.observability.sink, config.observability, self.project_dir,
                )

                for node in desired_spec.nodes:
                    adapter = Adapter(node, ssl_context=ssl_ctx)
                    await adapter.start()
                    # Set edge policy
                    node_policy = _resolve_node_policy(desired_spec, node.name)
                    if node_policy:
                        adapter.set_policy(node_policy)
                    # Wire observability
                    adapter.set_span_exporter(self._span_exporter)
                    node_tel = config.node_telemetry.get(node.name)
                    if node_tel:
                        adapter.set_telemetry_rules(node_tel.classes)
                    self._adapters[node.name] = adapter

                    control = AdapterControlServer(adapter, security=config.security)
                    await control.start()
                    self._controls[node.name] = control

                    self._state.adapters[node.name] = AdapterState(
                        node_name=node.name,
                        status=NodeStatus.LISTENING,
                    )
                save_state(self._state, self.project_dir)
                logger.info(f"Circuit '{desired_spec.name}' booted with {len(self._adapters)} nodes")

                # Start certificate manager if auto_rotate is enabled
                if ssl_ctx and config.security.tls.auto_rotate:
                    self._start_cert_manager(config, ssl_ctx)

                # Start federation if configured
                if config.federation.enabled:
                    await self._start_federation(config)

            elif action_type == "reboot":
                # Topology changed -- tear down and reboot
                await self.down()
                return await self.apply(config)

            elif action_type == "add_node":
                node = data["node"]
                ssl_ctx = _build_ssl_context(config.security.tls)
                adapter = Adapter(node, ssl_context=ssl_ctx)
                await adapter.start()
                node_policy = _resolve_node_policy(desired_spec, node.name)
                if node_policy:
                    adapter.set_policy(node_policy)
                # Wire observability
                if self._span_exporter:
                    adapter.set_span_exporter(self._span_exporter)
                node_tel = config.node_telemetry.get(node.name)
                if node_tel:
                    adapter.set_telemetry_rules(node_tel.classes)
                self._adapters[node.name] = adapter

                control = AdapterControlServer(adapter, security=config.security)
                await control.start()
                self._controls[node.name] = control

                if self._state:
                    self._state.adapters[node.name] = AdapterState(
                        node_name=node.name,
                        status=NodeStatus.LISTENING,
                    )
                # Apply routing if config has it
                if node.name in config.routing:
                    adapter.set_routing(config.routing[node.name])
                    if self._state:
                        self._state.adapters[node.name].routing_config = config.routing[node.name].model_dump()

                logger.info(f"Added node '{node.name}' to circuit")

            elif action_type == "remove_node":
                node_name = data["node_name"]
                adapter = self._adapters.get(node_name)
                if adapter:
                    await adapter.drain(timeout=5.0)
                    await adapter.stop()
                    del self._adapters[node_name]
                control = self._controls.get(node_name)
                if control:
                    await control.stop()
                    del self._controls[node_name]
                # Stop any process for this node
                if self._process_mgr.is_running(node_name):
                    await self._process_mgr.stop(node_name)
                if self._state:
                    self._state.adapters.pop(node_name, None)
                    if node_name in self._state.live_nodes:
                        self._state.live_nodes.remove(node_name)
                logger.info(f"Removed node '{node_name}' from circuit")

            elif action_type == "add_edge":
                # Recompute policy on target adapter
                tgt = data["target"]
                adapter = self._adapters.get(tgt)
                if adapter:
                    node_policy = _resolve_node_policy(desired_spec, tgt)
                    adapter.set_policy(node_policy)

            elif action_type == "remove_edge":
                # Recompute policy on target adapter
                tgt = data["target"]
                adapter = self._adapters.get(tgt)
                if adapter:
                    node_policy = _resolve_node_policy(desired_spec, tgt)
                    adapter.set_policy(node_policy)

            elif action_type == "update_routing":
                # Same topology, update routing in-place
                node_name = data["node_name"]
                routing_config = data["routing_config"]
                adapter = self._adapters.get(node_name)
                if adapter:
                    adapter.set_routing(routing_config)
                    if self._state and node_name in self._state.adapters:
                        self._state.adapters[node_name].routing_config = routing_config.model_dump()

            elif action_type == "clear_routing":
                node_name = data["node_name"]
                adapter = self._adapters.get(node_name)
                if adapter:
                    adapter.clear_routing()
                    if self._state and node_name in self._state.adapters:
                        self._state.adapters[node_name].routing_config = None

        # Apply routing from config
        if actions and actions[0][0] == "boot":
            for node_name, routing_config in config.routing.items():
                adapter = self._adapters.get(node_name)
                if adapter:
                    adapter.set_routing(routing_config)
                    if self._state and node_name in self._state.adapters:
                        self._state.adapters[node_name].routing_config = routing_config.model_dump()

        # Update circuit to desired spec after processing all actions
        self._circuit = desired_spec
        save_circuit_spec(desired_spec, self.project_dir)

        if self._state:
            self._state.updated_at = _now_iso()
            save_state(self._state, self.project_dir)

        return self._state

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

    def _start_cert_manager(self, config: CircuitConfig, ssl_ctx) -> None:
        """Start the CertificateManager for auto-rotation."""
        from baton.certs import CertificateManager

        tls = config.security.tls
        if not tls.cert or not tls.key:
            logger.warning("auto_rotate enabled but no cert/key paths configured")
            return

        self._cert_manager = CertificateManager(
            ssl_context=ssl_ctx,
            cert_path=tls.cert,
            key_path=tls.key,
            check_interval=tls.rotate_check_interval_s,
            warning_days=tls.warning_days,
            critical_days=tls.critical_days,
        )
        # Do initial check
        self._cert_manager.check_now()
        logger.info(f"Certificate manager started (interval={tls.rotate_check_interval_s}s)")

    async def _start_federation(self, config: CircuitConfig) -> None:
        """Start the FederationServer and FederationManager."""
        from baton.federation import FederationManager, FederationServer

        fed = config.federation
        if not fed.identity:
            logger.warning("Federation enabled but no identity configured")
            return

        self._federation_server = FederationServer(
            identity=fed.identity,
            get_local_state=lambda: self._state,
        )
        await self._federation_server.start()

        self._federation_manager = FederationManager(
            config=fed,
            server=self._federation_server,
            get_local_state=lambda: self._state,
        )
        self._federation_task = asyncio.create_task(self._federation_manager.run())
        logger.info(f"Federation started (peers={[p.name for p in fed.peers]})")


def _compute_convergence_actions(
    config: CircuitConfig,
    desired: CircuitSpec,
    current_state: CircuitState | None,
    current_circuit: CircuitSpec | None,
) -> list[tuple[str, dict]]:
    """Compute the actions needed to converge from current state to desired config.

    Returns a list of (action_type, data) tuples.
    """
    actions: list[tuple[str, dict]] = []

    # No running state -> full boot
    if current_state is None or not current_state.adapters:
        actions.append(("boot", {}))
        return actions

    if current_circuit is None:
        actions.append(("boot", {}))
        return actions

    # Build lookup tables
    current_nodes_by_name = {n.name: n for n in current_circuit.nodes}
    desired_nodes_by_name = {n.name: n for n in desired.nodes}
    current_node_names = set(current_nodes_by_name.keys())
    desired_node_names = set(desired_nodes_by_name.keys())

    current_edges = {(e.source, e.target) for e in current_circuit.edges}
    desired_edges = {(e.source, e.target) for e in desired.edges}

    new_nodes = desired_node_names - current_node_names
    removed_nodes = current_node_names - desired_node_names
    common_nodes = current_node_names & desired_node_names

    # Check for changed nodes (same name but different port/mode/role)
    for name in common_nodes:
        cur = current_nodes_by_name[name]
        des = desired_nodes_by_name[name]
        if (cur.port, str(cur.proxy_mode), str(cur.role)) != (des.port, str(des.proxy_mode), str(des.role)):
            actions.append(("reboot", {}))
            return actions

    # Check for port conflicts: new node's port collides with existing
    current_ports = {current_nodes_by_name[n].port for n in common_nodes}
    for name in new_nodes:
        if desired_nodes_by_name[name].port in current_ports:
            actions.append(("reboot", {}))
            return actions

    # Incremental node changes
    for name in removed_nodes:
        actions.append(("remove_node", {"node_name": name}))

    for name in new_nodes:
        actions.append(("add_node", {"node": desired_nodes_by_name[name]}))

    # Edge changes
    added_edges = desired_edges - current_edges
    removed_edge_set = current_edges - desired_edges
    for src, tgt in removed_edge_set:
        actions.append(("remove_edge", {"source": src, "target": tgt}))
    for src, tgt in added_edges:
        # Find the edge spec with policy
        edge_spec = None
        for e in desired.edges:
            if e.source == src and e.target == tgt:
                edge_spec = e
                break
        actions.append(("add_edge", {"edge": edge_spec, "source": src, "target": tgt}))

    # Same topology -- check routing changes
    for node_name, desired_routing in config.routing.items():
        adapter_state = current_state.adapters.get(node_name)
        if adapter_state is None:
            continue
        current_routing = adapter_state.routing_config
        desired_dump = desired_routing.model_dump()
        if current_routing != desired_dump:
            actions.append(("update_routing", {
                "node_name": node_name,
                "routing_config": desired_routing,
            }))

    # Check for routing that should be cleared
    current_routed = {
        name for name, a in current_state.adapters.items()
        if a.routing_config is not None
    }
    desired_routed = set(config.routing.keys())
    for node_name in current_routed - desired_routed:
        actions.append(("clear_routing", {"node_name": node_name}))

    return actions
