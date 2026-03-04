"""Tests for aggregated dashboard."""

from __future__ import annotations

import asyncio

import pytest

from baton.adapter import Adapter, BackendTarget
from baton.dashboard import DashboardSnapshot, NodeSnapshot, collect, format_table
from baton.schemas import (
    AdapterState,
    CircuitSpec,
    CircuitState,
    EdgeSpec,
    NodeSpec,
    NodeStatus,
)


class TestCollect:
    async def test_collect_basic(self):
        """Collect metrics from adapters into a snapshot."""
        backend = await asyncio.start_server(
            lambda r, w: w.close(), "127.0.0.1", 15001
        )
        circuit = CircuitSpec(
            name="test",
            nodes=[
                NodeSpec(name="api", port=15002, proxy_mode="tcp"),
                NodeSpec(name="db", port=15003, proxy_mode="tcp"),
            ],
            edges=[EdgeSpec(source="api", target="db")],
        )
        state = CircuitState(
            circuit_name="test",
            adapters={
                "api": AdapterState(node_name="api", status=NodeStatus.ACTIVE),
                "db": AdapterState(node_name="db", status=NodeStatus.LISTENING),
            },
        )
        adapter_api = Adapter(circuit.nodes[0])
        adapter_api.set_backend(BackendTarget(host="127.0.0.1", port=15001))
        adapter_db = Adapter(circuit.nodes[1])

        adapters = {"api": adapter_api, "db": adapter_db}
        try:
            snapshot = await collect(adapters, state, circuit)
            assert "api" in snapshot.nodes
            assert "db" in snapshot.nodes
            assert snapshot.nodes["api"].status == "active"
            assert snapshot.nodes["db"].status == "listening"
            assert snapshot.nodes["api"].health == "healthy"
            assert snapshot.nodes["db"].health == "unknown"
            assert snapshot.timestamp
        finally:
            backend.close()
            await backend.wait_closed()

    async def test_collect_with_routing(self):
        """Collect includes routing info."""
        from baton.schemas import RoutingConfig, RoutingStrategy, RoutingTarget

        circuit = CircuitSpec(
            name="test",
            nodes=[NodeSpec(name="api", port=15004, proxy_mode="tcp")],
        )
        state = CircuitState(
            circuit_name="test",
            adapters={"api": AdapterState(node_name="api", status=NodeStatus.ACTIVE)},
        )
        adapter = Adapter(circuit.nodes[0])
        config = RoutingConfig(
            strategy=RoutingStrategy.WEIGHTED,
            targets=[
                RoutingTarget(name="a", port=8001, weight=80),
                RoutingTarget(name="b", port=8002, weight=20),
            ],
            locked=True,
        )
        adapter.set_routing(config)

        snapshot = await collect({"api": adapter}, state, circuit)
        assert snapshot.nodes["api"].routing_strategy == "weighted"
        assert snapshot.nodes["api"].routing_locked is True


class TestFormatTable:
    def test_format_empty(self):
        snapshot = DashboardSnapshot()
        assert "No nodes" in format_table(snapshot)

    def test_format_with_nodes(self):
        snapshot = DashboardSnapshot(
            timestamp="2024-01-01T00:00:00Z",
            nodes={
                "api": NodeSnapshot(
                    name="api",
                    role="service",
                    status="active",
                    health="healthy",
                    requests_total=100,
                    requests_failed=2,
                    error_rate=0.02,
                    latency_p50=12.0,
                    latency_p95=45.0,
                    routing_strategy="weighted",
                    routing_locked=True,
                ),
            },
        )
        output = format_table(snapshot)
        assert "api" in output
        assert "active" in output
        assert "healthy" in output
        assert "weighted (locked)" in output
