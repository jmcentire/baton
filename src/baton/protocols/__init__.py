"""Protocol handler abstraction for Baton adapters.

Defines the ProtocolHandler protocol and a registry for handler lookup.
Each protocol handler implements connection handling and health checking.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from baton.schemas import HealthCheck, HealthVerdict, NodeSpec

if TYPE_CHECKING:
    from baton.adapter import Adapter


@dataclass
class ConnectionContext:
    """Shared context passed to protocol handlers during connection handling.

    Provides access to adapter state without coupling handlers to the Adapter class.
    """

    node: NodeSpec
    adapter: Adapter


@runtime_checkable
class ProtocolHandler(Protocol):
    """Protocol interface for connection handlers.

    Implementations handle the transport-level logic for a specific protocol
    (HTTP, TCP, gRPC, protobuf, SOAP, etc.). The Adapter remains the lifecycle
    owner; handlers only deal with individual connection processing.
    """

    async def handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        ctx: ConnectionContext,
    ) -> None:
        """Handle a single client connection.

        Args:
            reader: Client's stream reader.
            writer: Client's stream writer.
            ctx: Shared connection context with adapter access.
        """
        ...

    async def health_check(
        self, host: str, port: int, metadata: dict[str, str]
    ) -> HealthCheck:
        """Check backend health using protocol-specific logic.

        Args:
            host: Backend host.
            port: Backend port.
            metadata: Node metadata dict.

        Returns:
            HealthCheck result with verdict and latency.
        """
        ...


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[ProtocolHandler]] = {}


def register_handler(mode: str, handler_cls: type[ProtocolHandler]) -> None:
    """Register a protocol handler class for a proxy mode."""
    _REGISTRY[mode] = handler_cls


def get_handler(mode: str) -> type[ProtocolHandler] | None:
    """Look up a registered handler class by proxy mode."""
    return _REGISTRY.get(mode)


def list_handlers() -> dict[str, type[ProtocolHandler]]:
    """Return all registered handlers."""
    return dict(_REGISTRY)
