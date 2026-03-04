"""Tests for circuit lifecycle orchestration."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from unittest.mock import AsyncMock, MagicMock, patch

from baton.cli import main as cli_main
from baton.config import load_circuit
from baton.lifecycle import LifecycleManager, _resolve_node_policy
from baton.schemas import (
    CircuitConfig,
    CircuitSpec,
    CollapseLevel,
    DeployConfig,
    EdgePolicy,
    EdgeSpec,
    NodeSpec,
    NodeStatus,
    RoutingConfig,
    RoutingStrategy,
    RoutingTarget,
    SecurityConfig,
)


def _init_project(d: Path) -> None:
    """Set up a project directory with a 2-node circuit."""
    cli_main(["init", str(d)])
    cli_main(["node", "add", "api", "--port", "17001", "--dir", str(d)])
    cli_main(["node", "add", "service", "--port", "17002", "--dir", str(d)])
    cli_main(["edge", "add", "api", "service", "--dir", str(d)])


class TestLifecycleUpDown:
    async def test_up_creates_adapters(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        try:
            state = await mgr.up(mock=True)
            assert len(mgr.adapters) == 2
            assert state.collapse_level == CollapseLevel.FULL_MOCK
            assert "api" in state.adapters
            assert "service" in state.adapters
            assert state.adapters["api"].status == NodeStatus.LISTENING
        finally:
            await mgr.down()

    async def test_down_cleans_up(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        await mgr.up(mock=True)
        await mgr.down()
        assert len(mgr.adapters) == 0

    async def test_adapters_respond_503_when_no_backend(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        try:
            await mgr.up(mock=True)
            reader, writer = await asyncio.open_connection("127.0.0.1", 17001)
            writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            assert b"503" in response
            writer.close()
        finally:
            await mgr.down()


class TestLifecycleSlot:
    async def test_slot_service(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        try:
            await mgr.up(mock=True)
            # Start a simple HTTP server as the service
            await mgr.slot(
                "api",
                "python3 -m http.server $BATON_SERVICE_PORT",
            )
            state = mgr.state
            assert state.adapters["api"].status == NodeStatus.ACTIVE
            assert state.adapters["api"].service.is_mock is False
            assert "api" in state.live_nodes
            assert state.collapse_level == CollapseLevel.PARTIAL
        finally:
            await mgr.down()

    async def test_slot_missing_node(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        try:
            await mgr.up(mock=True)
            with pytest.raises(ValueError, match="not found"):
                await mgr.slot("missing", "echo hi")
        finally:
            await mgr.down()


class TestLifecycleSlotMock:
    async def test_slot_mock(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        try:
            await mgr.up(mock=True)
            await mgr.slot(
                "api",
                "python3 -m http.server $BATON_SERVICE_PORT",
            )
            assert mgr.state.collapse_level == CollapseLevel.PARTIAL

            await mgr.slot_mock("api")
            assert mgr.state.adapters["api"].status == NodeStatus.LISTENING
            assert "api" not in mgr.state.live_nodes
            assert mgr.state.collapse_level == CollapseLevel.FULL_MOCK
        finally:
            await mgr.down()


class TestLifecycleSlotAB:
    async def test_slot_ab_creates_routing(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        try:
            await mgr.up(mock=True)
            await mgr.slot_ab(
                "api",
                "python3 -m http.server $BATON_SERVICE_PORT",
                "python3 -m http.server $BATON_SERVICE_PORT",
                split=(80, 20),
            )
            adapter = mgr.adapters["api"]
            assert adapter.routing is not None
            assert adapter.routing.strategy == RoutingStrategy.WEIGHTED
            assert len(adapter.routing.targets) == 2
            assert mgr.state.adapters["api"].status == NodeStatus.ACTIVE
            assert mgr.state.adapters["api"].routing_config is not None
        finally:
            await mgr.down()


class TestLifecycleRoutingLock:
    async def test_lock_prevents_slot(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        try:
            await mgr.up(mock=True)
            await mgr.slot_ab(
                "api",
                "python3 -m http.server $BATON_SERVICE_PORT",
                "python3 -m http.server $BATON_SERVICE_PORT",
            )
            mgr.lock_routing("api")
            with pytest.raises(RuntimeError, match="locked"):
                await mgr.slot("api", "python3 -m http.server $BATON_SERVICE_PORT")
        finally:
            await mgr.down()

    async def test_unlock_allows_slot(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        try:
            await mgr.up(mock=True)
            await mgr.slot_ab(
                "api",
                "python3 -m http.server $BATON_SERVICE_PORT",
                "python3 -m http.server $BATON_SERVICE_PORT",
            )
            mgr.lock_routing("api")
            mgr.unlock_routing("api")
            # Should not raise after unlock -- clear routing first
            adapter = mgr.adapters["api"]
            adapter.clear_routing()
            await mgr.slot("api", "python3 -m http.server $BATON_SERVICE_PORT")
            assert mgr.state.adapters["api"].status == NodeStatus.ACTIVE
        finally:
            await mgr.down()

    async def test_lock_prevents_swap(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        try:
            await mgr.up(mock=True)
            await mgr.slot("api", "python3 -m http.server $BATON_SERVICE_PORT")
            config = RoutingConfig(
                strategy=RoutingStrategy.WEIGHTED,
                targets=[
                    RoutingTarget(name="a", port=37001, weight=80),
                    RoutingTarget(name="b", port=37002, weight=20),
                ],
                locked=True,
            )
            mgr.adapters["api"].set_routing(config)
            with pytest.raises(RuntimeError, match="locked"):
                await mgr.swap("api", "python3 -m http.server $BATON_SERVICE_PORT")
        finally:
            await mgr.down()


class TestCollapseLevel:
    async def test_all_live(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        try:
            await mgr.up(mock=True)
            await mgr.slot("api", "python3 -m http.server $BATON_SERVICE_PORT")
            await mgr.slot("service", "python3 -m http.server $BATON_SERVICE_PORT")
            assert mgr.state.collapse_level == CollapseLevel.FULL_LIVE
        finally:
            await mgr.down()


class TestEgressCollapse:
    def test_egress_always_mocked_in_collapse(self):
        from baton.collapse import compute_mock_backends
        from baton.schemas import CircuitSpec, NodeSpec

        circuit = CircuitSpec(
            name="test",
            nodes=[
                NodeSpec(name="api", port=16010),
                NodeSpec(name="stripe", port=16011, role="egress"),
            ],
            edges=[EdgeSpec(source="api", target="stripe")],
        )
        # Even if stripe is in live_nodes, it should still be mocked
        backends = compute_mock_backends(circuit, live_nodes={"api", "stripe"})
        assert "stripe" in backends  # egress always mocked
        assert "api" not in backends  # api is live

    async def test_egress_slot_rejected(self, project_dir: Path):
        d = project_dir / "p"
        cli_main(["init", str(d)])
        cli_main(["node", "add", "api", "--port", "16012", "--dir", str(d)])
        cli_main(["node", "add", "stripe", "--port", "16013", "--role", "egress", "--dir", str(d)])
        cli_main(["edge", "add", "api", "stripe", "--dir", str(d)])

        mgr = LifecycleManager(d)
        try:
            await mgr.up(mock=True)
            with pytest.raises(ValueError, match="Cannot slot.*egress"):
                await mgr.slot("stripe", "python3 -m http.server $BATON_SERVICE_PORT")
        finally:
            await mgr.down()


class TestIngressRecording:
    async def test_ingress_adapter_records_signals(self, project_dir: Path):
        d = project_dir / "p"
        cli_main(["init", str(d)])
        cli_main(["node", "add", "gateway", "--port", "16014", "--role", "ingress", "--dir", str(d)])

        mgr = LifecycleManager(d)
        try:
            await mgr.up(mock=True)
            adapter = mgr.adapters["gateway"]
            assert adapter._record_signals is True
        finally:
            await mgr.down()


# -- Apply convergence --


class TestApply:
    async def test_apply_boots_when_no_state(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        config = CircuitConfig(
            name="default",
            nodes=[
                NodeSpec(name="api", port=17001),
                NodeSpec(name="service", port=17002),
            ],
            edges=[EdgeSpec(source="api", target="service")],
        )
        try:
            state = await mgr.apply(config)
            assert len(mgr.adapters) == 2
            assert "api" in state.adapters
            assert "service" in state.adapters
            assert state.adapters["api"].status == NodeStatus.LISTENING
        finally:
            await mgr.down()

    async def test_apply_idempotent(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        config = CircuitConfig(
            name="default",
            nodes=[
                NodeSpec(name="api", port=17001),
                NodeSpec(name="service", port=17002),
            ],
            edges=[EdgeSpec(source="api", target="service")],
        )
        try:
            state1 = await mgr.apply(config)
            # Apply same config again -- should be no-op
            state2 = await mgr.apply(config)
            assert len(mgr.adapters) == 2
            assert state2.adapters["api"].status == NodeStatus.LISTENING
        finally:
            await mgr.down()

    async def test_apply_updates_routing(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        config = CircuitConfig(
            name="default",
            nodes=[
                NodeSpec(name="api", port=17001),
                NodeSpec(name="service", port=17002),
            ],
            edges=[EdgeSpec(source="api", target="service")],
        )
        try:
            await mgr.apply(config)
            # Now apply with routing
            config2 = CircuitConfig(
                name="default",
                nodes=[
                    NodeSpec(name="api", port=17001),
                    NodeSpec(name="service", port=17002),
                ],
                edges=[EdgeSpec(source="api", target="service")],
                routing={"api": RoutingConfig(
                    strategy=RoutingStrategy.WEIGHTED,
                    targets=[
                        RoutingTarget(name="a", port=37001, weight=80),
                        RoutingTarget(name="b", port=37002, weight=20),
                    ],
                )},
            )
            state = await mgr.apply(config2)
            assert state.adapters["api"].routing_config is not None
            assert state.adapters["api"].routing_config["strategy"] == "weighted"
        finally:
            await mgr.down()


# -- Edge Policy --


class TestApplyEdgePolicy:
    async def test_apply_sets_policy(self, project_dir: Path):
        """Config with edge policy -> adapter has policy set."""
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        config = CircuitConfig(
            name="default",
            nodes=[
                NodeSpec(name="api", port=17001),
                NodeSpec(name="service", port=17002),
            ],
            edges=[EdgeSpec(
                source="api", target="service",
                policy=EdgePolicy(timeout_ms=5000, retries=2),
            )],
        )
        try:
            await mgr.apply(config)
            adapter = mgr.adapters["service"]
            assert adapter.policy is not None
            assert adapter.policy.timeout_ms == 5000
            assert adapter.policy.retries == 2
            # api has no incoming edges with policy
            assert mgr.adapters["api"].policy is None
        finally:
            await mgr.down()

    async def test_apply_no_policy(self, project_dir: Path):
        """Config without edge policy -> adapter.policy is None."""
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        config = CircuitConfig(
            name="default",
            nodes=[
                NodeSpec(name="api", port=17001),
                NodeSpec(name="service", port=17002),
            ],
            edges=[EdgeSpec(source="api", target="service")],
        )
        try:
            await mgr.apply(config)
            assert mgr.adapters["service"].policy is None
            assert mgr.adapters["api"].policy is None
        finally:
            await mgr.down()

    def test_resolve_most_restrictive(self):
        """Two edges targeting same node -> merged policy."""
        circuit = CircuitSpec(
            name="test",
            nodes=[
                NodeSpec(name="a", port=17010),
                NodeSpec(name="b", port=17011),
                NodeSpec(name="c", port=17012),
            ],
            edges=[
                EdgeSpec(source="a", target="c", policy=EdgePolicy(timeout_ms=5000, retries=1, circuit_breaker_threshold=5)),
                EdgeSpec(source="b", target="c", policy=EdgePolicy(timeout_ms=3000, retries=3, circuit_breaker_threshold=3)),
            ],
        )
        merged = _resolve_node_policy(circuit, "c")
        assert merged is not None
        assert merged.timeout_ms == 3000      # min
        assert merged.retries == 3             # max
        assert merged.circuit_breaker_threshold == 3  # min nonzero


# -- Security --


class TestApplySecurity:
    async def test_apply_tls_off(self, project_dir: Path):
        """No TLS -> adapters start without SSL."""
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        config = CircuitConfig(
            name="default",
            nodes=[
                NodeSpec(name="api", port=17001),
                NodeSpec(name="service", port=17002),
            ],
            edges=[EdgeSpec(source="api", target="service")],
        )
        try:
            await mgr.apply(config)
            assert mgr.adapters["api"]._ssl_context is None
        finally:
            await mgr.down()

    async def test_apply_passes_security_to_control(self, project_dir: Path):
        """Security config reaches AdapterControlServer."""
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        security = SecurityConfig()
        config = CircuitConfig(
            name="default",
            nodes=[
                NodeSpec(name="api", port=17001),
                NodeSpec(name="service", port=17002),
            ],
            edges=[EdgeSpec(source="api", target="service")],
            security=security,
        )
        try:
            await mgr.apply(config)
            # Controls were created with security config
            ctrl = mgr._controls["api"]
            assert ctrl._security is not None
        finally:
            await mgr.down()


# -- Incremental Apply --


class TestIncrementalApply:
    async def test_add_node_no_reboot(self, project_dir: Path):
        """Boot 2 nodes, apply with 3 -> original 2 adapters still running, 3rd added."""
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        config2 = CircuitConfig(
            name="default",
            nodes=[
                NodeSpec(name="api", port=17001),
                NodeSpec(name="service", port=17002),
            ],
            edges=[EdgeSpec(source="api", target="service")],
        )
        try:
            await mgr.apply(config2)
            old_api_adapter = mgr.adapters["api"]

            config3 = CircuitConfig(
                name="default",
                nodes=[
                    NodeSpec(name="api", port=17001),
                    NodeSpec(name="service", port=17002),
                    NodeSpec(name="cache", port=17003),
                ],
                edges=[
                    EdgeSpec(source="api", target="service"),
                    EdgeSpec(source="api", target="cache"),
                ],
            )
            state = await mgr.apply(config3)
            # Original adapters still the same objects (not rebooted)
            assert mgr.adapters["api"] is old_api_adapter
            assert "cache" in mgr.adapters
            assert "cache" in state.adapters
            assert len(mgr.adapters) == 3
        finally:
            await mgr.down()

    async def test_remove_node_drains(self, project_dir: Path):
        """Boot 3 nodes, apply with 2 -> removed node's adapter stopped."""
        d = project_dir / "p"
        cli_main(["init", str(d)])
        cli_main(["node", "add", "api", "--port", "17001", "--dir", str(d)])
        cli_main(["node", "add", "service", "--port", "17002", "--dir", str(d)])
        cli_main(["node", "add", "cache", "--port", "17003", "--dir", str(d)])
        cli_main(["edge", "add", "api", "service", "--dir", str(d)])
        cli_main(["edge", "add", "api", "cache", "--dir", str(d)])

        mgr = LifecycleManager(d)
        config3 = CircuitConfig(
            name="default",
            nodes=[
                NodeSpec(name="api", port=17001),
                NodeSpec(name="service", port=17002),
                NodeSpec(name="cache", port=17003),
            ],
            edges=[
                EdgeSpec(source="api", target="service"),
                EdgeSpec(source="api", target="cache"),
            ],
        )
        try:
            await mgr.apply(config3)
            assert len(mgr.adapters) == 3

            config2 = CircuitConfig(
                name="default",
                nodes=[
                    NodeSpec(name="api", port=17001),
                    NodeSpec(name="service", port=17002),
                ],
                edges=[EdgeSpec(source="api", target="service")],
            )
            state = await mgr.apply(config2)
            assert "cache" not in mgr.adapters
            assert "cache" not in state.adapters
            assert len(mgr.adapters) == 2
        finally:
            await mgr.down()

    async def test_add_edge(self, project_dir: Path):
        """Apply with new edge -> circuit updated, no reboot."""
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        config1 = CircuitConfig(
            name="default",
            nodes=[
                NodeSpec(name="api", port=17001),
                NodeSpec(name="service", port=17002),
            ],
            edges=[],
        )
        try:
            await mgr.apply(config1)
            old_adapter = mgr.adapters["api"]

            config2 = CircuitConfig(
                name="default",
                nodes=[
                    NodeSpec(name="api", port=17001),
                    NodeSpec(name="service", port=17002),
                ],
                edges=[EdgeSpec(source="api", target="service")],
            )
            await mgr.apply(config2)
            # Same adapter, no reboot
            assert mgr.adapters["api"] is old_adapter
        finally:
            await mgr.down()

    async def test_remove_edge(self, project_dir: Path):
        """Apply without an edge -> circuit updated, no reboot."""
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        config1 = CircuitConfig(
            name="default",
            nodes=[
                NodeSpec(name="api", port=17001),
                NodeSpec(name="service", port=17002),
            ],
            edges=[EdgeSpec(source="api", target="service")],
        )
        try:
            await mgr.apply(config1)
            old_adapter = mgr.adapters["api"]

            config2 = CircuitConfig(
                name="default",
                nodes=[
                    NodeSpec(name="api", port=17001),
                    NodeSpec(name="service", port=17002),
                ],
                edges=[],
            )
            await mgr.apply(config2)
            assert mgr.adapters["api"] is old_adapter
        finally:
            await mgr.down()

    async def test_changed_port_reboots(self, project_dir: Path):
        """Change a node's port -> full reboot."""
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        config1 = CircuitConfig(
            name="default",
            nodes=[
                NodeSpec(name="api", port=17001),
                NodeSpec(name="service", port=17002),
            ],
            edges=[EdgeSpec(source="api", target="service")],
        )
        try:
            await mgr.apply(config1)
            old_adapter = mgr.adapters["api"]

            config2 = CircuitConfig(
                name="default",
                nodes=[
                    NodeSpec(name="api", port=17001),
                    NodeSpec(name="service", port=17005),  # changed port
                ],
                edges=[EdgeSpec(source="api", target="service")],
            )
            await mgr.apply(config2)
            # Rebooted -- adapter is a new object
            assert mgr.adapters["api"] is not old_adapter
        finally:
            await mgr.down()

    async def test_add_node_gets_policy(self, project_dir: Path):
        """New node with incoming edge policy -> adapter.policy set."""
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        config1 = CircuitConfig(
            name="default",
            nodes=[
                NodeSpec(name="api", port=17001),
                NodeSpec(name="service", port=17002),
            ],
            edges=[EdgeSpec(source="api", target="service")],
        )
        try:
            await mgr.apply(config1)

            config2 = CircuitConfig(
                name="default",
                nodes=[
                    NodeSpec(name="api", port=17001),
                    NodeSpec(name="service", port=17002),
                    NodeSpec(name="cache", port=17003),
                ],
                edges=[
                    EdgeSpec(source="api", target="service"),
                    EdgeSpec(source="api", target="cache",
                             policy=EdgePolicy(timeout_ms=1000)),
                ],
            )
            await mgr.apply(config2)
            assert mgr.adapters["cache"].policy is not None
            assert mgr.adapters["cache"].policy.timeout_ms == 1000
        finally:
            await mgr.down()

    async def test_remove_node_clears_state(self, project_dir: Path):
        """Removed node not in state.adapters."""
        d = project_dir / "p"
        cli_main(["init", str(d)])
        cli_main(["node", "add", "api", "--port", "17001", "--dir", str(d)])
        cli_main(["node", "add", "service", "--port", "17002", "--dir", str(d)])
        cli_main(["node", "add", "cache", "--port", "17003", "--dir", str(d)])
        cli_main(["edge", "add", "api", "service", "--dir", str(d)])

        mgr = LifecycleManager(d)
        config3 = CircuitConfig(
            name="default",
            nodes=[
                NodeSpec(name="api", port=17001),
                NodeSpec(name="service", port=17002),
                NodeSpec(name="cache", port=17003),
            ],
            edges=[EdgeSpec(source="api", target="service")],
        )
        try:
            await mgr.apply(config3)

            config2 = CircuitConfig(
                name="default",
                nodes=[
                    NodeSpec(name="api", port=17001),
                    NodeSpec(name="service", port=17002),
                ],
                edges=[EdgeSpec(source="api", target="service")],
            )
            state = await mgr.apply(config2)
            assert "cache" not in state.adapters
            assert "cache" not in mgr._controls
        finally:
            await mgr.down()


# -- Deploy Integration --


class TestApplyWithProvider:
    async def test_local_uses_lifecycle(self, project_dir: Path):
        """Local provider -> normal convergence."""
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        config = CircuitConfig(
            name="default",
            nodes=[
                NodeSpec(name="api", port=17001),
                NodeSpec(name="service", port=17002),
            ],
            edges=[EdgeSpec(source="api", target="service")],
            deploy=DeployConfig(provider="local"),
        )
        try:
            state = await mgr.apply(config)
            assert len(mgr.adapters) == 2
            assert "api" in state.adapters
        finally:
            await mgr.down()

    async def test_nonlocal_delegates(self, project_dir: Path):
        """Mock create_provider, verify deploy() called with correct args."""
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)

        mock_provider = MagicMock()
        from baton.schemas import CircuitState
        mock_state = CircuitState(circuit_name="default")
        mock_provider.deploy = AsyncMock(return_value=mock_state)

        config = CircuitConfig(
            name="default",
            nodes=[
                NodeSpec(name="api", port=17001),
                NodeSpec(name="service", port=17002),
            ],
            edges=[EdgeSpec(source="api", target="service")],
            deploy=DeployConfig(provider="gcp", region="us-central1", project="my-proj"),
        )
        with patch("baton.lifecycle.LifecycleManager._apply_via_provider") as mock_via:
            mock_via.return_value = mock_state
            state = await mgr.apply(config)
            mock_via.assert_called_once_with(config)
            assert state is mock_state
