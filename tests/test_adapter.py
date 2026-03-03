"""Tests for the async reverse proxy adapter."""

from __future__ import annotations

import asyncio

import pytest

from baton.adapter import Adapter, BackendTarget
from baton.schemas import HealthVerdict, NodeSpec, ProxyMode


async def _start_echo_http_server(port: int) -> asyncio.Server:
    """Start a simple HTTP echo server on the given port."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5.0)
            # Read body if Content-Length present
            content_length = 0
            for line in data.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    content_length = int(line.split(b":", 1)[1].strip())
            body = b""
            if content_length > 0:
                body = await reader.readexactly(content_length)

            response_body = b"OK"
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Length: 2\r\n"
                b"Connection: close\r\n"
                b"\r\n"
                b"OK"
            )
            writer.write(response)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", port)
    return server


async def _start_echo_tcp_server(port: int) -> asyncio.Server:
    """Start a simple TCP echo server."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            if data:
                writer.write(data)
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", port)
    return server


class TestBackendTarget:
    def test_unconfigured(self):
        t = BackendTarget()
        assert not t.is_configured

    def test_configured(self):
        t = BackendTarget(host="127.0.0.1", port=8080)
        assert t.is_configured


class TestAdapterHTTP:
    async def test_start_and_stop(self):
        node = NodeSpec(name="test-http", port=18901)
        adapter = Adapter(node)
        await adapter.start()
        assert adapter.is_running
        await adapter.stop()
        assert not adapter.is_running

    async def test_503_when_no_backend(self):
        node = NodeSpec(name="test-no-backend", port=18902)
        adapter = Adapter(node)
        await adapter.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 18902)
            writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            assert b"503" in response
            writer.close()
        finally:
            await adapter.stop()

    async def test_proxy_to_backend(self):
        backend = await _start_echo_http_server(18903)
        node = NodeSpec(name="test-proxy", port=18904)
        adapter = Adapter(node)
        await adapter.start()
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=18903))

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 18904)
            writer.write(b"GET /hello HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            assert b"200 OK" in response
            assert b"OK" in response
            writer.close()

            assert adapter.metrics.requests_total == 1
            assert adapter.metrics.requests_failed == 0
        finally:
            await adapter.stop()
            backend.close()
            await backend.wait_closed()

    async def test_hot_swap(self):
        backend1 = await _start_echo_http_server(18905)
        backend2 = await _start_echo_http_server(18906)
        node = NodeSpec(name="test-swap", port=18907)
        adapter = Adapter(node)
        await adapter.start()

        try:
            # Point at backend1
            adapter.set_backend(BackendTarget(host="127.0.0.1", port=18905))
            reader, writer = await asyncio.open_connection("127.0.0.1", 18907)
            writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            resp = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            assert b"200" in resp
            writer.close()

            # Swap to backend2
            adapter.set_backend(BackendTarget(host="127.0.0.1", port=18906))
            reader, writer = await asyncio.open_connection("127.0.0.1", 18907)
            writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            resp = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            assert b"200" in resp
            writer.close()

            assert adapter.metrics.requests_total == 2
        finally:
            await adapter.stop()
            backend1.close()
            await backend1.wait_closed()
            backend2.close()
            await backend2.wait_closed()

    async def test_signal_recording(self):
        backend = await _start_echo_http_server(18908)
        node = NodeSpec(name="test-record", port=18909)
        adapter = Adapter(node, record_signals=True)
        await adapter.start()
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=18908))

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 18909)
            writer.write(b"GET /test HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            await asyncio.wait_for(reader.read(4096), timeout=5.0)
            writer.close()

            await asyncio.sleep(0.1)
            signals = adapter.signals
            assert len(signals) == 1
            assert signals[0].method == "GET"
            assert signals[0].path == "/test"
            assert signals[0].status_code == 200
        finally:
            await adapter.stop()
            backend.close()
            await backend.wait_closed()


class TestAdapterTCP:
    async def test_tcp_proxy(self):
        backend = await _start_echo_tcp_server(18910)
        node = NodeSpec(name="test-tcp", port=18911, proxy_mode="tcp")
        adapter = Adapter(node)
        await adapter.start()
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=18910))

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 18911)
            writer.write(b"hello world")
            await writer.drain()
            writer.write_eof()
            response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            assert response == b"hello world"
            writer.close()
        finally:
            await adapter.stop()
            backend.close()
            await backend.wait_closed()


class TestHealthCheck:
    async def test_healthy_backend(self):
        backend = await _start_echo_http_server(18912)
        node = NodeSpec(name="test-health", port=18913)
        adapter = Adapter(node)
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=18912))

        try:
            health = await adapter.health_check()
            assert health.verdict == HealthVerdict.HEALTHY
            assert health.latency_ms > 0
        finally:
            backend.close()
            await backend.wait_closed()

    async def test_no_backend(self):
        node = NodeSpec(name="test-nobackend", port=18914)
        adapter = Adapter(node)
        health = await adapter.health_check()
        assert health.verdict == HealthVerdict.UNKNOWN
        assert "No backend" in health.detail

    async def test_unhealthy_backend(self):
        node = NodeSpec(name="test-dead", port=18915)
        adapter = Adapter(node)
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=18999))
        health = await adapter.health_check()
        assert health.verdict == HealthVerdict.UNHEALTHY


class TestDrain:
    async def test_drain_no_connections(self):
        node = NodeSpec(name="test-drain", port=18916)
        adapter = Adapter(node)
        await adapter.start()
        try:
            await asyncio.wait_for(adapter.drain(timeout=1.0), timeout=2.0)
        finally:
            await adapter.stop()
