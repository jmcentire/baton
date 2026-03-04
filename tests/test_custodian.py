"""Tests for the custodian monitoring agent."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from baton.adapter import Adapter, BackendTarget
from baton.custodian import AnomalyDetector, Custodian, RepairPlaybook
from baton.schemas import (
    AdapterState,
    CircuitState,
    CustodianAction,
    HealthVerdict,
    NodeSpec,
    NodeStatus,
    ServiceSlot,
    TelemetryClassRule,
)


class TestRepairPlaybook:
    def test_restart_for_live_service(self):
        playbook = RepairPlaybook()
        state = AdapterState(
            node_name="api",
            service=ServiceSlot(command="./run.sh", is_mock=False),
            consecutive_failures=3,
        )
        assert playbook.decide(state) == CustodianAction.RESTART_SERVICE

    def test_replace_after_many_failures(self):
        playbook = RepairPlaybook()
        state = AdapterState(
            node_name="api",
            service=ServiceSlot(command="./run.sh", is_mock=False),
            consecutive_failures=7,
        )
        assert playbook.decide(state) == CustodianAction.REPLACE_SERVICE

    def test_escalate_for_mock(self):
        playbook = RepairPlaybook()
        state = AdapterState(
            node_name="api",
            service=ServiceSlot(is_mock=True),
            consecutive_failures=5,
        )
        assert playbook.decide(state) == CustodianAction.ESCALATE


class TestCustodian:
    async def test_detects_healthy(self):
        # Start a TCP server as a healthy backend
        backend = await asyncio.start_server(
            lambda r, w: w.close(), "127.0.0.1", 14001
        )
        node = NodeSpec(name="api", port=14002, proxy_mode="tcp")
        adapter = Adapter(node)
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=14001))

        state = CircuitState(
            adapters={"api": AdapterState(node_name="api", status=NodeStatus.ACTIVE)}
        )

        custodian = Custodian({"api": adapter}, state, poll_interval=0.1)
        try:
            events = await custodian.check_once()
            assert len(events) == 0
            assert state.adapters["api"].last_health_verdict == HealthVerdict.HEALTHY
        finally:
            backend.close()
            await backend.wait_closed()

    async def test_detects_unhealthy(self):
        node = NodeSpec(name="api", port=14003, proxy_mode="tcp")
        adapter = Adapter(node)
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=14099))  # nothing listening

        state = CircuitState(
            adapters={"api": AdapterState(node_name="api", status=NodeStatus.ACTIVE)}
        )

        custodian = Custodian({"api": adapter}, state, poll_interval=0.1)
        events = await custodian.check_once()
        assert state.adapters["api"].consecutive_failures == 1
        # Not enough failures for repair yet
        assert len(events) == 0

    async def test_triggers_repair_after_threshold(self):
        node = NodeSpec(name="api", port=14004, proxy_mode="tcp")
        adapter = Adapter(node)
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=14099))

        state = CircuitState(
            adapters={
                "api": AdapterState(
                    node_name="api",
                    status=NodeStatus.ACTIVE,
                    consecutive_failures=2,  # One more will trigger
                    service=ServiceSlot(command="./run.sh", is_mock=False),
                )
            }
        )

        lifecycle = AsyncMock()
        custodian = Custodian(
            {"api": adapter}, state, lifecycle=lifecycle, poll_interval=0.1
        )

        events = await custodian.check_once()
        assert len(events) == 1
        assert events[0].action == CustodianAction.RESTART_SERVICE
        assert events[0].success is True
        lifecycle.restart_service.assert_called_once_with("api")

    async def test_no_lifecycle_records_event(self):
        node = NodeSpec(name="api", port=14005, proxy_mode="tcp")
        adapter = Adapter(node)
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=14099))

        state = CircuitState(
            adapters={
                "api": AdapterState(
                    node_name="api",
                    consecutive_failures=2,
                    service=ServiceSlot(command="./run.sh", is_mock=False),
                )
            }
        )

        # No lifecycle manager
        custodian = Custodian({"api": adapter}, state, poll_interval=0.1)
        events = await custodian.check_once()
        assert len(events) == 1
        assert events[0].success is False
        assert "No lifecycle" in events[0].detail

    async def test_recovers_from_faulted(self):
        backend = await asyncio.start_server(
            lambda r, w: w.close(), "127.0.0.1", 14006
        )
        node = NodeSpec(name="api", port=14007, proxy_mode="tcp")
        adapter = Adapter(node)
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=14006))

        state = CircuitState(
            adapters={
                "api": AdapterState(
                    node_name="api",
                    status=NodeStatus.FAULTED,
                    consecutive_failures=5,
                )
            }
        )

        custodian = Custodian({"api": adapter}, state, poll_interval=0.1)
        try:
            await custodian.check_once()
            assert state.adapters["api"].status == NodeStatus.ACTIVE
            assert state.adapters["api"].consecutive_failures == 0
        finally:
            backend.close()
            await backend.wait_closed()

    async def test_run_and_stop(self):
        node = NodeSpec(name="api", port=14008, proxy_mode="tcp")
        adapter = Adapter(node)
        state = CircuitState(
            adapters={"api": AdapterState(node_name="api")}
        )

        custodian = Custodian({"api": adapter}, state, poll_interval=0.05)
        task = asyncio.create_task(custodian.run())
        await asyncio.sleep(0.01)  # let the task start
        assert custodian.is_running

        await asyncio.sleep(0.2)
        custodian.stop()
        await asyncio.wait_for(task, timeout=2.0)
        assert not custodian.is_running


class TestAnomalyDetector:
    def test_no_anomaly_on_healthy(self):
        node = NodeSpec(name="api", port=14010, proxy_mode="tcp")
        adapter = Adapter(node)
        # Normal latency data
        for i in range(50):
            adapter.metrics.record_latency(10.0 + i * 0.1)
        adapter.metrics.requests_total = 100
        adapter.metrics.requests_failed = 1

        detector = AnomalyDetector()
        anomalies = detector.check(adapter)
        assert len(anomalies) == 0

    def test_detects_latency_spike(self):
        node = NodeSpec(name="api", port=14011, proxy_mode="tcp")
        adapter = Adapter(node)
        # Normal latency, then a massive spike
        for _ in range(99):
            adapter.metrics.record_latency(10.0)
        adapter.metrics.record_latency(1000.0)  # huge spike

        detector = AnomalyDetector(z_threshold=2.0)
        anomalies = detector.check(adapter)
        assert len(anomalies) >= 1
        assert "z-score" in anomalies[0]

    def test_detects_slo_violation(self):
        node = NodeSpec(name="api", port=14012, proxy_mode="tcp")
        adapter = Adapter(node)
        # All latencies above SLO
        for _ in range(100):
            adapter.metrics.record_latency(300.0)

        rules = [TelemetryClassRule(
            match="POST /pay", telemetry_class="payment", slo_p95_ms=200,
        )]
        detector = AnomalyDetector()
        anomalies = detector.check(adapter, slo_rules=rules)
        assert any("SLO" in a for a in anomalies)

    def test_detects_high_error_rate(self):
        node = NodeSpec(name="api", port=14013, proxy_mode="tcp")
        adapter = Adapter(node)
        adapter.metrics.requests_total = 20
        adapter.metrics.requests_failed = 15
        for _ in range(20):
            adapter.metrics.record_latency(10.0)

        detector = AnomalyDetector()
        anomalies = detector.check(adapter)
        assert any("error rate" in a for a in anomalies)

    def test_no_anomaly_with_few_samples(self):
        node = NodeSpec(name="api", port=14014, proxy_mode="tcp")
        adapter = Adapter(node)
        # Too few data points for statistical detection
        adapter.metrics.record_latency(10.0)
        adapter.metrics.record_latency(1000.0)

        detector = AnomalyDetector()
        anomalies = detector.check(adapter)
        # Not enough data for z-score, and requests_total < 10
        assert len(anomalies) == 0


class TestRepairPlaybookWithAnomalies:
    def test_reroute_on_anomaly(self):
        playbook = RepairPlaybook()
        state = AdapterState(
            node_name="api",
            service=ServiceSlot(command="./run.sh", is_mock=False),
            last_health_verdict=HealthVerdict.HEALTHY,
        )
        result = playbook.decide(state, anomalies=["SLO violation"])
        assert result == CustodianAction.REROUTE

    def test_anomaly_ignored_when_unhealthy(self):
        playbook = RepairPlaybook()
        state = AdapterState(
            node_name="api",
            service=ServiceSlot(command="./run.sh", is_mock=False),
            last_health_verdict=HealthVerdict.UNHEALTHY,
            consecutive_failures=3,
        )
        result = playbook.decide(state, anomalies=["SLO violation"])
        assert result == CustodianAction.RESTART_SERVICE
