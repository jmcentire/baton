"""Span exporter that forwards to Arbiter's OTLP endpoint.

Fire-and-forget: never blocks the proxied request. Tracks drop rate.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque

from baton.tracing import SpanData, SpanExporter

logger = logging.getLogger(__name__)


class ArbiterSpanForwarder:
    """Forwards spans to Arbiter's OTLP endpoint.

    Fire-and-forget with bounded queue. If queue is full, spans are dropped.
    Drop rate is tracked as a metric.
    """

    def __init__(self, endpoint: str, max_queue: int = 10000):
        self._endpoint = endpoint
        self._queue: deque[SpanData] = deque(maxlen=max_queue)
        self._spans_forwarded: int = 0
        self._spans_dropped: int = 0
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def spans_forwarded(self) -> int:
        return self._spans_forwarded

    @property
    def spans_dropped(self) -> int:
        return self._spans_dropped

    @property
    def drop_rate(self) -> float:
        total = self._spans_forwarded + self._spans_dropped
        return self._spans_dropped / total if total > 0 else 0.0

    def enqueue(self, spans: list[SpanData]) -> None:
        """Add spans to the forwarding queue. Drops if queue is full."""
        for span in spans:
            if len(self._queue) >= self._queue.maxlen:
                self._spans_dropped += 1
            else:
                self._queue.append(span)

    async def run(self) -> None:
        """Background loop: drain queue and forward to Arbiter."""
        self._running = True
        try:
            while self._running:
                if self._queue:
                    batch = []
                    while self._queue and len(batch) < 100:
                        batch.append(self._queue.popleft())
                    if batch:
                        await self._forward_batch(batch)
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False

    async def _forward_batch(self, batch: list[SpanData]) -> None:
        """Forward a batch of spans to Arbiter. Fire-and-forget."""
        try:
            # Simple JSON-over-HTTP forwarding
            import json
            payload = json.dumps({
                "spans": [
                    {
                        "name": s.name,
                        "trace_id": s.trace_id,
                        "span_id": s.span_id,
                        "parent_span_id": s.parent_span_id,
                        "start_time_ns": s.start_time_ns,
                        "end_time_ns": s.end_time_ns,
                        "attributes": s.attributes,
                        "status": s.status,
                        "node_name": s.node_name,
                    }
                    for s in batch
                ]
            }).encode("utf-8")

            # Parse endpoint
            url = self._endpoint
            if "://" in url:
                _, rest = url.split("://", 1)
            else:
                rest = url
            if "/" in rest:
                host_port = rest.split("/", 1)[0]
            else:
                host_port = rest
            if ":" in host_port:
                host, port_str = host_port.split(":", 1)
                port = int(port_str)
            else:
                host = host_port
                port = 80

            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=2.0,
            )
            request = (
                f"POST /v1/traces HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(payload)}\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            ).encode("ascii")
            writer.write(request + payload)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            self._spans_forwarded += len(batch)
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
            self._spans_dropped += len(batch)
            logger.debug(f"Arbiter span forwarding failed: {e}")


class CompositeSpanExporter(SpanExporter):
    """Delegates to multiple span exporters.

    Used when both the primary exporter and Arbiter forwarder are active.
    """

    def __init__(self, primary: SpanExporter, forwarder: ArbiterSpanForwarder):
        self._primary = primary
        self._forwarder = forwarder

    def export(self, spans: list[SpanData]) -> None:
        """Export to primary and enqueue for Arbiter (non-blocking)."""
        self._primary.export(spans)
        self._forwarder.enqueue(spans)
