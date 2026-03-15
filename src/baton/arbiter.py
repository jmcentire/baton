"""Arbiter client for trust scoring and declaration gap checking.

All methods degrade gracefully when Arbiter is unreachable — they return
None or empty results rather than raising. The circuit never blocks on
Arbiter availability.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Timeout for all Arbiter API calls (seconds)
_TIMEOUT = 2.0


@dataclass(frozen=True)
class TrustScore:
    """Trust assessment for a node from Arbiter."""
    node_name: str
    score: float                   # 0.0 - 1.0
    level: str = "unknown"         # high, established, low, unknown
    authoritative: bool = False    # True if node has authority domains
    timestamp: str = ""

    @property
    def is_low_trust_authoritative(self) -> bool:
        return self.authoritative and self.level == "low"


@dataclass(frozen=True)
class DeclarationGapResult:
    """Result of a declaration gap check."""
    has_gap: bool = False
    unauthorized_tiers: list[str] = field(default_factory=list)
    detail: str = ""


class ArbiterClient:
    """Client for Arbiter's REST API.

    All methods are async and use a short timeout. If Arbiter is
    unreachable, methods return None (for single results) or empty
    collections (for lists).
    """

    def __init__(self, api_endpoint: str):
        """
        Args:
            api_endpoint: Base URL for Arbiter's HTTP API (e.g. http://localhost:7700)
        """
        self._api_endpoint = api_endpoint.rstrip("/")

    @property
    def api_endpoint(self) -> str:
        return self._api_endpoint

    async def is_reachable(self) -> bool:
        """Check if Arbiter is reachable."""
        try:
            status, _ = await self._get("/health")
            return status is not None and 200 <= status < 500
        except Exception:
            return False

    async def get_trust_score(self, node_name: str) -> TrustScore | None:
        """Get trust score for a node.

        Returns None if Arbiter is unreachable.
        """
        status, body = await self._get(f"/trust/{node_name}")
        if status is None or status != 200 or body is None:
            return None
        try:
            data = json.loads(body)
            return TrustScore(
                node_name=node_name,
                score=float(data.get("score", 0.0)),
                level=data.get("level", "unknown"),
                authoritative=data.get("authoritative", False),
                timestamp=data.get("timestamp", ""),
            )
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.debug(f"Failed to parse trust score for {node_name}: {e}")
            return None

    async def check_declaration_gap(
        self,
        node_name: str,
        declared_reads: list[str],
        declared_writes: list[str],
    ) -> DeclarationGapResult:
        """Check if a node's declared data access matches Arbiter's observations.

        Returns a result with has_gap=False if Arbiter is unreachable (fail-open).
        """
        payload = json.dumps({
            "node_name": node_name,
            "declared_reads": declared_reads,
            "declared_writes": declared_writes,
        }).encode("utf-8")
        status, body = await self._post("/declaration-gap", payload)
        if status is None or status != 200 or body is None:
            return DeclarationGapResult()
        try:
            data = json.loads(body)
            return DeclarationGapResult(
                has_gap=data.get("has_gap", False),
                unauthorized_tiers=data.get("unauthorized_tiers", []),
                detail=data.get("detail", ""),
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"Failed to parse declaration gap for {node_name}: {e}")
            return DeclarationGapResult()

    async def get_canary_corpus(
        self, tiers: list[str], run_id: str = "",
    ) -> list[dict]:
        """Fetch canary corpus from Arbiter for taint testing.

        Returns empty list if Arbiter is unreachable.
        """
        payload = json.dumps({
            "tiers": tiers,
            "run_id": run_id,
        }).encode("utf-8")
        status, body = await self._post("/canary/inject", payload)
        if status is None or status != 200 or body is None:
            return []
        try:
            data = json.loads(body)
            return data.get("corpus", [])
        except (json.JSONDecodeError, ValueError):
            return []

    async def get_canary_results(self, run_id: str) -> dict:
        """Fetch canary test results from Arbiter.

        Returns empty dict if Arbiter is unreachable.
        """
        status, body = await self._get(f"/canary/results/{run_id}")
        if status is None or status != 200 or body is None:
            return {}
        try:
            return json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return {}

    async def _get(self, path: str) -> tuple[int | None, str | None]:
        """HTTP GET to Arbiter API. Returns (status_code, body) or (None, None)."""
        return await self._request("GET", path)

    async def _post(self, path: str, body: bytes = b"") -> tuple[int | None, str | None]:
        """HTTP POST to Arbiter API. Returns (status_code, body) or (None, None)."""
        return await self._request("POST", path, body)

    async def _request(
        self, method: str, path: str, body: bytes = b"",
    ) -> tuple[int | None, str | None]:
        """Raw HTTP request to Arbiter. Returns (status, response_body) or (None, None)."""
        try:
            # Parse host:port from api_endpoint
            url = self._api_endpoint + path
            # Simple URL parsing for asyncio.open_connection
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
                asyncio.open_connection(host, port),
                timeout=_TIMEOUT,
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

            # Read response
            response = await asyncio.wait_for(reader.read(65536), timeout=_TIMEOUT)
            writer.close()
            await writer.wait_closed()

            # Parse status code
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
                # Extract body after \r\n\r\n
                if b"\r\n\r\n" in response:
                    response_body = response.split(b"\r\n\r\n", 1)[1].decode("utf-8", errors="replace")

            return status_code, response_body

        except (asyncio.TimeoutError, ConnectionRefusedError, OSError, ValueError) as e:
            logger.debug(f"Arbiter request failed: {method} {path}: {e}")
            return None, None
