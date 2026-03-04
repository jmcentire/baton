"""End-to-end integration test for Baton.

Tests the full circuit lifecycle: init, up, request forwarding,
metrics, signals, telemetry, and JSONL persistence.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest

from baton.adapter import Adapter, BackendTarget
from baton.cli import main as cli_main
from baton.collapse import compute_mock_backends
from baton.config import load_circuit
from baton.dashboard import collect
from baton.lifecycle import LifecycleManager
from baton.schemas import NodeRole
from baton.signals import SignalAggregator
from baton.state import load_state, read_jsonl
from baton.telemetry import TelemetryCollector


async def _start_echo_http_server(port: int) -> asyncio.Server:
    """Start a simple HTTP echo server on the given port."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5.0)
            content_length = 0
            for line in data.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    content_length = int(line.split(b":", 1)[1].strip())
            if content_length > 0:
                await reader.readexactly(content_length)

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


async def _send_request(port: int, path: str = "/test/") -> int:
    """Send a GET request to a port, return status code."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(
            f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
        )
        await writer.drain()
        response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
        # Parse status code from first line
        first_line = response.split(b"\r\n")[0].decode()
        return int(first_line.split()[1])
    finally:
        writer.close()


@pytest.mark.asyncio
class TestE2ECircuit:
    """End-to-end test of a 3-node circuit with roles."""

    async def test_full_circuit_lifecycle(self, tmp_path: Path):
        """Test the full lifecycle: init -> up -> requests -> metrics -> signals -> teardown."""
        project_dir = tmp_path / "e2e"
        project_dir.mkdir()

        # -- Step 1: Init 3-node circuit via CLI --
        # gateway[ingress]:19100 -> api[service]:19101 -> stripe[egress]:19102
        assert cli_main(["init", str(project_dir), "--name", "e2e"]) == 0
        assert cli_main(["node", "add", "gateway", "--port", "19100", "--role", "ingress", "--dir", str(project_dir)]) == 0
        assert cli_main(["node", "add", "api", "--port", "19101", "--dir", str(project_dir)]) == 0
        assert cli_main(["node", "add", "stripe", "--port", "19102", "--role", "egress", "--dir", str(project_dir)]) == 0
        assert cli_main(["edge", "add", "gateway", "api", "--dir", str(project_dir)]) == 0
        assert cli_main(["edge", "add", "api", "stripe", "--dir", str(project_dir)]) == 0

        circuit = load_circuit(project_dir)
        assert len(circuit.nodes) == 3
        assert len(circuit.edges) == 2

        # -- Step 2: Boot via LifecycleManager --
        mgr = LifecycleManager(project_dir)
        state = await mgr.up(mock=True)
        assert len(state.adapters) == 3

        # -- Step 3: Verify compute_mock_backends -- stripe (egress) must be mocked --
        backends = compute_mock_backends(circuit, live_nodes=set())
        assert "stripe" in backends
        assert "gateway" in backends
        assert "api" in backends

        # -- Step 4: Point adapters at echo HTTP backends --
        echo_gateway = await _start_echo_http_server(19110)
        echo_api = await _start_echo_http_server(19111)

        adapters = mgr.adapters
        adapters["gateway"].set_backend(BackendTarget(host="127.0.0.1", port=19110))
        adapters["api"].set_backend(BackendTarget(host="127.0.0.1", port=19111))
        # stripe egress: point at a mock echo too so it doesn't 503
        echo_stripe = await _start_echo_http_server(19112)
        adapters["stripe"].set_backend(BackendTarget(host="127.0.0.1", port=19112))

        # -- Step 5: Start SignalAggregator + TelemetryCollector as background tasks --
        sig_agg = SignalAggregator(
            adapters, project_dir, flush_interval=0.5
        )
        telemetry = TelemetryCollector(
            adapters, state, circuit, project_dir, flush_interval=0.5
        )
        sig_task = asyncio.create_task(sig_agg.run())
        tel_task = asyncio.create_task(telemetry.run())

        # -- Step 6: Send requests --
        # 5 through gateway, 3 through api
        for _ in range(5):
            status = await _send_request(19100, "/test/gateway")
            assert status == 200

        for _ in range(3):
            status = await _send_request(19101, "/test/api")
            assert status == 200

        # Give collectors time to drain
        await asyncio.sleep(1.5)

        # -- Step 7: Verify adapter metrics --
        gw_metrics = adapters["gateway"].metrics
        assert gw_metrics.requests_total == 5
        assert gw_metrics.status_2xx == 5
        assert gw_metrics.p50() > 0

        api_metrics = adapters["api"].metrics
        assert api_metrics.requests_total == 3
        assert api_metrics.status_2xx == 3

        # -- Step 8: Verify dashboard collect() snapshot --
        snapshot = await collect(adapters, state, circuit)
        assert len(snapshot.nodes) == 3
        assert snapshot.nodes["gateway"].role == str(NodeRole.INGRESS)
        assert snapshot.nodes["stripe"].role == str(NodeRole.EGRESS)
        assert snapshot.nodes["api"].role == str(NodeRole.SERVICE)
        assert snapshot.nodes["gateway"].requests_total == 5
        assert snapshot.nodes["api"].requests_total == 3

        # -- Step 9: Verify SignalAggregator query --
        gw_signals = sig_agg.query(node="gateway")
        api_signals = sig_agg.query(node="api")
        assert len(gw_signals) == 5
        assert len(api_signals) == 3

        # -- Step 10: Verify path_stats --
        stats = sig_agg.path_stats()
        assert any("/test/" in p for p in stats)

        # -- Step 11: Verify JSONL files written --
        metrics_records = read_jsonl(project_dir, "metrics.jsonl")
        assert len(metrics_records) >= 1

        signals_records = read_jsonl(project_dir, "signals.jsonl")
        assert len(signals_records) >= 8  # 5 + 3

        # -- Step 12: Clean up --
        sig_agg.stop()
        telemetry.stop()
        await sig_task
        await tel_task

        echo_gateway.close()
        echo_api.close()
        echo_stripe.close()
        await echo_gateway.wait_closed()
        await echo_api.wait_closed()
        await echo_stripe.wait_closed()

        await mgr.down()
