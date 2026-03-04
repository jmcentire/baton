"""Tests for baton.federation -- multi-cluster federation."""

from __future__ import annotations

import asyncio
import json

import pytest

from baton.schemas import (
    AdapterState,
    CircuitState,
    ClusterIdentity,
    CustodianAction,
    FederationConfig,
    FederationEdge,
    HealthVerdict,
    NodeStatus,
    PeerState,
)
from baton.federation import FederationManager, FederationServer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_local_state(**kwargs) -> CircuitState:
    return CircuitState(
        circuit_name="test",
        live_nodes=kwargs.get("live_nodes", ["api"]),
        adapters=kwargs.get("adapters", {
            "api": AdapterState(
                node_name="api",
                status=NodeStatus.ACTIVE,
                last_health_verdict=HealthVerdict.HEALTHY,
            ),
            "backend": AdapterState(
                node_name="backend",
                status=NodeStatus.LISTENING,
                last_health_verdict=HealthVerdict.UNKNOWN,
            ),
        }),
    )


@pytest.fixture()
def cluster_a_identity():
    return ClusterIdentity(name="cluster-a", api_endpoint="127.0.0.1:19300", region="us-east")


@pytest.fixture()
def cluster_b_identity():
    return ClusterIdentity(name="cluster-b", api_endpoint="127.0.0.1:19301", region="us-west")


# ---------------------------------------------------------------------------
# FederationServer tests
# ---------------------------------------------------------------------------


async def _http_get(host: str, port: int, path: str) -> tuple[int, dict]:
    """Simple HTTP GET, returns (status_code, parsed_json)."""
    reader, writer = await asyncio.open_connection(host, port)
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()
    writer.write(request)
    await writer.drain()

    response = await asyncio.wait_for(reader.read(65536), timeout=5.0)
    writer.close()

    first_line = response.split(b"\r\n", 1)[0].decode()
    status = int(first_line.split(" ")[1])
    parts = response.split(b"\r\n\r\n", 1)
    body = json.loads(parts[1]) if len(parts) == 2 else {}
    return status, body


async def _http_post(host: str, port: int, path: str, data: dict) -> tuple[int, dict]:
    """Simple HTTP POST, returns (status_code, parsed_json)."""
    reader, writer = await asyncio.open_connection(host, port)
    body = json.dumps(data).encode()
    request = (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode() + body
    writer.write(request)
    await writer.drain()

    response = await asyncio.wait_for(reader.read(65536), timeout=5.0)
    writer.close()

    first_line = response.split(b"\r\n", 1)[0].decode()
    status = int(first_line.split(" ")[1])
    parts = response.split(b"\r\n\r\n", 1)
    resp_body = json.loads(parts[1]) if len(parts) == 2 else {}
    return status, resp_body


class TestFederationServer:
    async def test_status_endpoint(self, cluster_a_identity):
        local_state = _make_local_state()
        server = FederationServer(cluster_a_identity, lambda: local_state)
        await server.start()

        try:
            status, data = await _http_get("127.0.0.1", 19300, "/federation/status")
            assert status == 200
            assert data["cluster"] == "cluster-a"
            assert data["region"] == "us-east"
        finally:
            await server.stop()

    async def test_nodes_endpoint(self, cluster_a_identity):
        local_state = _make_local_state()
        server = FederationServer(cluster_a_identity, lambda: local_state)
        await server.start()

        try:
            status, data = await _http_get("127.0.0.1", 19300, "/federation/nodes")
            assert status == 200
            assert data["cluster"] == "cluster-a"
            assert "api" in data["nodes"]
            assert "api" in data["live_nodes"]
        finally:
            await server.stop()

    async def test_nodes_no_state(self, cluster_a_identity):
        server = FederationServer(cluster_a_identity, lambda: None)
        await server.start()

        try:
            status, data = await _http_get("127.0.0.1", 19300, "/federation/nodes")
            assert status == 200
            assert data["nodes"] == []
        finally:
            await server.stop()

    async def test_heartbeat_endpoint(self, cluster_a_identity):
        server = FederationServer(cluster_a_identity, lambda: None)
        await server.start()

        try:
            heartbeat = {
                "cluster": "cluster-b",
                "node_count": 3,
                "live_nodes": ["svc-x"],
                "health_summary": {"svc-x": "healthy"},
            }
            status, data = await _http_post(
                "127.0.0.1", 19300, "/federation/heartbeat", heartbeat
            )
            assert status == 200
            assert data["ok"] is True

            # Verify peer state was stored
            peers = server.peer_states
            assert "cluster-b" in peers
            assert peers["cluster-b"].reachable is True
            assert peers["cluster-b"].node_count == 3
        finally:
            await server.stop()

    async def test_404_unknown_path(self, cluster_a_identity):
        server = FederationServer(cluster_a_identity, lambda: None)
        await server.start()

        try:
            status, data = await _http_get("127.0.0.1", 19300, "/unknown")
            assert status == 404
        finally:
            await server.stop()


# ---------------------------------------------------------------------------
# FederationManager tests
# ---------------------------------------------------------------------------


class TestFederationManager:
    async def test_heartbeat_to_peer(self, cluster_a_identity, cluster_b_identity):
        """Manager sends heartbeat to peer and receives response."""
        # Start peer (cluster-b) server
        peer_state = _make_local_state()
        peer_server = FederationServer(cluster_b_identity, lambda: peer_state)
        await peer_server.start()

        # Setup cluster-a manager
        local_state = _make_local_state()
        config = FederationConfig(
            enabled=True,
            identity=cluster_a_identity,
            peers=[cluster_b_identity],
            heartbeat_interval_s=0.1,
            heartbeat_timeout_s=5.0,
            failover_threshold=3,
        )
        server_a = FederationServer(cluster_a_identity, lambda: local_state)
        manager = FederationManager(config, server_a, lambda: local_state)

        try:
            # Run one heartbeat round
            await manager._heartbeat_round()

            # Verify peer state was pulled
            peers = manager.peer_states
            assert "cluster-b" in peers
            assert peers["cluster-b"].reachable is True
        finally:
            await peer_server.stop()

    async def test_failover_on_unreachable(self, cluster_a_identity):
        """Manager triggers failover after consecutive failures."""
        local_state = _make_local_state()
        # Peer on a port nobody is listening on
        dead_peer = ClusterIdentity(
            name="dead-peer", api_endpoint="127.0.0.1:19399"
        )
        config = FederationConfig(
            enabled=True,
            identity=cluster_a_identity,
            peers=[dead_peer],
            heartbeat_interval_s=0.1,
            heartbeat_timeout_s=1.0,
            failover_threshold=2,
        )
        server_a = FederationServer(cluster_a_identity, lambda: local_state)
        manager = FederationManager(config, server_a, lambda: local_state)

        # Run heartbeat rounds until failover
        await manager._heartbeat_round()
        assert len(manager.events) == 0  # Not yet

        await manager._heartbeat_round()
        assert len(manager.events) == 1
        assert manager.events[0]["type"] == "federated_failover"
        assert manager.events[0]["peer"] == "dead-peer"

        # Third round should not generate another failover
        await manager._heartbeat_round()
        assert len(manager.events) == 1  # Still just one

    async def test_restore_after_failover(self, cluster_a_identity, cluster_b_identity):
        """Manager triggers restore when failed peer comes back."""
        local_state = _make_local_state()

        # First, simulate failover to a dead peer
        dead_peer = ClusterIdentity(
            name="cluster-b", api_endpoint="127.0.0.1:19398"
        )
        config = FederationConfig(
            enabled=True,
            identity=cluster_a_identity,
            peers=[dead_peer],
            heartbeat_interval_s=0.1,
            heartbeat_timeout_s=1.0,
            failover_threshold=1,
        )
        server_a = FederationServer(cluster_a_identity, lambda: local_state)
        manager = FederationManager(config, server_a, lambda: local_state)

        # Trigger failover
        await manager._heartbeat_round()
        assert any(e["type"] == "federated_failover" for e in manager.events)

        # Now start the peer
        peer_state = _make_local_state()
        peer_server = FederationServer(
            ClusterIdentity(name="cluster-b", api_endpoint="127.0.0.1:19398"),
            lambda: peer_state,
        )
        await peer_server.start()

        try:
            # Update config to point to live peer
            manager._config = FederationConfig(
                enabled=True,
                identity=cluster_a_identity,
                peers=[ClusterIdentity(name="cluster-b", api_endpoint="127.0.0.1:19398")],
                heartbeat_interval_s=0.1,
                heartbeat_timeout_s=5.0,
                failover_threshold=1,
            )

            # Run heartbeat -- should restore
            await manager._heartbeat_round()
            assert any(e["type"] == "federated_restore" for e in manager.events)
        finally:
            await peer_server.stop()

    async def test_run_and_stop(self, cluster_a_identity):
        """Manager run loop starts and stops cleanly."""
        local_state = _make_local_state()
        config = FederationConfig(
            enabled=True,
            identity=cluster_a_identity,
            peers=[],
            heartbeat_interval_s=0.1,
        )
        server_a = FederationServer(cluster_a_identity, lambda: local_state)
        manager = FederationManager(config, server_a, lambda: local_state)

        task = asyncio.create_task(manager.run())
        await asyncio.sleep(0.3)
        assert manager.is_running

        manager.stop()
        await asyncio.sleep(0.2)
        assert not manager.is_running

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestFederationSchemas:
    def test_cluster_identity(self):
        ci = ClusterIdentity(name="prod", api_endpoint="10.0.0.1:9090", region="us-east")
        assert ci.name == "prod"
        assert ci.region == "us-east"

    def test_federation_edge(self):
        edge = FederationEdge(
            source_cluster="a",
            target_cluster="b",
            node_mapping={"api": "api-remote"},
        )
        assert edge.source_cluster == "a"
        assert edge.node_mapping["api"] == "api-remote"

    def test_peer_state(self):
        ps = PeerState(
            cluster_name="prod",
            reachable=True,
            node_count=5,
            live_nodes=["a", "b"],
            health_summary={"a": "healthy"},
        )
        assert ps.node_count == 5

    def test_federation_config(self):
        config = FederationConfig(
            enabled=True,
            identity=ClusterIdentity(name="me", api_endpoint="localhost:9090"),
            peers=[ClusterIdentity(name="them", api_endpoint="remote:9090")],
            heartbeat_interval_s=10.0,
            failover_threshold=5,
        )
        assert config.enabled
        assert len(config.peers) == 1

    def test_custodian_actions_include_federation(self):
        assert CustodianAction.FEDERATED_FAILOVER == "federated_failover"
        assert CustodianAction.FEDERATED_RESTORE == "federated_restore"
