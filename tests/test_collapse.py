"""Tests for circuit collapse."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml

from baton.collapse import build_mock_server, compute_mock_backends
from baton.schemas import CircuitSpec, EdgeSpec, NodeSpec


@pytest.fixture
def circuit_with_contracts(tmp_path: Path) -> tuple[CircuitSpec, Path]:
    """Circuit with OpenAPI contracts on disk."""
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()

    # Write an OpenAPI spec for api node
    api_spec = {
        "openapi": "3.0.0",
        "paths": {
            "/users": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "example": [{"id": 1, "name": "alice"}]
                                }
                            }
                        }
                    }
                }
            }
        },
    }
    with open(specs_dir / "api.yaml", "w") as f:
        yaml.dump(api_spec, f)

    circuit = CircuitSpec(
        name="test",
        nodes=[
            NodeSpec(name="api", port=15001, contract="specs/api.yaml"),
            NodeSpec(name="service", port=15002),
            NodeSpec(name="db", port=15003, proxy_mode="tcp"),
        ],
        edges=[
            EdgeSpec(source="api", target="service"),
            EdgeSpec(source="service", target="db"),
        ],
    )
    return circuit, tmp_path


class TestBuildMockServer:
    async def test_all_mocked(self, circuit_with_contracts):
        circuit, project_dir = circuit_with_contracts
        mock = build_mock_server(circuit, live_nodes=set(), project_dir=project_dir)
        await mock.start()
        try:
            # api node mock should serve /users
            reader, writer = await asyncio.open_connection("127.0.0.1", 35001)
            writer.write(b"GET /users HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            chunks = []
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
            writer.close()

            assert b"200" in response
            body = json.loads(response.split(b"\r\n\r\n", 1)[1])
            assert body == [{"id": 1, "name": "alice"}]

            # service node mock should serve default health
            reader, writer = await asyncio.open_connection("127.0.0.1", 35002)
            writer.write(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            chunks = []
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
            writer.close()
            assert b"200" in response
        finally:
            await mock.stop()

    async def test_partial_mock(self, circuit_with_contracts):
        circuit, project_dir = circuit_with_contracts
        # Only mock service and db, keep api live
        mock = build_mock_server(
            circuit, live_nodes={"api"}, project_dir=project_dir
        )
        await mock.start()
        try:
            # service should be mocked
            reader, writer = await asyncio.open_connection("127.0.0.1", 35002)
            writer.write(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            chunks = []
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
            writer.close()
            assert b"200" in response

            # api port should NOT be listening (it's live, not mocked)
            with pytest.raises((ConnectionRefusedError, OSError)):
                await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", 35001), timeout=1.0
                )
        finally:
            await mock.stop()

    async def test_none_mocked(self, circuit_with_contracts):
        circuit, project_dir = circuit_with_contracts
        mock = build_mock_server(
            circuit,
            live_nodes={"api", "service", "db"},
            project_dir=project_dir,
        )
        # No servers should be started
        await mock.start()
        assert not mock.is_running
        await mock.stop()


class TestComputeMockBackends:
    def test_all_mocked(self, sample_circuit):
        backends = compute_mock_backends(sample_circuit, live_nodes=set())
        assert len(backends) == 3
        assert backends["api"].port == 29080
        assert backends["service"].port == 29081
        assert backends["db"].port == 29432

    def test_partial(self, sample_circuit):
        backends = compute_mock_backends(sample_circuit, live_nodes={"api"})
        assert "api" not in backends
        assert "service" in backends
        assert "db" in backends

    def test_none_mocked(self, sample_circuit):
        backends = compute_mock_backends(
            sample_circuit, live_nodes={"api", "service", "db"}
        )
        assert len(backends) == 0
