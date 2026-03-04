"""Tests for the canary controller."""

from __future__ import annotations

import pytest

from baton.adapter import Adapter, AdapterMetrics, BackendTarget
from baton.canary import CanaryController
from baton.routing import canary as canary_routing
from baton.schemas import NodeSpec, RoutingConfig, RoutingStrategy, RoutingTarget


class FakeLifecycle:
    """Fake lifecycle for testing canary controller."""

    def __init__(self):
        self.routing_calls: list[tuple[str, RoutingConfig]] = []

    def set_routing(self, node_name: str, config: RoutingConfig) -> None:
        self.routing_calls.append((node_name, config))


def _make_adapter_with_canary(canary_pct: int = 10) -> tuple[Adapter, FakeLifecycle]:
    """Create adapter with canary routing at given percentage."""
    node = NodeSpec(name="api", port=19500)
    adapter = Adapter(node, record_signals=False)

    config = canary_routing("127.0.0.1", 39500, 39501, canary_pct=canary_pct)
    adapter.set_routing(config)

    lifecycle = FakeLifecycle()
    return adapter, lifecycle


def _inject_canary_metrics(
    adapter: Adapter,
    requests: int = 30,
    errors: int = 0,
    latency_ms: float = 100.0,
) -> None:
    """Inject fake per-target metrics for canary."""
    m = AdapterMetrics()
    m.requests_total = requests
    m.status_5xx = errors
    m.status_2xx = requests - errors
    for _ in range(requests):
        m.record_latency(latency_ms)
    adapter._target_metrics["canary"] = m


def _inject_stable_metrics(adapter: Adapter, requests: int = 100) -> None:
    """Inject fake per-target metrics for stable."""
    m = AdapterMetrics()
    m.requests_total = requests
    m.status_2xx = requests
    for _ in range(requests):
        m.record_latency(50.0)
    adapter._target_metrics["stable"] = m


class TestCanaryController:
    def test_promote_on_healthy_canary(self):
        """Healthy canary should promote to next step."""
        adapter, lifecycle = _make_adapter_with_canary(10)
        _inject_canary_metrics(adapter, requests=30, errors=0, latency_ms=100.0)
        _inject_stable_metrics(adapter)

        controller = CanaryController(
            adapter, "api", lifecycle,
            promote_steps=[10, 25, 50, 100],
            min_requests=20,
        )
        controller._evaluate()

        # Should have promoted to 25%
        assert len(lifecycle.routing_calls) == 1
        _, config = lifecycle.routing_calls[0]
        canary_t = next(t for t in config.targets if t.name == "canary")
        assert canary_t.weight == 25

    def test_rollback_on_high_error_rate(self):
        """High error rate should trigger rollback."""
        adapter, lifecycle = _make_adapter_with_canary(10)
        _inject_canary_metrics(adapter, requests=30, errors=5, latency_ms=100.0)
        _inject_stable_metrics(adapter)

        controller = CanaryController(
            adapter, "api", lifecycle,
            error_threshold=5.0,
            min_requests=20,
        )
        controller._evaluate()

        assert controller.outcome == "rolled_back"
        assert len(lifecycle.routing_calls) == 1
        _, config = lifecycle.routing_calls[0]
        stable_t = next(t for t in config.targets if t.name == "stable")
        assert stable_t.weight == 100

    def test_rollback_on_high_latency(self):
        """High p99 latency should trigger rollback."""
        adapter, lifecycle = _make_adapter_with_canary(10)
        _inject_canary_metrics(adapter, requests=30, errors=0, latency_ms=600.0)
        _inject_stable_metrics(adapter)

        controller = CanaryController(
            adapter, "api", lifecycle,
            latency_threshold=500.0,
            min_requests=20,
        )
        controller._evaluate()

        assert controller.outcome == "rolled_back"
        assert not controller.is_running

    def test_skip_when_insufficient_requests(self):
        """Should skip evaluation when canary has too few requests."""
        adapter, lifecycle = _make_adapter_with_canary(10)
        _inject_canary_metrics(adapter, requests=5, errors=0, latency_ms=100.0)
        _inject_stable_metrics(adapter)

        controller = CanaryController(
            adapter, "api", lifecycle,
            min_requests=20,
        )
        controller._evaluate()

        # No promotion or rollback
        assert len(lifecycle.routing_calls) == 0
        assert controller.outcome == ""

    def test_skip_when_no_canary_metrics(self):
        """Should skip evaluation when no canary metrics exist."""
        adapter, lifecycle = _make_adapter_with_canary(10)
        # Don't inject any canary metrics

        controller = CanaryController(
            adapter, "api", lifecycle,
            min_requests=20,
        )
        controller._evaluate()

        assert len(lifecycle.routing_calls) == 0

    def test_full_promotion_completes(self):
        """Promoting through all steps should complete."""
        adapter, lifecycle = _make_adapter_with_canary(50)
        _inject_canary_metrics(adapter, requests=30, errors=0, latency_ms=100.0)
        _inject_stable_metrics(adapter)

        controller = CanaryController(
            adapter, "api", lifecycle,
            promote_steps=[10, 25, 50, 100],
            min_requests=20,
        )
        controller._evaluate()

        # Should promote to 100% and complete
        assert controller.outcome == "promoted"
        assert not controller.is_running
        assert len(lifecycle.routing_calls) == 1
        _, config = lifecycle.routing_calls[0]
        canary_t = next(t for t in config.targets if t.name == "canary")
        assert canary_t.weight == 100

    def test_promotion_already_at_max(self):
        """At 100% should mark as promoted and stop."""
        adapter, lifecycle = _make_adapter_with_canary(10)
        # Override routing to already be at 100%
        config = RoutingConfig(
            strategy=RoutingStrategy.CANARY,
            targets=[
                RoutingTarget(name="stable", host="127.0.0.1", port=39500, weight=0),
                RoutingTarget(name="canary", host="127.0.0.1", port=39501, weight=100),
            ],
        )
        adapter.set_routing(config)
        _inject_canary_metrics(adapter, requests=30, errors=0, latency_ms=100.0)

        controller = CanaryController(
            adapter, "api", lifecycle,
            promote_steps=[10, 25, 50, 100],
            min_requests=20,
        )
        controller._evaluate()

        assert controller.outcome == "promoted"
        assert not controller.is_running

    def test_custom_promote_steps(self):
        """Custom promote steps should be respected."""
        adapter, lifecycle = _make_adapter_with_canary(5)
        _inject_canary_metrics(adapter, requests=30, errors=0, latency_ms=100.0)
        _inject_stable_metrics(adapter)

        controller = CanaryController(
            adapter, "api", lifecycle,
            promote_steps=[5, 20, 50, 100],
            min_requests=20,
        )
        controller._evaluate()

        assert len(lifecycle.routing_calls) == 1
        _, config = lifecycle.routing_calls[0]
        canary_t = next(t for t in config.targets if t.name == "canary")
        assert canary_t.weight == 20

    def test_error_threshold_boundary(self):
        """Error rate exactly at threshold should not trigger rollback."""
        adapter, lifecycle = _make_adapter_with_canary(10)
        # 5% error rate with threshold of 5.0 -- at boundary, not over
        _inject_canary_metrics(adapter, requests=100, errors=5, latency_ms=100.0)
        _inject_stable_metrics(adapter)

        controller = CanaryController(
            adapter, "api", lifecycle,
            error_threshold=5.0,
            min_requests=20,
        )
        controller._evaluate()

        # Should NOT have rolled back (5.0 is not > 5.0)
        assert controller.outcome != "rolled_back"

    @pytest.mark.asyncio
    async def test_run_loop_stops_on_promotion(self):
        """run() should exit after promotion completes."""
        adapter, lifecycle = _make_adapter_with_canary(50)
        _inject_canary_metrics(adapter, requests=30, errors=0, latency_ms=100.0)
        _inject_stable_metrics(adapter)

        controller = CanaryController(
            adapter, "api", lifecycle,
            promote_steps=[10, 25, 50, 100],
            eval_interval=0.05,
            min_requests=20,
        )
        await controller.run()

        assert controller.outcome == "promoted"

    @pytest.mark.asyncio
    async def test_run_loop_stops_on_rollback(self):
        """run() should exit after rollback."""
        adapter, lifecycle = _make_adapter_with_canary(10)
        _inject_canary_metrics(adapter, requests=30, errors=10, latency_ms=100.0)
        _inject_stable_metrics(adapter)

        controller = CanaryController(
            adapter, "api", lifecycle,
            error_threshold=5.0,
            eval_interval=0.05,
            min_requests=20,
        )
        await controller.run()

        assert controller.outcome == "rolled_back"


class TestPerTargetMetrics:
    def test_target_metrics_empty_by_default(self):
        node = NodeSpec(name="test", port=19600)
        adapter = Adapter(node, record_signals=False)
        assert adapter.target_metrics == {}

    def test_target_metrics_reset_on_set_routing(self):
        node = NodeSpec(name="test", port=19601)
        adapter = Adapter(node, record_signals=False)
        adapter._target_metrics["canary"] = AdapterMetrics()

        config = canary_routing("127.0.0.1", 39601, 39602, canary_pct=10)
        adapter.set_routing(config)

        assert adapter.target_metrics == {}

    def test_select_backend_named_no_routing(self):
        node = NodeSpec(name="test", port=19602)
        adapter = Adapter(node, record_signals=False)
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=39602))

        target, name = adapter._select_backend_named()
        assert target is not None
        assert target.port == 39602
        assert name is None

    def test_select_backend_named_with_canary(self):
        node = NodeSpec(name="test", port=19603)
        adapter = Adapter(node, record_signals=False)

        config = RoutingConfig(
            strategy=RoutingStrategy.CANARY,
            targets=[
                RoutingTarget(name="stable", host="127.0.0.1", port=39603, weight=0),
                RoutingTarget(name="canary", host="127.0.0.1", port=39604, weight=100),
            ],
        )
        adapter.set_routing(config)

        target, name = adapter._select_backend_named()
        assert target is not None
        assert name == "canary"
        assert target.port == 39604
