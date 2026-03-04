"""Persistent telemetry collection.

Periodically snapshots metrics to .baton/metrics.jsonl.
Supports Prometheus text exposition format.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from pathlib import Path

from baton.adapter import Adapter
from baton.dashboard import DashboardSnapshot, collect
from baton.schemas import CircuitSpec, CircuitState
from baton.state import append_jsonl, read_jsonl

logger = logging.getLogger(__name__)

METRICS_FILE = "metrics.jsonl"


class TelemetryCollector:
    """Periodically snapshots metrics to .baton/metrics.jsonl."""

    def __init__(
        self,
        adapters: dict[str, Adapter],
        state: CircuitState,
        circuit: CircuitSpec,
        project_dir: str | Path,
        flush_interval: float = 30.0,
    ):
        self._adapters = adapters
        self._state = state
        self._circuit = circuit
        self._project_dir = Path(project_dir)
        self._flush_interval = flush_interval
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    async def run(self) -> None:
        """Async loop: snapshot -> append to JSONL every flush_interval."""
        self._running = True
        try:
            while self._running:
                await self.flush_now()
                await asyncio.sleep(self._flush_interval)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

    def stop(self) -> None:
        """Signal the run loop to stop."""
        self._running = False

    async def flush_now(self) -> None:
        """Immediate snapshot + write."""
        try:
            snapshot = await collect(self._adapters, self._state, self._circuit)
            data = dataclasses.asdict(snapshot)
            append_jsonl(self._project_dir, METRICS_FILE, data)
        except Exception as e:
            logger.debug(f"Telemetry flush error: {e}")

    @staticmethod
    def load_history(
        project_dir: str | Path,
        node: str | None = None,
        last_n: int | None = None,
    ) -> list[dict]:
        """Read back from JSONL. Optional filters."""
        records = read_jsonl(project_dir, METRICS_FILE, last_n=last_n)
        if node:
            filtered = []
            for r in records:
                nodes = r.get("nodes", {})
                if node in nodes:
                    filtered.append({
                        "timestamp": r.get("timestamp"),
                        "node": nodes[node],
                    })
            return filtered
        return records

    @staticmethod
    def format_prometheus(snapshot: DashboardSnapshot) -> str:
        """Format snapshot as Prometheus text exposition."""
        lines = []
        for node in snapshot.nodes.values():
            labels = f'node="{node.name}",role="{node.role}"'
            lines.append(f'baton_requests_total{{{labels}}} {node.requests_total}')
            lines.append(f'baton_requests_failed{{{labels}}} {node.requests_failed}')
            lines.append(f'baton_error_rate{{{labels}}} {node.error_rate}')
            lines.append(f'baton_latency_p50_ms{{{labels}}} {node.latency_p50}')
            lines.append(f'baton_latency_p95_ms{{{labels}}} {node.latency_p95}')
            lines.append(f'baton_active_connections{{{labels}}} {node.active_connections}')
        return "\n".join(lines) + "\n"
