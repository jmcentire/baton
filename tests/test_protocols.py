"""Tests for baton.protocols package."""

from __future__ import annotations

import asyncio
import struct

import pytest

from baton.adapter import Adapter, BackendTarget
from baton.schemas import (
    HealthCheck,
    HealthVerdict,
    NodeSpec,
    ProxyMode,
)


# ---------------------------------------------------------------------------
# Protocol registry tests
# ---------------------------------------------------------------------------


class TestProtocolRegistry:
    def test_register_and_get(self):
        from baton.protocols import get_handler, register_handler

        class DummyHandler:
            pass

        register_handler("dummy", DummyHandler)
        assert get_handler("dummy") is DummyHandler

    def test_get_unknown(self):
        from baton.protocols import get_handler

        assert get_handler("nonexistent_protocol") is None

    def test_list_handlers(self):
        from baton.protocols import list_handlers

        # After importing the modules, built-in handlers should be registered
        import baton.protocols.http  # noqa: F401
        import baton.protocols.tcp  # noqa: F401
        import baton.protocols.protobuf  # noqa: F401
        import baton.protocols.soap  # noqa: F401

        handlers = list_handlers()
        assert "http" in handlers
        assert "tcp" in handlers
        assert "grpc" in handlers
        assert "protobuf" in handlers
        assert "soap" in handlers

    def test_connection_context(self):
        from baton.protocols import ConnectionContext

        node = NodeSpec(name="test", port=9000)
        ctx = ConnectionContext(node=node, adapter=None)
        assert ctx.node.name == "test"


# ---------------------------------------------------------------------------
# Protobuf handler tests
# ---------------------------------------------------------------------------


async def _start_length_prefix_echo(host: str, port: int):
    """Echo server that reads length-prefixed messages and echoes them back."""

    async def handler(reader, writer):
        try:
            while True:
                prefix = await reader.readexactly(4)
                msg_len = struct.unpack("!I", prefix)[0]
                payload = await reader.readexactly(msg_len)
                writer.write(prefix + payload)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handler, host, port)
    return server


class TestProtobufAdapter:
    async def test_protobuf_proxy(self):
        """Protobuf handler relays length-prefixed messages through the adapter."""
        echo = await _start_length_prefix_echo("127.0.0.1", 19100)
        node = NodeSpec(name="proto-svc", port=19101, proxy_mode=ProxyMode.PROTOBUF)
        adapter = Adapter(node)
        await adapter.start()
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=19100))

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 19101)
            # Send a length-prefixed message
            payload = b"hello protobuf"
            msg = struct.pack("!I", len(payload)) + payload
            writer.write(msg)
            await writer.drain()

            # Read response
            prefix = await asyncio.wait_for(reader.readexactly(4), timeout=5.0)
            resp_len = struct.unpack("!I", prefix)[0]
            resp = await asyncio.wait_for(reader.readexactly(resp_len), timeout=5.0)
            assert resp == payload

            writer.close()
            await asyncio.sleep(0.1)  # let handler finish
        finally:
            await adapter.stop()
            echo.close()

    async def test_protobuf_health_check(self):
        """Protobuf handler health check uses TCP connectivity."""
        echo = await _start_length_prefix_echo("127.0.0.1", 19102)
        node = NodeSpec(name="proto-hc", port=19103, proxy_mode=ProxyMode.PROTOBUF)
        adapter = Adapter(node)
        await adapter.start()
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=19102))

        try:
            hc = await adapter.health_check()
            assert hc.verdict == HealthVerdict.HEALTHY
        finally:
            await adapter.stop()
            echo.close()

    async def test_protobuf_no_backend(self):
        """Protobuf handler closes connection when no backend is configured."""
        node = NodeSpec(name="proto-none", port=19104, proxy_mode=ProxyMode.PROTOBUF)
        adapter = Adapter(node)
        await adapter.start()

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 19104)
            payload = b"test"
            msg = struct.pack("!I", len(payload)) + payload
            writer.write(msg)
            await writer.drain()

            # Should get disconnected
            try:
                data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
                assert data == b""
            except (ConnectionResetError, asyncio.TimeoutError):
                pass

            writer.close()
        finally:
            await adapter.stop()


# ---------------------------------------------------------------------------
# SOAP handler tests
# ---------------------------------------------------------------------------


async def _start_soap_backend(host: str, port: int, fault: bool = False):
    """Simple HTTP backend that returns a SOAP response."""

    async def handler(reader, writer):
        try:
            data = await reader.readuntil(b"\r\n\r\n")
            # Read body if content-length present
            cl = 0
            for line in data.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    cl = int(line.split(b":")[1].strip())
            if cl > 0:
                await reader.readexactly(cl)

            if fault:
                body = b'<soap:Envelope><soap:Body><soap:Fault><faultcode>Server</faultcode></soap:Fault></soap:Body></soap:Envelope>'
            else:
                body = b'<soap:Envelope><soap:Body><Response>OK</Response></soap:Body></soap:Envelope>'

            response = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: text/xml\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode() + body
            writer.write(response)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handler, host, port)
    return server


class TestSOAPAdapter:
    async def test_soap_proxy(self):
        """SOAP handler forwards HTTP SOAP requests."""
        backend = await _start_soap_backend("127.0.0.1", 19200)
        node = NodeSpec(name="soap-svc", port=19201, proxy_mode=ProxyMode.SOAP)
        adapter = Adapter(node)
        await adapter.start()
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=19200))

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 19201)
            soap_body = b'<soap:Envelope><soap:Body><GetData/></soap:Body></soap:Envelope>'
            request = (
                f"POST /service HTTP/1.1\r\n"
                f"Host: 127.0.0.1:19201\r\n"
                f"SOAPAction: \"GetData\"\r\n"
                f"Content-Type: text/xml\r\n"
                f"Content-Length: {len(soap_body)}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode() + soap_body
            writer.write(request)
            await writer.drain()

            response = await asyncio.wait_for(reader.read(8192), timeout=5.0)
            assert b"200 OK" in response
            assert b"<Response>OK</Response>" in response

            writer.close()
        finally:
            await adapter.stop()
            backend.close()

    async def test_soap_action_recorded(self):
        """SOAP handler records SOAPAction in signals."""
        backend = await _start_soap_backend("127.0.0.1", 19202)
        node = NodeSpec(name="soap-sig", port=19203, proxy_mode=ProxyMode.SOAP)
        adapter = Adapter(node, record_signals=True)
        await adapter.start()
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=19202))

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 19203)
            soap_body = b'<soap:Envelope><soap:Body><MyAction/></soap:Body></soap:Envelope>'
            request = (
                f"POST /ws HTTP/1.1\r\n"
                f"Host: 127.0.0.1:19203\r\n"
                f"SOAPAction: \"urn:MyAction\"\r\n"
                f"Content-Length: {len(soap_body)}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode() + soap_body
            writer.write(request)
            await writer.drain()

            await asyncio.wait_for(reader.read(8192), timeout=5.0)
            writer.close()

            await asyncio.sleep(0.1)
            signals = adapter.drain_signals()
            assert len(signals) >= 1
            assert signals[0].path == "urn:MyAction"
        finally:
            await adapter.stop()
            backend.close()

    async def test_soap_health_check_fault_detection(self):
        """SOAP health check detects SOAP faults and returns DEGRADED."""
        backend = await _start_soap_backend("127.0.0.1", 19204, fault=True)
        node = NodeSpec(name="soap-hc", port=19205, proxy_mode=ProxyMode.SOAP)
        adapter = Adapter(node)
        await adapter.start()
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=19204))

        try:
            hc = await adapter.health_check()
            assert hc.verdict == HealthVerdict.DEGRADED
            assert "SOAP fault" in hc.detail
        finally:
            await adapter.stop()
            backend.close()

    async def test_soap_no_backend(self):
        """SOAP handler returns 503 when no backend."""
        node = NodeSpec(name="soap-none", port=19206, proxy_mode=ProxyMode.SOAP)
        adapter = Adapter(node)
        await adapter.start()

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 19206)
            request = (
                b"POST /ws HTTP/1.1\r\n"
                b"Host: 127.0.0.1:19206\r\n"
                b"Content-Length: 0\r\n"
                b"Connection: close\r\n\r\n"
            )
            writer.write(request)
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            assert b"503" in response

            writer.close()
        finally:
            await adapter.stop()
