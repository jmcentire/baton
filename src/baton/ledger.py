"""Ledger client for egress node sync and field masking.

Fetches egress node configuration and field masks from Ledger.
All methods degrade gracefully when Ledger is unreachable.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_TIMEOUT = 2.0


@dataclass(frozen=True)
class FieldMask:
    """A field masking rule from Ledger."""
    field: str
    replacement: str = "[ENCRYPTED]"
    reason: str = ""


@dataclass(frozen=True)
class EgressNodeConfig:
    """Egress node configuration from Ledger export."""
    name: str
    port: int = 0
    protocol: str = "http"
    mock_generator: str = ""      # "ledger" if Ledger provides mocks
    masked_fields: list[FieldMask] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


class LedgerClient:
    """Client for Ledger's REST API.

    All methods degrade gracefully: unreachable Ledger returns empty results.
    """

    def __init__(self, api_endpoint: str):
        self._api_endpoint = api_endpoint.rstrip("/")

    @property
    def api_endpoint(self) -> str:
        return self._api_endpoint

    async def is_reachable(self) -> bool:
        try:
            status, _ = await self._get("/health")
            return status is not None and 200 <= status < 500
        except Exception:
            return False

    async def get_egress_export(self) -> list[EgressNodeConfig]:
        """Fetch egress node configs from Ledger.

        Returns empty list if unreachable.
        """
        status, body = await self._get("/export/baton")
        if status is None or status != 200 or body is None:
            return []
        try:
            data = json.loads(body)
            nodes = []
            for n in data.get("egress_nodes", []):
                masks = [
                    FieldMask(
                        field=m.get("field", ""),
                        replacement=m.get("replacement", "[ENCRYPTED]"),
                        reason=m.get("reason", ""),
                    )
                    for m in n.get("masked_fields", [])
                ]
                nodes.append(EgressNodeConfig(
                    name=n.get("name", ""),
                    port=n.get("port", 0),
                    protocol=n.get("protocol", "http"),
                    mock_generator=n.get("mock_generator", ""),
                    masked_fields=masks,
                    metadata=n.get("metadata", {}),
                ))
            return nodes
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"Failed to parse Ledger egress export: {e}")
            return []

    async def get_mock_records(
        self, tiers: list[str], run_id: str = "",
    ) -> list[dict]:
        """Fetch canary-fingerprinted mock records from Ledger.

        Returns empty list if unreachable.
        """
        payload = json.dumps({"tiers": tiers, "run_id": run_id}).encode("utf-8")
        status, body = await self._post("/mock/canary-records", payload)
        if status is None or status != 200 or body is None:
            return []
        try:
            data = json.loads(body)
            return data.get("records", [])
        except (json.JSONDecodeError, ValueError):
            return []

    async def _get(self, path: str) -> tuple[int | None, str | None]:
        return await self._request("GET", path)

    async def _post(self, path: str, body: bytes = b"") -> tuple[int | None, str | None]:
        return await self._request("POST", path, body)

    async def _request(
        self, method: str, path: str, body: bytes = b"",
    ) -> tuple[int | None, str | None]:
        try:
            url = self._api_endpoint + path
            if "://" in url:
                _, rest = url.split("://", 1)
            else:
                rest = url
            if "/" in rest:
                host_port, req_path = rest.split("/", 1)
                req_path = "/" + req_path
            else:
                host_port = rest
                req_path = path
            if ":" in host_port:
                host, port_str = host_port.split(":", 1)
                port = int(port_str)
            else:
                host = host_port
                port = 80

            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=_TIMEOUT,
            )
            headers = (
                f"{method} {req_path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                f"Connection: close\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"\r\n"
            ).encode("ascii")
            writer.write(headers + body)
            await writer.drain()
            response = await asyncio.wait_for(reader.read(65536), timeout=_TIMEOUT)
            writer.close()
            await writer.wait_closed()

            status_code = None
            response_body = None
            if response:
                first_line = response.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
                parts = first_line.split(" ")
                if len(parts) >= 2:
                    try:
                        status_code = int(parts[1])
                    except ValueError:
                        pass
                if b"\r\n\r\n" in response:
                    response_body = response.split(b"\r\n\r\n", 1)[1].decode("utf-8", errors="replace")
            return status_code, response_body
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError, ValueError) as e:
            logger.debug(f"Ledger request failed: {method} {path}: {e}")
            return None, None
