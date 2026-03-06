"""Cross-node signal aggregation.

Collects signals from all adapters, persists to JSONL,
and provides querying and per-path statistics.
"""

from __future__ import annotations

import asyncio
import collections
import logging
from dataclasses import dataclass, field
from pathlib import Path

from baton.adapter import Adapter
from baton.schemas import SignalRecord
from baton.state import append_jsonl, read_jsonl

logger = logging.getLogger(__name__)

SIGNALS_FILE = "signals.jsonl"


@dataclass
class PathStat:
    """Per-path aggregation."""

    path: str
    count: int = 0
    avg_latency_ms: float = 0.0
    error_count: int = 0

    @property
    def error_rate(self) -> float:
        return self.error_count / self.count if self.count > 0 else 0.0


class SignalAggregator:
    """Collects signals from all adapters, persists to JSONL.

    Paper 20 (Ritual Shape): Repeated signals degrade performance monotonically
    (+0.07 nats per repeat). Deduplication suppresses consecutive identical
    signals from the same node+path within a time window.
    """

    def __init__(
        self,
        adapters: dict[str, Adapter],
        project_dir: str | Path,
        buffer_size: int = 10000,
        flush_interval: float = 10.0,
        dedup_window_s: float = 1.0,
    ):
        self._adapters = adapters
        self._project_dir = Path(project_dir)
        self._buffer: collections.deque[SignalRecord] = collections.deque(
            maxlen=buffer_size
        )
        self._flush_interval = flush_interval
        self._dedup_window_s = dedup_window_s
        self._last_seen: dict[str, str] = {}  # (node:path:status) -> timestamp
        self._dedup_count: int = 0
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)

    async def run(self) -> None:
        """Async loop: drain signals from adapters, append to buffer + JSONL."""
        self._running = True
        try:
            while self._running:
                self._collect()
                await asyncio.sleep(self._flush_interval)
        except asyncio.CancelledError:
            pass
        finally:
            # Final drain
            self._collect()
            self._running = False

    def stop(self) -> None:
        """Signal the run loop to stop."""
        self._running = False

    @property
    def dedup_count(self) -> int:
        """Number of signals suppressed by deduplication."""
        return self._dedup_count

    def _is_duplicate(self, sig: SignalRecord) -> bool:
        """Check if signal is a duplicate within the dedup window.

        Paper 20: Within-session repetition degrades performance monotonically.
        Suppress consecutive identical signals (same node+path+status) within
        dedup_window_s seconds.
        """
        if self._dedup_window_s <= 0:
            return False
        key = f"{sig.node_name}:{sig.path}:{sig.status_code}"
        prev_ts = self._last_seen.get(key)
        self._last_seen[key] = sig.timestamp
        if not prev_ts or not sig.timestamp:
            return False
        try:
            from datetime import datetime, timezone
            prev = datetime.fromisoformat(prev_ts)
            curr = datetime.fromisoformat(sig.timestamp)
            delta = (curr - prev).total_seconds()
            return 0 <= delta < self._dedup_window_s
        except (ValueError, TypeError):
            return False

    def _collect(self) -> None:
        """Drain signals from all adapters into buffer and JSONL.

        Applies deduplication (Paper 20: no repetition).
        """
        for adapter in self._adapters.values():
            signals = adapter.drain_signals()
            for sig in signals:
                if self._is_duplicate(sig):
                    self._dedup_count += 1
                    continue
                self._buffer.append(sig)
                append_jsonl(
                    self._project_dir,
                    SIGNALS_FILE,
                    sig.model_dump(),
                )

    def query(
        self,
        node: str | None = None,
        path: str | None = None,
        last_n: int = 100,
    ) -> list[SignalRecord]:
        """Query in-memory buffer."""
        results = list(self._buffer)
        if node:
            results = [s for s in results if s.node_name == node]
        if path:
            results = [s for s in results if path in s.path]
        return results[-last_n:]

    def path_stats(self, node: str | None = None) -> dict[str, PathStat]:
        """Per-path aggregation: count, avg_latency, error_rate."""
        signals = list(self._buffer)
        if node:
            signals = [s for s in signals if s.node_name == node]

        stats: dict[str, PathStat] = {}
        totals: dict[str, list[float]] = {}

        for sig in signals:
            if sig.path not in stats:
                stats[sig.path] = PathStat(path=sig.path)
                totals[sig.path] = []
            stats[sig.path].count += 1
            totals[sig.path].append(sig.latency_ms)
            if sig.status_code >= 400:
                stats[sig.path].error_count += 1

        for path, stat in stats.items():
            latencies = totals[path]
            if latencies:
                stat.avg_latency_ms = sum(latencies) / len(latencies)

        return stats

    @staticmethod
    def load_history(
        project_dir: str | Path,
        node: str | None = None,
        last_n: int | None = None,
    ) -> list[dict]:
        """Read from .baton/signals.jsonl."""
        records = read_jsonl(project_dir, SIGNALS_FILE, last_n=last_n)
        if node:
            records = [r for r in records if r.get("node_name") == node]
        return records
