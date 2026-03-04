"""Tests for cross-node signal aggregation."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from baton.adapter import Adapter, BackendTarget
from baton.schemas import NodeSpec, SignalRecord
from baton.signals import SIGNALS_FILE, SignalAggregator


async def _start_echo_http_server(port: int) -> asyncio.Server:
    async def handle(reader, writer):
        try:
            await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5.0)
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Length: 2\r\n"
                b"Connection: close\r\n\r\nOK"
            )
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    return await asyncio.start_server(handle, "127.0.0.1", port)


class TestDrainSignals:
    async def test_drain_clears_buffer(self):
        backend = await _start_echo_http_server(15050)
        node = NodeSpec(name="test-drain-sig", port=15051)
        adapter = Adapter(node, record_signals=True)
        await adapter.start()
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=15050))

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 15051)
            writer.write(b"GET /test HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            await asyncio.wait_for(reader.read(4096), timeout=5.0)
            writer.close()
            await asyncio.sleep(0.1)

            drained = adapter.drain_signals()
            assert len(drained) == 1
            assert drained[0].path == "/test"

            # Buffer should be empty now
            assert len(adapter.signals) == 0
        finally:
            await adapter.stop()
            backend.close()
            await backend.wait_closed()


class TestSignalAggregator:
    async def test_collect_from_adapters(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        (d / ".baton").mkdir()

        backend = await _start_echo_http_server(15052)
        node = NodeSpec(name="api", port=15053)
        adapter = Adapter(node, record_signals=True)
        await adapter.start()
        adapter.set_backend(BackendTarget(host="127.0.0.1", port=15052))

        try:
            # Make a request
            reader, writer = await asyncio.open_connection("127.0.0.1", 15053)
            writer.write(b"GET /hello HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            await asyncio.wait_for(reader.read(4096), timeout=5.0)
            writer.close()
            await asyncio.sleep(0.1)

            aggregator = SignalAggregator({"api": adapter}, d)
            aggregator._collect()

            assert aggregator.buffer_size == 1
            # Adapter buffer should be drained
            assert len(adapter.signals) == 0
            # JSONL should have a record
            path = d / ".baton" / SIGNALS_FILE
            assert path.exists()
        finally:
            await adapter.stop()
            backend.close()
            await backend.wait_closed()

    async def test_query_by_node(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        (d / ".baton").mkdir()

        node_a = NodeSpec(name="api", port=15054)
        node_b = NodeSpec(name="db", port=15055, proxy_mode="tcp")
        adapter_a = Adapter(node_a, record_signals=True)
        adapter_b = Adapter(node_b, record_signals=True)

        # Manually add signals
        adapter_a._signals.append(
            SignalRecord(node_name="api", direction="inbound", method="GET", path="/a")
        )
        adapter_b._signals.append(
            SignalRecord(node_name="db", direction="inbound", method="GET", path="/b")
        )

        aggregator = SignalAggregator(
            {"api": adapter_a, "db": adapter_b}, d
        )
        aggregator._collect()

        results = aggregator.query(node="api")
        assert len(results) == 1
        assert results[0].path == "/a"

    async def test_query_by_path(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        (d / ".baton").mkdir()

        node = NodeSpec(name="api", port=15056)
        adapter = Adapter(node, record_signals=True)
        adapter._signals.extend([
            SignalRecord(node_name="api", direction="inbound", method="GET", path="/users"),
            SignalRecord(node_name="api", direction="inbound", method="GET", path="/orders"),
            SignalRecord(node_name="api", direction="inbound", method="GET", path="/users/1"),
        ])

        aggregator = SignalAggregator({"api": adapter}, d)
        aggregator._collect()

        results = aggregator.query(path="/users")
        assert len(results) == 2  # /users and /users/1


class TestPathStats:
    async def test_path_stats(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        (d / ".baton").mkdir()

        node = NodeSpec(name="api", port=15057)
        adapter = Adapter(node, record_signals=True)
        adapter._signals.extend([
            SignalRecord(
                node_name="api", direction="inbound", method="GET",
                path="/users", status_code=200, latency_ms=10.0,
            ),
            SignalRecord(
                node_name="api", direction="inbound", method="GET",
                path="/users", status_code=200, latency_ms=20.0,
            ),
            SignalRecord(
                node_name="api", direction="inbound", method="GET",
                path="/users", status_code=500, latency_ms=100.0,
            ),
            SignalRecord(
                node_name="api", direction="inbound", method="POST",
                path="/orders", status_code=201, latency_ms=50.0,
            ),
        ])

        aggregator = SignalAggregator({"api": adapter}, d)
        aggregator._collect()

        stats = aggregator.path_stats()
        assert "/users" in stats
        assert "/orders" in stats
        assert stats["/users"].count == 3
        assert stats["/users"].error_count == 1
        assert abs(stats["/users"].error_rate - 1 / 3) < 0.01
        assert abs(stats["/users"].avg_latency_ms - (10 + 20 + 100) / 3) < 0.01
        assert stats["/orders"].count == 1


class TestLoadHistory:
    async def test_load_history(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        (d / ".baton").mkdir()

        node = NodeSpec(name="api", port=15058)
        adapter = Adapter(node, record_signals=True)
        adapter._signals.append(
            SignalRecord(node_name="api", direction="inbound", method="GET", path="/test")
        )

        aggregator = SignalAggregator({"api": adapter}, d)
        aggregator._collect()

        records = SignalAggregator.load_history(d)
        assert len(records) == 1
        assert records[0]["path"] == "/test"

    async def test_load_history_by_node(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        (d / ".baton").mkdir()

        node_a = NodeSpec(name="api", port=15059)
        node_b = NodeSpec(name="db", port=15060, proxy_mode="tcp")
        adapter_a = Adapter(node_a, record_signals=True)
        adapter_b = Adapter(node_b, record_signals=True)
        adapter_a._signals.append(
            SignalRecord(node_name="api", direction="inbound", method="GET", path="/a")
        )
        adapter_b._signals.append(
            SignalRecord(node_name="db", direction="inbound", method="GET", path="/b")
        )

        aggregator = SignalAggregator(
            {"api": adapter_a, "db": adapter_b}, d
        )
        aggregator._collect()

        records = SignalAggregator.load_history(d, node="api")
        assert len(records) == 1
        assert records[0]["node_name"] == "api"

    def test_load_history_empty(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        records = SignalAggregator.load_history(d)
        assert records == []


class TestBufferCap:
    async def test_buffer_respects_max(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        (d / ".baton").mkdir()

        node = NodeSpec(name="api", port=15061)
        adapter = Adapter(node, record_signals=True)
        for i in range(20):
            adapter._signals.append(
                SignalRecord(
                    node_name="api", direction="inbound",
                    method="GET", path=f"/p{i}",
                )
            )

        aggregator = SignalAggregator({"api": adapter}, d, buffer_size=10)
        aggregator._collect()

        assert aggregator.buffer_size == 10
