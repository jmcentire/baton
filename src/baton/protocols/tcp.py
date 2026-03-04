"""TCP protocol handler -- bidirectional byte pipe.

Used for raw TCP proxying and as the base for gRPC (transparent HTTP/2).
"""

from __future__ import annotations

import asyncio
import logging
import time

from baton.protocols import ConnectionContext, register_handler
from baton.schemas import HealthCheck, HealthVerdict

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class TCPHandler:
    """Bidirectional TCP byte pipe handler."""

    async def handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        ctx: ConnectionContext,
    ) -> None:
        adapter = ctx.adapter
        if adapter._draining or not adapter._backend.is_configured:
            writer.close()
            return

        adapter._active_connections += 1
        backend_writer = None
        conn_timeout = adapter._policy.timeout_ms / 1000 if adapter._policy else 30.0
        try:
            backend_reader, backend_writer = await asyncio.wait_for(
                asyncio.open_connection(adapter._backend.host, adapter._backend.port),
                timeout=conn_timeout,
            )
            await asyncio.gather(
                _pipe(reader, backend_writer),
                _pipe(backend_reader, writer),
            )
            adapter._metrics.requests_total += 1
        except Exception as e:
            adapter._metrics.requests_failed += 1
            logger.debug(f"[{ctx.node.name}] TCP proxy error: {e}")
        finally:
            adapter._decrement_connections()
            writer.close()
            if backend_writer:
                backend_writer.close()

    async def health_check(
        self, host: str, port: int, metadata: dict[str, str]
    ) -> HealthCheck:
        """TCP connectivity check."""
        node_name = metadata.get("_node_name", "")
        start = time.monotonic()
        try:
            r, w = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5.0
            )
            w.close()
            await w.wait_closed()
            latency = (time.monotonic() - start) * 1000
            return HealthCheck(
                node_name=node_name,
                verdict=HealthVerdict.HEALTHY,
                latency_ms=latency,
                timestamp=_now_iso(),
            )
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return HealthCheck(
                node_name=node_name,
                verdict=HealthVerdict.UNHEALTHY,
                latency_ms=latency,
                detail=str(e),
                timestamp=_now_iso(),
            )


async def _pipe(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    """Copy bytes from reader to writer until EOF."""
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass


register_handler("tcp", TCPHandler)
register_handler("grpc", TCPHandler)
