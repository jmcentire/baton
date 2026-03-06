"""Canary controller -- automated promotion and rollback.

Follows the custodian pattern: async loop, periodic evaluation, stop/start.
Compares canary vs stable per-target metrics and promotes or rolls back.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from baton.adapter import Adapter, AdapterMetrics
from baton.schemas import RoutingConfig, RoutingStrategy, RoutingTarget

logger = logging.getLogger(__name__)

DEFAULT_PROMOTE_STEPS = [10, 25, 50, 100]


def centroid_select(candidates: dict[str, tuple[float, float, float]]) -> str | None:
    """Select the candidate closest to the ensemble centroid.

    Paper 19 (Ensemble Gravity): Centroid-based selection closes 48.9% of the
    coordination gap -- 5.4x better than state injection. For canary evaluation,
    this selects the variant whose metrics are closest to the ensemble average.

    Args:
        candidates: dict of name -> (error_rate, p99_latency_ms, throughput)

    Returns:
        Name of the candidate closest to centroid, or None if empty.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return next(iter(candidates))

    # Compute centroid
    n = len(candidates)
    centroid = [0.0, 0.0, 0.0]
    for err, lat, thr in candidates.values():
        centroid[0] += err / n
        centroid[1] += lat / n
        centroid[2] += thr / n

    # Find closest to centroid (Euclidean distance, normalized)
    # Normalize each dimension by range to prevent latency dominating
    ranges = [0.0, 0.0, 0.0]
    vals = list(candidates.values())
    for dim in range(3):
        dim_vals = [v[dim] for v in vals]
        ranges[dim] = max(dim_vals) - min(dim_vals) if len(dim_vals) > 1 else 1.0
        if ranges[dim] == 0:
            ranges[dim] = 1.0

    best_name = None
    best_dist = float("inf")
    for name, (err, lat, thr) in candidates.items():
        dist = sum(
            ((v - c) / r) ** 2
            for v, c, r in zip([err, lat, thr], centroid, ranges)
        )
        if dist < best_dist:
            best_dist = dist
            best_name = name

    return best_name


class CanaryLifecycle(Protocol):
    """Protocol for lifecycle actions the canary controller can invoke."""

    def set_routing(self, node_name: str, config: RoutingConfig) -> None: ...


class CanaryController:
    """Automated canary promotion/rollback controller.

    Usage:
        controller = CanaryController(adapter, "api", lifecycle)
        task = asyncio.create_task(controller.run())
        ...
        controller.stop()
        await task
    """

    def __init__(
        self,
        adapter: Adapter,
        node_name: str,
        lifecycle: CanaryLifecycle,
        *,
        error_threshold: float = 5.0,
        latency_threshold: float = 500.0,
        promote_steps: list[int] | None = None,
        eval_interval: float = 30.0,
        min_requests: int = 20,
    ):
        self._adapter = adapter
        self._node_name = node_name
        self._lifecycle = lifecycle
        self._error_threshold = error_threshold
        self._latency_threshold = latency_threshold
        self._promote_steps = list(promote_steps or DEFAULT_PROMOTE_STEPS)
        self._eval_interval = eval_interval
        self._min_requests = min_requests
        self._running = False
        self._outcome: str = ""  # "promoted", "rolled_back", or ""

    @property
    def outcome(self) -> str:
        return self._outcome

    @property
    def is_running(self) -> bool:
        return self._running

    async def run(self) -> None:
        """Main evaluation loop."""
        self._running = True
        logger.info(f"Canary controller started for [{self._node_name}]")
        while self._running:
            await asyncio.sleep(self._eval_interval)
            if not self._running:
                break
            self._evaluate()
            if not self._running:
                break
        logger.info(
            f"Canary controller stopped for [{self._node_name}] "
            f"(outcome: {self._outcome or 'none'})"
        )

    def stop(self) -> None:
        self._running = False

    def _evaluate(self) -> None:
        """Compare canary vs stable metrics. Promote or rollback."""
        target_metrics = self._adapter.target_metrics
        canary_m = target_metrics.get("canary")
        stable_m = target_metrics.get("stable")

        if canary_m is None:
            logger.debug(f"[{self._node_name}] No canary metrics yet, skipping")
            return

        if canary_m.requests_total < self._min_requests:
            logger.debug(
                f"[{self._node_name}] Canary has {canary_m.requests_total} requests "
                f"(need {self._min_requests}), skipping"
            )
            return

        # Check error rate
        if canary_m.requests_total > 0:
            error_rate = canary_m.status_5xx / canary_m.requests_total * 100
            if error_rate > self._error_threshold:
                logger.warning(
                    f"[{self._node_name}] Canary error rate {error_rate:.1f}% "
                    f"> threshold {self._error_threshold}%, rolling back"
                )
                self._rollback()
                return

        # Check p99 latency
        p99 = canary_m.p99()
        if p99 > self._latency_threshold:
            logger.warning(
                f"[{self._node_name}] Canary p99 {p99:.0f}ms "
                f"> threshold {self._latency_threshold}ms, rolling back"
            )
            self._rollback()
            return

        # Looks healthy -- promote to next step
        self._promote()

    def _get_current_canary_weight(self) -> int:
        """Get current canary weight from the adapter's routing config."""
        routing = self._adapter.routing
        if routing is None:
            return 0
        for t in routing.targets:
            if t.name == "canary":
                return t.weight
        return 0

    def _promote(self) -> None:
        """Advance canary to the next weight step."""
        current = self._get_current_canary_weight()

        # Find next step > current weight
        next_weight = None
        for step in self._promote_steps:
            if step > current:
                next_weight = step
                break

        if next_weight is None:
            # Already at or past the highest step -- promotion complete
            logger.info(f"[{self._node_name}] Canary promotion complete (at {current}%)")
            self._outcome = "promoted"
            self._running = False
            return

        # Get current routing targets to preserve host/port info
        routing = self._adapter.routing
        if routing is None:
            return

        stable_target = None
        canary_target = None
        for t in routing.targets:
            if t.name == "stable":
                stable_target = t
            elif t.name == "canary":
                canary_target = t

        if stable_target is None or canary_target is None:
            logger.error(f"[{self._node_name}] Missing stable/canary targets in routing config")
            return

        config = RoutingConfig(
            strategy=RoutingStrategy.CANARY,
            targets=[
                RoutingTarget(
                    name="stable",
                    host=stable_target.host,
                    port=stable_target.port,
                    weight=100 - next_weight,
                ),
                RoutingTarget(
                    name="canary",
                    host=canary_target.host,
                    port=canary_target.port,
                    weight=next_weight,
                ),
            ],
        )
        self._lifecycle.set_routing(self._node_name, config)
        logger.info(f"[{self._node_name}] Canary promoted to {next_weight}%")

        if next_weight >= 100:
            self._outcome = "promoted"
            self._running = False

    def _rollback(self) -> None:
        """Revert to 100% stable traffic."""
        routing = self._adapter.routing
        if routing is None:
            self._outcome = "rolled_back"
            self._running = False
            return

        stable_target = None
        canary_target = None
        for t in routing.targets:
            if t.name == "stable":
                stable_target = t
            elif t.name == "canary":
                canary_target = t

        if stable_target is None:
            logger.error(f"[{self._node_name}] No stable target found for rollback")
            self._outcome = "rolled_back"
            self._running = False
            return

        # Set 100% stable, 0% canary
        targets = [
            RoutingTarget(
                name="stable",
                host=stable_target.host,
                port=stable_target.port,
                weight=100,
            ),
        ]
        if canary_target is not None:
            targets.append(
                RoutingTarget(
                    name="canary",
                    host=canary_target.host,
                    port=canary_target.port,
                    weight=0,
                ),
            )

        config = RoutingConfig(
            strategy=RoutingStrategy.CANARY,
            targets=targets,
        )
        self._lifecycle.set_routing(self._node_name, config)
        logger.info(f"[{self._node_name}] Canary rolled back to 100% stable")
        self._outcome = "rolled_back"
        self._running = False
