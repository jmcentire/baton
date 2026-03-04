"""Tests for baton.mcp_server."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from baton.schemas import (
    AdapterState,
    CircuitSpec,
    CircuitState,
    EdgeSpec,
    NodeSpec,
    NodeStatus,
    HealthVerdict,
    RoutingConfig,
    RoutingTarget,
    ServiceSlot,
)
from baton.state import save_state, save_circuit_spec
from baton.config import save_circuit


# We need to mock mcp import since it may not be installed in test env
@pytest.fixture(autouse=True)
def _patch_project_dir(tmp_path, monkeypatch):
    """Point MCP server at a temp project dir."""
    monkeypatch.setenv("BATON_PROJECT_DIR", str(tmp_path))


@pytest.fixture()
def sample_circuit(tmp_path) -> CircuitSpec:
    """Create a sample circuit in baton.yaml and .baton/circuit.json."""
    spec = CircuitSpec(
        name="test-circuit",
        version=1,
        nodes=[
            NodeSpec(name="api", port=3000, role="ingress"),
            NodeSpec(name="backend", port=3001),
            NodeSpec(name="db", port=3002, role="egress"),
        ],
        edges=[
            EdgeSpec(source="api", target="backend"),
            EdgeSpec(source="backend", target="db"),
        ],
    )
    save_circuit(spec, tmp_path)
    save_circuit_spec(spec, tmp_path)
    return spec


@pytest.fixture()
def sample_state(tmp_path, sample_circuit) -> CircuitState:
    """Create a sample circuit state in .baton/state.json."""
    state = CircuitState(
        circuit_name="test-circuit",
        collapse_level="partial",
        live_nodes=["api"],
        started_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:01:00Z",
        adapters={
            "api": AdapterState(
                node_name="api",
                status=NodeStatus.ACTIVE,
                last_health_verdict=HealthVerdict.HEALTHY,
                service=ServiceSlot(command="python server.py", is_mock=False, pid=1234),
            ),
            "backend": AdapterState(
                node_name="backend",
                status=NodeStatus.LISTENING,
                last_health_verdict=HealthVerdict.UNKNOWN,
            ),
            "db": AdapterState(
                node_name="db",
                status=NodeStatus.LISTENING,
                last_health_verdict=HealthVerdict.UNKNOWN,
            ),
        },
    )
    save_state(state, tmp_path)
    return state


@pytest.fixture()
def metrics_data(tmp_path):
    """Write sample metrics JSONL."""
    from baton.state import append_jsonl
    for i in range(5):
        append_jsonl(tmp_path, "metrics.jsonl", {
            "timestamp": f"2024-01-01T00:0{i}:00Z",
            "nodes": {
                "api": {
                    "name": "api",
                    "requests_total": 100 * (i + 1),
                    "requests_failed": i,
                    "error_rate": i / (100 * (i + 1)),
                    "latency_p50": 10.0 + i,
                    "latency_p95": 50.0 + i,
                },
                "backend": {
                    "name": "backend",
                    "requests_total": 80 * (i + 1),
                    "requests_failed": 0,
                },
            },
        })


@pytest.fixture()
def signals_data(tmp_path):
    """Write sample signals JSONL."""
    from baton.state import append_jsonl
    for i in range(10):
        append_jsonl(tmp_path, "signals.jsonl", {
            "node_name": "api" if i % 2 == 0 else "backend",
            "direction": "inbound",
            "method": "GET",
            "path": "/health" if i < 5 else "/api/users",
            "status_code": 200 if i < 8 else 500,
            "latency_ms": 10.0 + i,
        })


# ---------------------------------------------------------------------------
# Import the module under test (mcp may not be installed)
# ---------------------------------------------------------------------------

try:
    from baton.mcp_server import (
        resource_status,
        resource_topology,
        resource_node,
        resource_routes,
        resource_config,
        circuit_status,
        list_nodes,
        node_detail,
        show_routes,
        show_metrics,
        show_signals,
        signal_stats,
        show_topology,
        circuit_overview,
    )
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

pytestmark = pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")


# ---------------------------------------------------------------------------
# Resource tests
# ---------------------------------------------------------------------------


class TestResourceStatus:
    def test_no_state(self):
        result = resource_status()
        assert "No running circuit" in result

    def test_with_state(self, sample_state):
        result = resource_status()
        data = json.loads(result)
        assert data["circuit_name"] == "test-circuit"
        assert data["collapse_level"] == "partial"
        assert "api" in data["live_nodes"]
        assert data["adapters"]["api"]["status"] == "active"

    def test_adapter_service_info(self, sample_state):
        result = resource_status()
        data = json.loads(result)
        assert data["adapters"]["api"]["service_command"] == "python server.py"
        assert data["adapters"]["api"]["is_mock"] is False
        assert data["adapters"]["backend"]["is_mock"] is True


class TestResourceTopology:
    def test_no_topology(self):
        result = resource_topology()
        assert "No circuit topology" in result

    def test_with_topology(self, sample_circuit):
        result = resource_topology()
        data = json.loads(result)
        assert data["name"] == "test-circuit"
        assert len(data["nodes"]) == 3
        assert len(data["edges"]) == 2
        assert data["nodes"][0]["name"] == "api"
        assert data["nodes"][0]["role"] == "ingress"

    def test_edge_structure(self, sample_circuit):
        result = resource_topology()
        data = json.loads(result)
        edge = data["edges"][0]
        assert edge["source"] == "api"
        assert edge["target"] == "backend"


class TestResourceNode:
    def test_no_topology(self):
        result = resource_node("api")
        assert "No circuit topology" in result

    def test_node_not_found(self, sample_circuit):
        result = resource_node("nonexistent")
        assert "not found" in result

    def test_node_with_spec_only(self, sample_circuit):
        result = resource_node("api")
        data = json.loads(result)
        assert data["name"] == "api"
        assert data["port"] == 3000
        assert data["role"] == "ingress"
        assert data["neighbors"] == ["backend"]
        assert data["dependents"] == []

    def test_node_with_state(self, sample_state):
        result = resource_node("api")
        data = json.loads(result)
        assert data["state"]["status"] == "active"
        assert data["state"]["health"] == "healthy"
        assert data["state"]["service"]["command"] == "python server.py"

    def test_node_dependents(self, sample_circuit):
        result = resource_node("backend")
        data = json.loads(result)
        assert data["dependents"] == ["api"]
        assert data["neighbors"] == ["db"]


class TestResourceRoutes:
    def test_no_routes(self, sample_circuit):
        result = resource_routes()
        assert "No routing configurations" in result

    def test_routes_from_state(self, tmp_path, sample_circuit):
        state = CircuitState(
            circuit_name="test-circuit",
            adapters={
                "api": AdapterState(
                    node_name="api",
                    routing_config={
                        "strategy": "weighted",
                        "targets": [
                            {"name": "a", "host": "127.0.0.1", "port": 3100, "weight": 80},
                            {"name": "b", "host": "127.0.0.1", "port": 3101, "weight": 20},
                        ],
                    },
                ),
            },
        )
        save_state(state, tmp_path)
        result = resource_routes()
        data = json.loads(result)
        assert "api" in data
        assert data["api"]["strategy"] == "weighted"


class TestResourceConfig:
    def test_no_config(self):
        result = resource_config()
        assert "No baton.yaml" in result

    def test_with_config(self, sample_circuit):
        result = resource_config()
        data = json.loads(result)
        assert data["name"] == "test-circuit"
        assert len(data["nodes"]) == 3


# ---------------------------------------------------------------------------
# Tool tests
# ---------------------------------------------------------------------------


class TestToolCircuitStatus:
    def test_delegates_to_resource(self, sample_state):
        result = circuit_status()
        data = json.loads(result)
        assert data["circuit_name"] == "test-circuit"

    def test_with_project_dir(self, tmp_path, sample_state):
        result = circuit_status(project_dir=str(tmp_path))
        data = json.loads(result)
        assert data["circuit_name"] == "test-circuit"


class TestToolListNodes:
    def test_no_circuit(self):
        result = list_nodes()
        assert "No circuit topology" in result

    def test_with_state(self, sample_state):
        result = list_nodes()
        data = json.loads(result)
        assert len(data) == 3
        api = data[0]
        assert api["name"] == "api"
        assert api["status"] == "active"
        assert api["is_mock"] is False


class TestToolNodeDetail:
    def test_delegates(self, sample_state):
        result = node_detail("api")
        data = json.loads(result)
        assert data["name"] == "api"
        assert data["state"]["status"] == "active"


class TestToolShowRoutes:
    def test_no_node_filter(self, sample_circuit):
        result = show_routes()
        assert "No routing configurations" in result

    def test_node_not_found(self, sample_circuit, sample_state):
        result = show_routes(node="nonexistent")
        assert "No routing configuration" in result


class TestToolShowMetrics:
    def test_no_data(self):
        result = show_metrics()
        assert "No metrics data" in result

    def test_with_data(self, metrics_data):
        result = show_metrics(last_n=3)
        data = json.loads(result)
        assert len(data) == 3

    def test_filter_by_node(self, metrics_data):
        result = show_metrics(node="api", last_n=5)
        data = json.loads(result)
        assert len(data) == 5
        assert all("node" in r for r in data)

    def test_filter_nonexistent_node(self, metrics_data):
        result = show_metrics(node="nonexistent")
        assert "No metrics found" in result


class TestToolShowSignals:
    def test_no_data(self):
        result = show_signals()
        assert "No signal data" in result

    def test_with_data(self, signals_data):
        result = show_signals(last_n=5)
        data = json.loads(result)
        assert len(data) == 5

    def test_filter_by_node(self, signals_data):
        result = show_signals(node="api")
        data = json.loads(result)
        assert all(r["node_name"] == "api" for r in data)

    def test_filter_by_path(self, signals_data):
        result = show_signals(path="/health")
        data = json.loads(result)
        assert all("/health" in r["path"] for r in data)

    def test_no_match(self, signals_data):
        result = show_signals(node="nonexistent")
        assert "No signals match" in result


class TestToolSignalStats:
    def test_no_data(self):
        result = signal_stats()
        assert "No signal data" in result

    def test_with_data(self, signals_data):
        result = signal_stats()
        data = json.loads(result)
        assert "/health" in data
        assert "/api/users" in data
        assert data["/health"]["count"] == 5
        assert data["/api/users"]["count"] == 5

    def test_error_counting(self, signals_data):
        result = signal_stats()
        data = json.loads(result)
        # Signals 8 and 9 have status_code=500, path="/api/users"
        assert data["/api/users"]["error_count"] == 2

    def test_filter_by_node(self, signals_data):
        result = signal_stats(node="api")
        data = json.loads(result)
        # api gets signals at index 0,2,4,6,8
        total = sum(s["count"] for s in data.values())
        assert total == 5


class TestToolShowTopology:
    def test_delegates(self, sample_circuit):
        result = show_topology()
        data = json.loads(result)
        assert data["name"] == "test-circuit"


# ---------------------------------------------------------------------------
# Prompt tests
# ---------------------------------------------------------------------------


class TestPromptCircuitOverview:
    def test_no_data(self):
        result = circuit_overview()
        assert "No circuit topology" in result
        assert "No runtime state" in result

    def test_with_topology(self, sample_circuit):
        result = circuit_overview()
        assert "test-circuit" in result
        assert "api" in result
        assert "backend" in result
        assert "api -> backend" in result

    def test_with_state(self, sample_state):
        result = circuit_overview()
        assert "Runtime State" in result
        assert "partial" in result
        assert "active" in result


class TestMain:
    def test_main_exists(self):
        from baton.mcp_server import main
        assert callable(main)
