"""Tests for the dashboard HTTP server."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from baton.adapter import Adapter
from baton.dashboard_server import DashboardServer
from baton.schemas import (
    AdapterState,
    CircuitSpec,
    CircuitState,
    EdgeSpec,
    NodeSpec,
    NodeStatus,
    SignalRecord,
)
from baton.signals import SignalAggregator


def _make_circuit() -> tuple[CircuitSpec, CircuitState, dict[str, Adapter]]:
    circuit = CircuitSpec(
        name="dash-test",
        nodes=[
            NodeSpec(name="api", port=17401, proxy_mode="http"),
            NodeSpec(name="svc", port=17402, proxy_mode="http"),
        ],
        edges=[EdgeSpec(source="api", target="svc")],
    )
    state = CircuitState(
        circuit_name="dash-test",
        adapters={
            "api": AdapterState(node_name="api", status=NodeStatus.ACTIVE),
            "svc": AdapterState(node_name="svc", status=NodeStatus.ACTIVE),
        },
    )
    adapters = {
        "api": Adapter(circuit.nodes[0]),
        "svc": Adapter(circuit.nodes[1]),
    }
    return circuit, state, adapters


async def _http_get(port: int, path: str) -> tuple[int, bytes]:
    """Make a simple HTTP GET request and return (status_code, raw_body)."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode())
    await writer.drain()

    chunks = []
    while True:
        chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
        if not chunk:
            break
        chunks.append(chunk)
    response = b"".join(chunks)
    writer.close()

    first_line = response.split(b"\r\n", 1)[0].decode()
    status = int(first_line.split(" ")[1])
    body = response.split(b"\r\n\r\n", 1)[1]
    return status, body


class TestDashboardServerLifecycle:
    async def test_start_and_stop(self):
        circuit, state, adapters = _make_circuit()
        server = DashboardServer(adapters, state, circuit, port=17500)
        await server.start()
        assert server.is_running
        await server.stop()
        assert not server.is_running


class TestDashboardAPI:
    async def test_snapshot(self):
        circuit, state, adapters = _make_circuit()
        server = DashboardServer(adapters, state, circuit, port=17501)
        await server.start()
        try:
            status, body = await _http_get(17501, "/api/snapshot")
            assert status == 200
            data = json.loads(body)
            assert "timestamp" in data
            assert "api" in data["nodes"]
            assert "svc" in data["nodes"]
        finally:
            await server.stop()

    async def test_topology(self):
        circuit, state, adapters = _make_circuit()
        server = DashboardServer(adapters, state, circuit, port=17502)
        await server.start()
        try:
            status, body = await _http_get(17502, "/api/topology")
            assert status == 200
            data = json.loads(body)
            assert len(data["nodes"]) == 2
            assert len(data["edges"]) == 1
            assert data["edges"][0]["source"] == "api"
            assert data["edges"][0]["target"] == "svc"
        finally:
            await server.stop()

    async def test_signals_no_aggregator(self):
        circuit, state, adapters = _make_circuit()
        server = DashboardServer(adapters, state, circuit, port=17503)
        await server.start()
        try:
            status, body = await _http_get(17503, "/api/signals")
            assert status == 200
            data = json.loads(body)
            assert data == []
        finally:
            await server.stop()

    async def test_signals_with_aggregator(self, tmp_path: Path):
        circuit, state, adapters = _make_circuit()
        aggregator = SignalAggregator(adapters, tmp_path)
        # Manually inject a signal into the buffer
        aggregator._buffer.append(SignalRecord(
            node_name="api", direction="inbound", method="GET", path="/health",
            status_code=200, latency_ms=5.0,
        ))
        server = DashboardServer(
            adapters, state, circuit,
            signal_aggregator=aggregator, port=17504,
        )
        await server.start()
        try:
            status, body = await _http_get(17504, "/api/signals")
            assert status == 200
            data = json.loads(body)
            assert len(data) == 1
            assert data[0]["node_name"] == "api"
        finally:
            await server.stop()

    async def test_signal_stats_no_aggregator(self):
        circuit, state, adapters = _make_circuit()
        server = DashboardServer(adapters, state, circuit, port=17505)
        await server.start()
        try:
            status, body = await _http_get(17505, "/api/signals/stats")
            assert status == 200
            data = json.loads(body)
            assert data == {}
        finally:
            await server.stop()

    async def test_not_found(self):
        circuit, state, adapters = _make_circuit()
        server = DashboardServer(adapters, state, circuit, port=17506)
        await server.start()
        try:
            status, body = await _http_get(17506, "/api/unknown")
            # Falls through to static handler which returns 404
            assert status == 404
        finally:
            await server.stop()

    async def test_post_not_found(self):
        circuit, state, adapters = _make_circuit()
        server = DashboardServer(adapters, state, circuit, port=17507)
        await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 17507)
            writer.write(b"POST /api/snapshot HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            chunks = []
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
            writer.close()
            assert b"404" in response
        finally:
            await server.stop()


class TestDashboardStatic:
    async def test_static_file(self, tmp_path: Path):
        static_dir = tmp_path / "static"
        static_dir.mkdir()
        (static_dir / "index.html").write_text("<html>OK</html>")

        circuit, state, adapters = _make_circuit()
        server = DashboardServer(
            adapters, state, circuit,
            static_dir=static_dir, port=17510,
        )
        await server.start()
        try:
            status, body = await _http_get(17510, "/")
            assert status == 200
            assert b"<html>OK</html>" in body
        finally:
            await server.stop()

    async def test_static_no_dir(self):
        circuit, state, adapters = _make_circuit()
        server = DashboardServer(adapters, state, circuit, port=17511)
        await server.start()
        try:
            status, body = await _http_get(17511, "/somefile.html")
            assert status == 404
        finally:
            await server.stop()

    async def test_static_traversal_blocked(self, tmp_path: Path):
        static_dir = tmp_path / "static"
        static_dir.mkdir()
        (static_dir / "index.html").write_text("ok")
        # Write a file outside the static dir
        (tmp_path / "secret.txt").write_text("secret data")

        circuit, state, adapters = _make_circuit()
        server = DashboardServer(
            adapters, state, circuit,
            static_dir=static_dir, port=17512,
        )
        await server.start()
        try:
            status, body = await _http_get(17512, "/../secret.txt")
            assert status == 403
        finally:
            await server.stop()

    async def test_static_missing_file(self, tmp_path: Path):
        static_dir = tmp_path / "static"
        static_dir.mkdir()

        circuit, state, adapters = _make_circuit()
        server = DashboardServer(
            adapters, state, circuit,
            static_dir=static_dir, port=17513,
        )
        await server.start()
        try:
            status, body = await _http_get(17513, "/nonexistent.html")
            assert status == 404
        finally:
            await server.stop()
