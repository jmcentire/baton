"""Multi-cluster federation for Baton.

Provides heartbeat-based health monitoring, pull-based state sync,
and automatic failover between federated clusters.

Architecture:
  - FederationServer: HTTP API endpoint for receiving heartbeats and queries
  - FederationManager: Heartbeat loop, state sync, failover orchestration
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from baton.schemas import (
    ClusterIdentity,
    FederationConfig,
    FederationEdge,
    PeerState,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FederationServer:
    """HTTP API endpoint for federation communication.

    Exposes:
      GET  /federation/status   - This cluster's federation status
      GET  /federation/nodes    - This cluster's node list + health
      POST /federation/heartbeat - Receive heartbeat from a peer
    """

    def __init__(
        self,
        identity: ClusterIdentity,
        get_local_state: callable,
    ):
        self._identity = identity
        self._get_local_state = get_local_state
        self._server: asyncio.Server | None = None
        self._peer_states: dict[str, PeerState] = {}

    @property
    def peer_states(self) -> dict[str, PeerState]:
        return dict(self._peer_states)

    def update_peer(self, peer: PeerState) -> None:
        """Update a peer's state (called by FederationManager)."""
        self._peer_states[peer.cluster_name] = peer

    async def start(self) -> None:
        """Start the federation HTTP server."""
        # Parse host:port from identity.api_endpoint
        endpoint = self._identity.api_endpoint
        if "://" in endpoint:
            endpoint = endpoint.split("://", 1)[1]
        if ":" in endpoint:
            host, port_str = endpoint.rsplit(":", 1)
            port = int(port_str)
        else:
            host = endpoint
            port = 9090

        self._server = await asyncio.start_server(
            self._handle_request, host, port
        )
        logger.info(f"Federation server [{self._identity.name}] listening on {host}:{port}")

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_request(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10.0)
            request_line = data.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
            parts = request_line.split(" ")
            method = parts[0] if parts else ""
            path = parts[1] if len(parts) >= 2 else ""

            # Read body for POST
            body = b""
            content_length = 0
            for line in data.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    content_length = int(line.split(b":")[1].strip())
            if content_length > 0:
                body = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout=10.0
                )

            if path == "/federation/status" and method == "GET":
                await self._handle_status(writer)
            elif path == "/federation/nodes" and method == "GET":
                await self._handle_nodes(writer)
            elif path == "/federation/heartbeat" and method == "POST":
                await self._handle_heartbeat(writer, body)
            else:
                self._write_response(writer, 404, json.dumps({"error": "not found"}))
        except Exception as e:
            logger.debug(f"Federation request error: {e}")
            try:
                self._write_response(writer, 500, json.dumps({"error": str(e)}))
            except Exception:
                pass
        finally:
            try:
                await writer.drain()
                writer.close()
            except Exception:
                pass

    async def _handle_status(self, writer: asyncio.StreamWriter) -> None:
        result = {
            "cluster": self._identity.name,
            "region": self._identity.region,
            "peers": {
                name: {
                    "reachable": ps.reachable,
                    "last_heartbeat": ps.last_heartbeat,
                }
                for name, ps in self._peer_states.items()
            },
        }
        self._write_response(writer, 200, json.dumps(result))

    async def _handle_nodes(self, writer: asyncio.StreamWriter) -> None:
        local_state = self._get_local_state()
        if local_state is None:
            self._write_response(writer, 200, json.dumps({"nodes": [], "live_nodes": []}))
            return

        nodes = {}
        for name, adapter in local_state.adapters.items():
            nodes[name] = {
                "status": str(adapter.status),
                "health": str(adapter.last_health_verdict),
            }

        result = {
            "cluster": self._identity.name,
            "nodes": nodes,
            "live_nodes": local_state.live_nodes,
        }
        self._write_response(writer, 200, json.dumps(result))

    async def _handle_heartbeat(
        self, writer: asyncio.StreamWriter, body: bytes
    ) -> None:
        try:
            data = json.loads(body)
            peer_name = data.get("cluster", "")
            peer_state = PeerState(
                cluster_name=peer_name,
                reachable=True,
                last_heartbeat=_now_iso(),
                node_count=data.get("node_count", 0),
                live_nodes=data.get("live_nodes", []),
                health_summary=data.get("health_summary", {}),
            )
            self._peer_states[peer_name] = peer_state
            self._write_response(writer, 200, json.dumps({"ok": True}))
        except Exception as e:
            self._write_response(writer, 400, json.dumps({"error": str(e)}))

    @staticmethod
    def _write_response(writer: asyncio.StreamWriter, status: int, body: str) -> None:
        reasons = {200: "OK", 400: "Bad Request", 404: "Not Found", 500: "Internal Server Error"}
        reason = reasons.get(status, "Unknown")
        encoded = body.encode()
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(encoded)}\r\n"
            f"Connection: close\r\n\r\n".encode()
            + encoded
        )


class FederationManager:
    """Orchestrates heartbeat loop, state sync, and failover.

    Pull-based: periodically sends heartbeats to peers and pulls their state.
    On peer unreachable for `failover_threshold` consecutive checks, triggers
    failover actions on federation edges that reference the failed peer.
    """

    def __init__(
        self,
        config: FederationConfig,
        server: FederationServer,
        get_local_state: callable,
    ):
        self._config = config
        self._server = server
        self._get_local_state = get_local_state
        self._running = False
        self._consecutive_failures: dict[str, int] = {}
        self._failed_over: set[str] = set()
        self._events: list[dict] = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def events(self) -> list[dict]:
        return list(self._events)

    @property
    def peer_states(self) -> dict[str, PeerState]:
        return self._server.peer_states

    async def run(self) -> None:
        """Async loop: heartbeat to peers at configured interval."""
        self._running = True
        try:
            while self._running:
                await self._heartbeat_round()
                await asyncio.sleep(self._config.heartbeat_interval_s)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False

    async def _heartbeat_round(self) -> None:
        """Send heartbeat to all peers and check responses."""
        local_state = self._get_local_state()
        heartbeat_data = self._build_heartbeat(local_state)

        for peer in self._config.peers:
            reachable = await self._send_heartbeat(peer, heartbeat_data)

            if reachable:
                self._consecutive_failures[peer.name] = 0
                # Pull peer state
                peer_state = await self._pull_peer_state(peer)
                if peer_state:
                    self._server.update_peer(peer_state)

                # Check for restore
                if peer.name in self._failed_over:
                    self._failed_over.discard(peer.name)
                    self._events.append({
                        "type": "federated_restore",
                        "peer": peer.name,
                        "timestamp": _now_iso(),
                    })
                    logger.info(f"Federation: peer '{peer.name}' restored")
            else:
                failures = self._consecutive_failures.get(peer.name, 0) + 1
                self._consecutive_failures[peer.name] = failures

                self._server.update_peer(PeerState(
                    cluster_name=peer.name,
                    reachable=False,
                    last_heartbeat=self._server.peer_states.get(peer.name, PeerState()).last_heartbeat,
                ))

                if (
                    failures >= self._config.failover_threshold
                    and peer.name not in self._failed_over
                ):
                    self._failed_over.add(peer.name)
                    self._events.append({
                        "type": "federated_failover",
                        "peer": peer.name,
                        "failures": failures,
                        "timestamp": _now_iso(),
                    })
                    logger.warning(
                        f"Federation: peer '{peer.name}' unreachable "
                        f"after {failures} attempts -- failover triggered"
                    )

    def _build_heartbeat(self, local_state) -> dict:
        """Build heartbeat payload from local state."""
        identity = self._config.identity
        data: dict = {
            "cluster": identity.name if identity else "",
            "timestamp": _now_iso(),
        }
        if local_state:
            data["node_count"] = len(local_state.adapters)
            data["live_nodes"] = local_state.live_nodes
            health = {}
            for name, adapter in local_state.adapters.items():
                health[name] = str(adapter.last_health_verdict)
            data["health_summary"] = health
        return data

    async def _send_heartbeat(self, peer: ClusterIdentity, data: dict) -> bool:
        """Send heartbeat to a peer. Returns True if successful."""
        try:
            host, port = self._parse_endpoint(peer.api_endpoint)
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=self._config.heartbeat_timeout_s,
            )
            body = json.dumps(data).encode()
            request = (
                f"POST /federation/heartbeat HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode() + body
            writer.write(request)
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=self._config.heartbeat_timeout_s)
            writer.close()

            return b"200" in response.split(b"\r\n", 1)[0]
        except Exception as e:
            logger.debug(f"Heartbeat to {peer.name} failed: {e}")
            return False

    async def _pull_peer_state(self, peer: ClusterIdentity) -> PeerState | None:
        """Pull node state from a peer via GET /federation/nodes."""
        try:
            host, port = self._parse_endpoint(peer.api_endpoint)
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=self._config.heartbeat_timeout_s,
            )
            request = (
                f"GET /federation/nodes HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode()
            writer.write(request)
            await writer.drain()

            response = await asyncio.wait_for(reader.read(65536), timeout=self._config.heartbeat_timeout_s)
            writer.close()

            # Parse response body
            parts = response.split(b"\r\n\r\n", 1)
            if len(parts) == 2:
                data = json.loads(parts[1])
                health_summary = {}
                for name, info in data.get("nodes", {}).items():
                    health_summary[name] = info.get("health", "unknown")
                return PeerState(
                    cluster_name=peer.name,
                    reachable=True,
                    last_heartbeat=_now_iso(),
                    node_count=len(data.get("nodes", {})),
                    live_nodes=data.get("live_nodes", []),
                    health_summary=health_summary,
                )
        except Exception as e:
            logger.debug(f"Pull state from {peer.name} failed: {e}")
        return None

    @staticmethod
    def _parse_endpoint(endpoint: str) -> tuple[str, int]:
        """Parse host:port from an endpoint string."""
        if "://" in endpoint:
            endpoint = endpoint.split("://", 1)[1]
        if ":" in endpoint:
            host, port_str = endpoint.rsplit(":", 1)
            return host, int(port_str)
        return endpoint, 9090
