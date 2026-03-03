"""Tests for the custodian monitoring agent."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from baton.adapter import Adapter, BackendTarget
from baton.custodian import Custodian, RepairPlaybook
from baton.schemas import (
    AdapterState,
    CircuitState,
    CustodianAction,
    HealthVerdict,
    NodeSpec,
    NodeStatus,
    ServiceSlot,
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
        node = NodeSpec(name="api", port=14002)
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
        node = NodeSpec(name="api", port=14003)
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
        node = NodeSpec(name="api", port=14004)
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
        node = NodeSpec(name="api", port=14005)
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
        node = NodeSpec(name="api", port=14007)
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
        node = NodeSpec(name="api", port=14008)
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
