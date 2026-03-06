"""Custodian -- monitoring agent for circuit health and self-healing.

Polls adapter health endpoints, detects faults, and runs repair actions.
All repairs are atomic: new thing running before old removed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Protocol

import math

from baton.adapter import Adapter
from baton.schemas import (
    AdapterState,
    CircuitState,
    CustodianAction,
    CustodianEvent,
    HealthVerdict,
    NodeStatus,
    TelemetryClassRule,
)

logger = logging.getLogger(__name__)

HEALTH_POLL_INTERVAL = 5.0
FAILURE_THRESHOLD = 3


class LifecycleActions(Protocol):
    """Protocol for lifecycle actions the custodian can invoke."""

    async def restart_service(self, node_name: str) -> None: ...
    async def slot_mock(self, node_name: str) -> None: ...


class AnomalyDetector:
    """Z-score anomaly detection on latency and error rate."""

    def __init__(self, window_size: int = 100, z_threshold: float = 2.5):
        self._window_size = window_size
        self._z_threshold = z_threshold

    def check(
        self, adapter: Adapter, slo_rules: list[TelemetryClassRule] | None = None,
    ) -> list[str]:
        """Return list of anomaly descriptions, empty if healthy.

        Two detection modes:
        1. Statistical: z-score on latency buffer against rolling mean
        2. SLO-based: if slo_p95_ms is set, compare p95 against budget
        """
        anomalies: list[str] = []
        metrics = adapter.metrics
        buf = metrics._latency_buffer

        # Statistical z-score on latest latency
        if len(buf) >= 10:
            window = buf[-self._window_size:]
            mean = sum(window) / len(window)
            variance = sum((x - mean) ** 2 for x in window) / len(window)
            std = math.sqrt(variance) if variance > 0 else 0
            if std > 0 and buf:
                latest = buf[-1]
                z = (latest - mean) / std
                if z > self._z_threshold:
                    anomalies.append(
                        f"Latency z-score {z:.1f} exceeds threshold "
                        f"{self._z_threshold} (latest={latest:.0f}ms, mean={mean:.0f}ms)"
                    )

        # SLO-based p95 check
        if slo_rules:
            p95 = metrics.p95()
            for rule in slo_rules:
                if rule.slo_p95_ms > 0 and p95 > rule.slo_p95_ms:
                    anomalies.append(
                        f"SLO violation: p95={p95:.0f}ms exceeds "
                        f"budget {rule.slo_p95_ms}ms for '{rule.telemetry_class}'"
                    )

        # Error rate check (> 50% errors in recent requests)
        total = metrics.requests_total
        failed = metrics.requests_failed
        if total >= 10:
            error_rate = failed / total
            if error_rate > 0.5:
                anomalies.append(
                    f"High error rate: {error_rate:.0%} ({failed}/{total})"
                )

        return anomalies


class RepairPlaybook:
    """Determines repair action based on fault type and history.

    Research (Paper 23): Mode boundary (detection) and domain prime (recovery)
    are orthogonal decisions (rho = 0.858). This playbook implements the
    two-phase pattern: classify the fault mode first, then select the
    recovery action independently.

    Research (Paper 22): Explicit/complex routing rules ("director" pattern)
    perform worse than simple decisions. The playbook deliberately keeps
    decision logic minimal.
    """

    def classify(
        self, adapter_state: AdapterState, anomalies: list[str] | None = None,
    ) -> str:
        """Phase 1: Classify the fault mode (Paper 23: mode boundary).

        Returns a mode string: "healthy", "degraded", "unhealthy", "mock_failed".
        This is independent of what recovery action to take.
        """
        if anomalies and adapter_state.last_health_verdict != HealthVerdict.UNHEALTHY:
            return "degraded"
        if adapter_state.service.is_mock:
            return "mock_failed"
        if adapter_state.consecutive_failures >= FAILURE_THRESHOLD * 2:
            return "unhealthy"
        return "unhealthy"

    def select_action(self, mode: str) -> CustodianAction:
        """Phase 2: Select recovery action given fault mode (Paper 23: domain prime).

        Deliberately simple (Paper 22: complex rules hurt).
        """
        if mode == "degraded":
            return CustodianAction.REROUTE
        if mode == "mock_failed":
            return CustodianAction.ESCALATE
        if mode == "unhealthy":
            return CustodianAction.RESTART_SERVICE
        return CustodianAction.RESTART_SERVICE

    def decide(
        self, adapter_state: AdapterState, anomalies: list[str] | None = None,
    ) -> CustodianAction:
        """Combined decide (backward-compatible).

        Internally uses two-phase classify -> select_action.
        """
        mode = self.classify(adapter_state, anomalies)

        # Override: many failures on live service -> replace
        if (
            mode == "unhealthy"
            and not adapter_state.service.is_mock
            and adapter_state.consecutive_failures >= FAILURE_THRESHOLD * 2
        ):
            return CustodianAction.REPLACE_SERVICE

        return self.select_action(mode)


class Custodian:
    """Long-running monitoring loop.

    Usage:
        custodian = Custodian(adapters, state, lifecycle)
        task = asyncio.create_task(custodian.run())
        ...
        custodian.stop()
        await task
    """

    def __init__(
        self,
        adapters: dict[str, Adapter],
        state: CircuitState,
        lifecycle: LifecycleActions | None = None,
        playbook: RepairPlaybook | None = None,
        poll_interval: float = HEALTH_POLL_INTERVAL,
        anomaly_detector: AnomalyDetector | None = None,
        slo_rules: dict[str, list[TelemetryClassRule]] | None = None,
    ):
        self._adapters = adapters
        self._state = state
        self._lifecycle = lifecycle
        self._playbook = playbook or RepairPlaybook()
        self._poll_interval = poll_interval
        self._running = False
        self._events: list[CustodianEvent] = []
        self._anomaly_detector = anomaly_detector
        self._slo_rules = slo_rules or {}

    @property
    def events(self) -> list[CustodianEvent]:
        return list(self._events)

    @property
    def is_running(self) -> bool:
        return self._running

    async def run(self) -> None:
        """Main monitoring loop."""
        self._running = True
        logger.info("Custodian started")
        while self._running:
            await self._check_all()
            await asyncio.sleep(self._poll_interval)
        logger.info("Custodian stopped")

    def stop(self) -> None:
        self._running = False

    async def check_once(self) -> list[CustodianEvent]:
        """Run one check cycle and return any events generated."""
        before = len(self._events)
        await self._check_all()
        return self._events[before:]

    async def _check_all(self) -> None:
        for name, adapter in self._adapters.items():
            adapter_state = self._state.adapters.get(name)
            if not adapter_state:
                continue

            health = await adapter.health_check()
            adapter_state.last_health_check = health.timestamp
            adapter_state.last_health_verdict = health.verdict

            if health.verdict == HealthVerdict.UNHEALTHY:
                adapter_state.consecutive_failures += 1
                if adapter_state.consecutive_failures >= FAILURE_THRESHOLD:
                    await self._repair(name, adapter_state)
            elif health.verdict == HealthVerdict.HEALTHY:
                if adapter_state.consecutive_failures > 0:
                    adapter_state.consecutive_failures = 0
                if adapter_state.status == NodeStatus.FAULTED:
                    adapter_state.status = NodeStatus.ACTIVE

                # Run anomaly detection on healthy nodes
                if self._anomaly_detector:
                    node_slo = self._slo_rules.get(name)
                    anomalies = self._anomaly_detector.check(adapter, node_slo)
                    if anomalies:
                        event = CustodianEvent(
                            node_name=name,
                            action=CustodianAction.REROUTE,
                            reason=f"Anomaly on healthy node: {'; '.join(anomalies)}",
                            timestamp=datetime.now(timezone.utc).isoformat(),
                        )
                        self._events.append(event)
                        logger.info(f"Custodian [{name}]: anomaly detected - {anomalies}")

    async def _repair(self, node_name: str, adapter_state: AdapterState) -> None:
        action = self._playbook.decide(adapter_state)
        event = CustodianEvent(
            node_name=node_name,
            action=action,
            reason=f"Consecutive failures: {adapter_state.consecutive_failures}",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        if self._lifecycle is None:
            event.detail = "No lifecycle manager available"
            self._events.append(event)
            adapter_state.status = NodeStatus.FAULTED
            return

        try:
            if action == CustodianAction.RESTART_SERVICE:
                await self._lifecycle.restart_service(node_name)
                event.success = True
                event.detail = "Service restarted"
                adapter_state.consecutive_failures = 0
            elif action == CustodianAction.REPLACE_SERVICE:
                await self._lifecycle.slot_mock(node_name)
                event.success = True
                event.detail = "Replaced with mock"
                adapter_state.consecutive_failures = 0
            elif action == CustodianAction.ESCALATE:
                event.detail = "Manual intervention required"
        except Exception as e:
            event.detail = f"Repair failed: {e}"

        self._events.append(event)
        if not event.success:
            adapter_state.status = NodeStatus.FAULTED

        logger.info(
            f"Custodian [{node_name}]: {action} - "
            f"{'success' if event.success else 'failed'}: {event.detail}"
        )
