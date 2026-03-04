"""Length-prefixed binary protocol handler.

Proxies length-prefixed binary messages (common in protobuf-over-TCP services).
Each message is a 4-byte big-endian length prefix followed by that many bytes.
Health check uses TCP connectivity.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time

from baton.protocols import ConnectionContext, register_handler
from baton.schemas import HealthCheck, HealthVerdict, ProxyMode

logger = logging.getLogger(__name__)

LENGTH_PREFIX_SIZE = 4
MAX_MESSAGE_SIZE = 16 * 1024 * 1024  # 16 MB


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class ProtobufHandler:
    """Length-prefixed binary message proxy.

    Each message: [4 bytes big-endian length][payload].
    Preserves message boundaries through the proxy.
    """

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
            # When one direction finishes, cancel the other
            t1 = asyncio.create_task(
                _relay_messages(reader, backend_writer, ctx.node.name, "client->backend")
            )
            t2 = asyncio.create_task(
                _relay_messages(backend_reader, writer, ctx.node.name, "backend->client")
            )
            done, pending = await asyncio.wait(
                [t1, t2], return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
            adapter._metrics.requests_total += 1
        except Exception as e:
            adapter._metrics.requests_failed += 1
            logger.debug(f"[{ctx.node.name}] protobuf proxy error: {e}")
        finally:
            adapter._decrement_connections()
            writer.close()
            if backend_writer:
                backend_writer.close()

    async def health_check(
        self, host: str, port: int, metadata: dict[str, str]
    ) -> HealthCheck:
        """TCP connectivity check (protobuf has no standard health protocol)."""
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


async def _relay_messages(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    node_name: str,
    direction: str,
) -> None:
    """Read length-prefixed messages and forward them."""
    try:
        while True:
            # Read 4-byte length prefix
            prefix = await reader.readexactly(LENGTH_PREFIX_SIZE)
            msg_len = struct.unpack("!I", prefix)[0]

            if msg_len > MAX_MESSAGE_SIZE:
                logger.warning(
                    f"[{node_name}] {direction}: message too large ({msg_len} bytes)"
                )
                break

            # Read payload
            payload = await reader.readexactly(msg_len)

            # Forward length + payload
            writer.write(prefix + payload)
            await writer.drain()
    except asyncio.IncompleteReadError:
        pass
    except (ConnectionResetError, BrokenPipeError):
        pass


register_handler("protobuf", ProtobufHandler)
