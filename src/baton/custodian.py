"""Custodian -- monitoring agent for circuit health and self-healing.

Polls adapter health endpoints, detects faults, and runs repair actions.
All repairs are atomic: new thing running before old removed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Protocol

from baton.adapter import Adapter
from baton.schemas import (
    AdapterState,
    CircuitState,
    CustodianAction,
    CustodianEvent,
    HealthVerdict,
    NodeStatus,
)

logger = logging.getLogger(__name__)

HEALTH_POLL_INTERVAL = 5.0
FAILURE_THRESHOLD = 3


class LifecycleActions(Protocol):
    """Protocol for lifecycle actions the custodian can invoke."""

    async def restart_service(self, node_name: str) -> None: ...
    async def slot_mock(self, node_name: str) -> None: ...


class RepairPlaybook:
    """Determines repair action based on fault type and history."""

    def decide(self, adapter_state: AdapterState) -> CustodianAction:
        """Decide what repair action to take.

        - < FAILURE_THRESHOLD consecutive failures: restart service
        - >= FAILURE_THRESHOLD and has a command: replace with mock
        - No command (was already mock): escalate
        """
        if adapter_state.service.is_mock:
            return CustodianAction.ESCALATE

        if adapter_state.consecutive_failures < FAILURE_THRESHOLD * 2:
            return CustodianAction.RESTART_SERVICE
        else:
            return CustodianAction.REPLACE_SERVICE


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
    ):
        self._adapters = adapters
        self._state = state
        self._lifecycle = lifecycle
        self._playbook = playbook or RepairPlaybook()
        self._poll_interval = poll_interval
        self._running = False
        self._events: list[CustodianEvent] = []

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
