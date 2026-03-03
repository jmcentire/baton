"""Tests for adapter control API."""

from __future__ import annotations

import asyncio
import json

import pytest

from baton.adapter import Adapter, BackendTarget
from baton.adapter_control import AdapterControlServer
from baton.schemas import NodeSpec


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
        # Start a simple TCP server as backend
        backend = await asyncio.start_server(
            lambda r, w: w.close(), "127.0.0.1", 19003
        )
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
