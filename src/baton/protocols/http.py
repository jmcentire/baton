"""HTTP protocol handler -- delegates to Adapter's HTTP forwarding logic.

The HTTP connection handler is tightly coupled to the Adapter's routing,
circuit breaker, tracing, and signal recording. Rather than duplicating that
complex logic, the HTTPHandler delegates to the Adapter's _handle_http_connection
and _http_health_check methods via the ConnectionContext.

This allows all proxy modes to dispatch through the unified ProtocolHandler
registry while keeping the HTTP implementation in adapter.py until a deeper
extraction is warranted.
"""

from __future__ import annotations

import asyncio
import logging

from baton.protocols import ConnectionContext, register_handler
from baton.schemas import HealthCheck

logger = logging.getLogger(__name__)


class HTTPHandler:
    """HTTP protocol handler -- delegates to Adapter's built-in HTTP logic."""

    async def handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        ctx: ConnectionContext,
    ) -> None:
        await ctx.adapter._handle_http_connection(reader, writer)

    async def health_check(
        self, host: str, port: int, metadata: dict[str, str]
    ) -> HealthCheck:
        # Health check needs the adapter reference, which we get from metadata
        # The adapter stores itself in metadata["_adapter_ref"] for HTTP health checks
        adapter = metadata.get("_adapter_ref")
        if adapter is not None:
            return await adapter._http_health_check()
        # Fallback: TCP connectivity check
        from baton.protocols.tcp import TCPHandler
        return await TCPHandler().health_check(host, port, metadata)


register_handler("http", HTTPHandler)
