"""Tests for adapter control API."""

from __future__ import annotations

import asyncio
import json

import pytest

from baton.adapter import Adapter, BackendTarget
from baton.adapter_control import AdapterControlServer
from baton.schemas import NodeSpec, RoutingConfig, RoutingStrategy, RoutingTarget


async def _http_get(port: int, path: str) -> tuple[int, dict]:
    """Make a simple HTTP GET request and return (status_code, json_body)."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
    await writer.drain()

    # Read until EOF (Connection: close means server will close)
    chunks = []
    while True:
        chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
        if not chunk:
            break
        chunks.append(chunk)
    response = b"".join(chunks)
    writer.close()

    # Parse status code
    first_line = response.split(b"\r\n", 1)[0].decode()
    status = int(first_line.split(" ")[1])

    # Parse body (after \r\n\r\n)
    body = response.split(b"\r\n\r\n", 1)[1].decode()
    return status, json.loads(body)


class TestControlServer:
    async def test_start_and_stop(self):
        node = NodeSpec(name="ctrl-test", port=19001, management_port=29001)
        adapter = Adapter(node)
        ctrl = AdapterControlServer(adapter)
        await ctrl.start()
        assert ctrl.is_running
        await ctrl.stop()
        assert not ctrl.is_running

    async def test_health_no_backend(self):
        node = NodeSpec(name="ctrl-health", port=19002, management_port=29002)
        adapter = Adapter(node)
        ctrl = AdapterControlServer(adapter)
        await ctrl.start()
        try:
            status, body = await _http_get(29002, "/health")
            assert status == 200
            assert body["verdict"] == "unknown"
            assert "No backend" in body["detail"]
        finally:
            await ctrl.stop()

    async def test_health_with_backend(self):
        # Start an HTTP server that responds 200 to /health
        async def handle_health(reader, writer):
            try:
                await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5.0)
                writer.write(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Length: 2\r\n"
                    b"Connection: close\r\n\r\n"
                    b"OK"
                )
                await writer.drain()
            except Exception:
                pass
            finally:
                writer.close()

        backend = await asyncio.start_server(handle_health, "127.0.0.1", 19003)
        node = NodeSpec(name="ctrl-health2", port=19004, management_port=29004)
        adapter = Adapter(node)
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=19003))
        ctrl = AdapterControlServer(adapter)
        await ctrl.start()
        try:
            status, body = await _http_get(29004, "/health")
            assert status == 200
            assert body["verdict"] == "healthy"
            assert body["latency_ms"] > 0
        finally:
            await ctrl.stop()
            backend.close()
            await backend.wait_closed()

    async def test_metrics(self):
        node = NodeSpec(name="ctrl-metrics", port=19005, management_port=29005)
        adapter = Adapter(node)
        ctrl = AdapterControlServer(adapter)
        await ctrl.start()
        try:
            status, body = await _http_get(29005, "/metrics")
            assert status == 200
            assert body["requests_total"] == 0
            assert body["requests_failed"] == 0
            assert body["status_2xx"] == 0
            assert body["status_3xx"] == 0
            assert body["status_4xx"] == 0
            assert body["status_5xx"] == 0
            assert body["active_connections"] == 0
            assert body["latency_p50"] == 0.0
            assert body["latency_p95"] == 0.0
            assert body["latency_p99"] == 0.0
        finally:
            await ctrl.stop()

    async def test_status(self):
        node = NodeSpec(name="ctrl-status", port=19006, management_port=29006)
        adapter = Adapter(node)
        await adapter.start()
        ctrl = AdapterControlServer(adapter)
        await ctrl.start()
        try:
            status, body = await _http_get(29006, "/status")
            assert status == 200
            assert body["node"] == "ctrl-status"
            assert body["running"] is True
            assert body["backend"] is None
        finally:
            await ctrl.stop()
            await adapter.stop()

    async def test_status_with_backend(self):
        node = NodeSpec(name="ctrl-status2", port=19007, management_port=29007)
        adapter = Adapter(node)
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=9999))
        ctrl = AdapterControlServer(adapter)
        await ctrl.start()
        try:
            status, body = await _http_get(29007, "/status")
            assert status == 200
            assert body["backend"] == "127.0.0.1:9999"
        finally:
            await ctrl.stop()

    async def test_not_found(self):
        node = NodeSpec(name="ctrl-404", port=19008, management_port=29008)
        adapter = Adapter(node)
        ctrl = AdapterControlServer(adapter)
        await ctrl.start()
        try:
            status, body = await _http_get(29008, "/nonexistent")
            assert status == 404
            assert "error" in body
        finally:
            await ctrl.stop()

    async def test_routing_no_config(self):
        node = NodeSpec(name="ctrl-route-none", port=19009, management_port=29009)
        adapter = Adapter(node)
        ctrl = AdapterControlServer(adapter)
        await ctrl.start()
        try:
            status, body = await _http_get(29009, "/routing")
            assert status == 200
            assert body["strategy"] == "single"
            assert body["backend"] is None
        finally:
            await ctrl.stop()

    async def test_routing_with_config(self):
        node = NodeSpec(name="ctrl-route-cfg", port=19010, management_port=29010)
        adapter = Adapter(node)
        config = RoutingConfig(
            strategy=RoutingStrategy.WEIGHTED,
            targets=[
                RoutingTarget(name="a", port=8001, weight=80),
                RoutingTarget(name="b", port=8002, weight=20),
            ],
        )
        adapter.set_routing(config)
        ctrl = AdapterControlServer(adapter)
        await ctrl.start()
        try:
            status, body = await _http_get(29010, "/routing")
            assert status == 200
            assert body["strategy"] == "weighted"
            assert len(body["targets"]) == 2
            assert body["locked"] is False
        finally:
            await ctrl.stop()

    async def test_status_with_routing(self):
        node = NodeSpec(name="ctrl-st-route", port=19011, management_port=29011)
        adapter = Adapter(node)
        config = RoutingConfig(
            strategy=RoutingStrategy.WEIGHTED,
            targets=[
                RoutingTarget(name="a", port=8001, weight=80),
                RoutingTarget(name="b", port=8002, weight=20),
            ],
            locked=True,
        )
        adapter.set_routing(config)
        ctrl = AdapterControlServer(adapter)
        await ctrl.start()
        try:
            status, body = await _http_get(29011, "/status")
            assert status == 200
            assert body["routing_strategy"] == "weighted"
            assert body["routing_locked"] is True
        finally:
            await ctrl.stop()
