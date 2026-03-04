"""Tests for persistent telemetry."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from baton.adapter import Adapter, BackendTarget
from baton.dashboard import DashboardSnapshot, NodeSnapshot
from baton.schemas import (
    AdapterState,
    CircuitSpec,
    CircuitState,
    NodeSpec,
    NodeStatus,
)
from baton.telemetry import METRICS_FILE, TelemetryCollector


class TestTelemetryFlush:
    async def test_flush_writes_jsonl(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        (d / ".baton").mkdir()

        circuit = CircuitSpec(
            name="test",
            nodes=[NodeSpec(name="api", port=15010, proxy_mode="tcp")],
        )
        state = CircuitState(
            circuit_name="test",
            adapters={"api": AdapterState(node_name="api", status=NodeStatus.ACTIVE)},
        )
        adapter = Adapter(circuit.nodes[0])

        collector = TelemetryCollector(
            {"api": adapter}, state, circuit, d, flush_interval=0.1
        )
        await collector.flush_now()

        path = d / ".baton" / METRICS_FILE
        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert "timestamp" in data
        assert "api" in data["nodes"]

    async def test_multiple_flushes(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        (d / ".baton").mkdir()

        circuit = CircuitSpec(
            name="test",
            nodes=[NodeSpec(name="api", port=15011, proxy_mode="tcp")],
        )
        state = CircuitState(
            circuit_name="test",
            adapters={"api": AdapterState(node_name="api")},
        )
        adapter = Adapter(circuit.nodes[0])

        collector = TelemetryCollector(
            {"api": adapter}, state, circuit, d, flush_interval=0.1
        )
        await collector.flush_now()
        await collector.flush_now()

        path = d / ".baton" / METRICS_FILE
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2


class TestTelemetryLoadHistory:
    async def test_load_history(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        (d / ".baton").mkdir()

        circuit = CircuitSpec(
            name="test",
            nodes=[NodeSpec(name="api", port=15012, proxy_mode="tcp")],
        )
        state = CircuitState(
            circuit_name="test",
            adapters={"api": AdapterState(node_name="api")},
        )
        adapter = Adapter(circuit.nodes[0])
        collector = TelemetryCollector(
            {"api": adapter}, state, circuit, d
        )
        await collector.flush_now()
        await collector.flush_now()

        records = TelemetryCollector.load_history(d)
        assert len(records) == 2

    async def test_load_history_last_n(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        (d / ".baton").mkdir()

        circuit = CircuitSpec(
            name="test",
            nodes=[NodeSpec(name="api", port=15013, proxy_mode="tcp")],
        )
        state = CircuitState(
            circuit_name="test",
            adapters={"api": AdapterState(node_name="api")},
        )
        adapter = Adapter(circuit.nodes[0])
        collector = TelemetryCollector(
            {"api": adapter}, state, circuit, d
        )
        for _ in range(5):
            await collector.flush_now()

        records = TelemetryCollector.load_history(d, last_n=2)
        assert len(records) == 2

    async def test_load_history_by_node(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        (d / ".baton").mkdir()

        circuit = CircuitSpec(
            name="test",
            nodes=[
                NodeSpec(name="api", port=15014, proxy_mode="tcp"),
                NodeSpec(name="db", port=15015, proxy_mode="tcp"),
            ],
        )
        state = CircuitState(
            circuit_name="test",
            adapters={
                "api": AdapterState(node_name="api"),
                "db": AdapterState(node_name="db"),
            },
        )
        adapters = {
            "api": Adapter(circuit.nodes[0]),
            "db": Adapter(circuit.nodes[1]),
        }
        collector = TelemetryCollector(adapters, state, circuit, d)
        await collector.flush_now()

        records = TelemetryCollector.load_history(d, node="api")
        assert len(records) == 1
        assert "node" in records[0]

    def test_load_history_empty(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        records = TelemetryCollector.load_history(d)
        assert records == []


class TestPrometheusFormat:
    def test_format(self):
        snapshot = DashboardSnapshot(
            timestamp="2024-01-01T00:00:00Z",
            nodes={
                "api": NodeSnapshot(
                    name="api",
                    role="service",
                    requests_total=100,
                    requests_failed=2,
                    error_rate=0.02,
                    latency_p50=12.0,
                    latency_p95=45.0,
                ),
            },
        )
        output = TelemetryCollector.format_prometheus(snapshot)
        assert 'baton_requests_total{node="api",role="service"} 100' in output
        assert 'baton_requests_failed{node="api",role="service"} 2' in output
        assert 'baton_latency_p50_ms{node="api",role="service"} 12.0' in output


class TestTelemetryRunStop:
    async def test_run_and_stop(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True)
        (d / ".baton").mkdir()

        circuit = CircuitSpec(
            name="test",
            nodes=[NodeSpec(name="api", port=15016, proxy_mode="tcp")],
        )
        state = CircuitState(
            circuit_name="test",
            adapters={"api": AdapterState(node_name="api")},
        )
        adapter = Adapter(circuit.nodes[0])
        collector = TelemetryCollector(
            {"api": adapter}, state, circuit, d, flush_interval=0.05
        )

        task = asyncio.create_task(collector.run())
        await asyncio.sleep(0.01)
        assert collector.is_running

        await asyncio.sleep(0.15)
        collector.stop()
        await asyncio.wait_for(task, timeout=2.0)
        assert not collector.is_running

        # Should have written at least 2 snapshots
        records = TelemetryCollector.load_history(d)
        assert len(records) >= 2
