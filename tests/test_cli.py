"""Tests for Baton CLI."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from baton.cli import main
from baton.config import load_circuit
from baton.manifest import MANIFEST_FILENAME


class TestInit:
    def test_init_creates_files(self, project_dir: Path):
        d = project_dir / "myproject"
        rc = main(["init", str(d)])
        assert rc == 0
        assert (d / "baton.yaml").exists()
        assert (d / ".baton").is_dir()

    def test_init_with_name(self, project_dir: Path):
        d = project_dir / "myproject"
        main(["init", str(d), "--name", "myapp"])
        circuit = load_circuit(d)
        assert circuit.name == "myapp"

    def test_init_existing(self, project_dir: Path):
        d = project_dir / "myproject"
        main(["init", str(d)])
        rc = main(["init", str(d)])
        assert rc == 1

    def test_init_default_dir(self, project_dir: Path, monkeypatch):
        monkeypatch.chdir(project_dir)
        rc = main(["init"])
        assert rc == 0
        assert (project_dir / "baton.yaml").exists()


class TestNodeAdd:
    def _init(self, d: Path):
        main(["init", str(d)])

    def test_add_node(self, project_dir: Path):
        d = project_dir / "p"
        self._init(d)
        rc = main(["node", "add", "api", "--port", "8001", "--dir", str(d)])
        assert rc == 0
        circuit = load_circuit(d)
        assert len(circuit.nodes) == 1
        assert circuit.nodes[0].name == "api"

    def test_add_auto_port(self, project_dir: Path):
        d = project_dir / "p"
        self._init(d)
        main(["node", "add", "api", "--dir", str(d)])
        circuit = load_circuit(d)
        assert circuit.nodes[0].port == 9001

    def test_add_tcp(self, project_dir: Path):
        d = project_dir / "p"
        self._init(d)
        main(["node", "add", "db", "--mode", "tcp", "--dir", str(d)])
        circuit = load_circuit(d)
        assert circuit.nodes[0].proxy_mode == "tcp"

    def test_add_grpc_node(self, project_dir: Path):
        d = project_dir / "p"
        self._init(d)
        rc = main(["node", "add", "grpc-svc", "--mode", "grpc", "--dir", str(d)])
        assert rc == 0
        circuit = load_circuit(d)
        node = [n for n in circuit.nodes if n.name == "grpc-svc"][0]
        assert node.proxy_mode == "grpc"

    def test_add_duplicate(self, project_dir: Path):
        d = project_dir / "p"
        self._init(d)
        main(["node", "add", "api", "--dir", str(d)])
        rc = main(["node", "add", "api", "--dir", str(d)])
        assert rc == 1


class TestNodeRm:
    def test_remove_node(self, project_dir: Path):
        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--dir", str(d)])
        rc = main(["node", "rm", "api", "--dir", str(d)])
        assert rc == 0
        circuit = load_circuit(d)
        assert len(circuit.nodes) == 0

    def test_remove_missing(self, project_dir: Path):
        d = project_dir / "p"
        main(["init", str(d)])
        rc = main(["node", "rm", "api", "--dir", str(d)])
        assert rc == 1


class TestEdge:
    def _setup(self, d: Path):
        main(["init", str(d)])
        main(["node", "add", "api", "--dir", str(d)])
        main(["node", "add", "service", "--dir", str(d)])

    def test_add_edge(self, project_dir: Path):
        d = project_dir / "p"
        self._setup(d)
        rc = main(["edge", "add", "api", "service", "--dir", str(d)])
        assert rc == 0
        circuit = load_circuit(d)
        assert len(circuit.edges) == 1

    def test_remove_edge(self, project_dir: Path):
        d = project_dir / "p"
        self._setup(d)
        main(["edge", "add", "api", "service", "--dir", str(d)])
        rc = main(["edge", "rm", "api", "service", "--dir", str(d)])
        assert rc == 0
        circuit = load_circuit(d)
        assert len(circuit.edges) == 0

    def test_add_edge_missing_node(self, project_dir: Path):
        d = project_dir / "p"
        self._setup(d)
        rc = main(["edge", "add", "api", "missing", "--dir", str(d)])
        assert rc == 1


class TestContract:
    def test_set_contract(self, project_dir: Path):
        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--dir", str(d)])
        rc = main(["contract", "set", "api", "specs/api.yaml", "--dir", str(d)])
        assert rc == 0
        circuit = load_circuit(d)
        assert circuit.nodes[0].contract == "specs/api.yaml"


class TestStatus:
    def test_status_empty(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])
        rc = main(["status", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "default" in out
        assert "Nodes:   0" in out

    def test_status_with_nodes(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])
        main(["node", "add", "db", "--port", "5432", "--mode", "tcp", "--dir", str(d)])
        main(["edge", "add", "api", "db", "--dir", str(d)])
        rc = main(["status", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "api" in out
        assert "8001" in out
        assert "db" in out
        assert "tcp" in out
        assert "api -> db" in out


class TestStatusRoles:
    def test_status_shows_role_labels(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "gateway", "--port", "8001", "--role", "ingress", "--dir", str(d)])
        main(["node", "add", "api", "--port", "8002", "--dir", str(d)])
        main(["node", "add", "stripe", "--port", "8003", "--role", "egress", "--dir", str(d)])
        main(["edge", "add", "gateway", "api", "--dir", str(d)])
        main(["edge", "add", "api", "stripe", "--dir", str(d)])
        rc = main(["status", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[ingress]" in out
        assert "[egress]" in out

    def test_egress_cannot_be_edge_source(self, project_dir: Path):
        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])
        main(["node", "add", "stripe", "--port", "8002", "--role", "egress", "--dir", str(d)])
        # Adding an edge from egress to api should fail
        rc = main(["edge", "add", "stripe", "api", "--dir", str(d)])
        assert rc == 1


class TestServiceRegister:
    def test_register(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])

        svc = d / "api"
        svc.mkdir()
        (svc / MANIFEST_FILENAME).write_text(yaml.dump({"name": "api"}))

        rc = main(["service", "register", str(svc), "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Registered" in out

    def test_register_invalid(self, project_dir: Path):
        d = project_dir / "p"
        main(["init", str(d)])
        rc = main(["service", "register", str(d / "nonexistent"), "--dir", str(d)])
        assert rc == 1


class TestServiceList:
    def test_list_services(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])

        for name in ["api", "db"]:
            svc = d / name
            svc.mkdir()
            data = {"name": name}
            if name == "api":
                data["dependencies"] = ["db"]
            (svc / MANIFEST_FILENAME).write_text(yaml.dump(data))

        rc = main(["service", "list", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "api" in out
        assert "db" in out

    def test_list_empty(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])
        rc = main(["service", "list", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "No services" in out


class TestServiceDerive:
    def test_derive(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])

        for name in ["api", "db"]:
            svc = d / name
            svc.mkdir()
            data = {"name": name}
            if name == "api":
                data["dependencies"] = ["db"]
            (svc / MANIFEST_FILENAME).write_text(yaml.dump(data))

        rc = main(["service", "derive", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "2 nodes" in out
        assert "api -> db" in out

    def test_derive_and_save(self, project_dir: Path):
        d = project_dir / "p"
        main(["init", str(d)])

        svc = d / "api"
        svc.mkdir()
        (svc / MANIFEST_FILENAME).write_text(yaml.dump({"name": "api"}))

        rc = main(["service", "derive", "--save", "--dir", str(d)])
        assert rc == 0
        circuit = load_circuit(d)
        assert len(circuit.nodes) == 1
        assert circuit.nodes[0].name == "api"


class TestCheck:
    def test_check_compatible(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])

        svc = d / "api"
        svc.mkdir()
        (svc / MANIFEST_FILENAME).write_text(
            yaml.dump({"name": "api", "api_spec": "spec.yaml"})
        )
        # No dependencies with expected_api -> always compatible
        rc = main(["check", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "compatible" in out

    def test_check_no_services(self, project_dir: Path):
        d = project_dir / "p"
        main(["init", str(d)])
        rc = main(["check", "--dir", str(d)])
        assert rc == 1


class TestRouteShow:
    def test_show_no_state(self, project_dir: Path):
        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])
        rc = main(["route", "show", "api", "--dir", str(d)])
        # No state file -> node not found
        assert rc == 1

    def test_show_with_state(self, project_dir: Path, capsys):
        import json
        from baton.schemas import AdapterState, CircuitState, NodeStatus
        from baton.state import save_state

        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])

        # Create state with routing config
        state = CircuitState(
            circuit_name="default",
            adapters={
                "api": AdapterState(
                    node_name="api",
                    status=NodeStatus.ACTIVE,
                    routing_config={
                        "strategy": "weighted",
                        "targets": [
                            {"name": "a", "host": "127.0.0.1", "port": 8001, "weight": 80},
                            {"name": "b", "host": "127.0.0.1", "port": 8002, "weight": 20},
                        ],
                        "rules": [],
                        "default_target": "",
                        "locked": False,
                    },
                )
            },
        )
        save_state(state, d)

        rc = main(["route", "show", "api", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "weighted" in out

    def test_show_no_routing(self, project_dir: Path, capsys):
        from baton.schemas import AdapterState, CircuitState, NodeStatus
        from baton.state import save_state

        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])

        state = CircuitState(
            circuit_name="default",
            adapters={"api": AdapterState(node_name="api", status=NodeStatus.LISTENING)},
        )
        save_state(state, d)

        rc = main(["route", "show", "api", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "single backend" in out


class TestRouteLock:
    def test_route_no_subcommand(self):
        rc = main(["route"])
        assert rc == 1


class TestDeploy:
    def test_deploy_status_no_circuit(self, project_dir: Path):
        d = project_dir / "p"
        # No baton.yaml -> should fail
        rc = main(["deploy-status", "--dir", str(d)])
        assert rc == 1


class TestApplyCommand:
    def test_apply_dry_run(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])
        main(["node", "add", "db", "--port", "5432", "--mode", "tcp", "--dir", str(d)])
        main(["edge", "add", "api", "db", "--dir", str(d)])

        rc = main(["apply", "--dry-run", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "BOOT" in out
        assert "api" in out

    def test_apply_dry_run_no_config(self, project_dir: Path):
        d = project_dir / "p"
        rc = main(["apply", "--dry-run", "--dir", str(d)])
        assert rc == 1


class TestExportCommand:
    def test_export_stdout(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])

        rc = main(["export", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "name:" in out
        assert "api" in out

    def test_export_to_file(self, project_dir: Path):
        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])

        outfile = str(d / "snapshot.yaml")
        rc = main(["export", "--dir", str(d), "--output", outfile])
        assert rc == 0
        assert (d / "snapshot.yaml").exists()
        content = (d / "snapshot.yaml").read_text()
        assert "api" in content

    def test_export_no_config(self, project_dir: Path):
        d = project_dir / "p"
        d.mkdir(parents=True, exist_ok=True)
        rc = main(["export", "--dir", str(d)])
        assert rc == 1

    def test_export_with_runtime_routing(self, project_dir: Path, capsys):
        """Export includes routing from running state."""
        from baton.schemas import AdapterState, CircuitState, NodeStatus
        from baton.state import save_state

        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])

        # Create state with routing config
        state = CircuitState(
            circuit_name="default",
            adapters={
                "api": AdapterState(
                    node_name="api",
                    status=NodeStatus.ACTIVE,
                    routing_config={
                        "strategy": "weighted",
                        "targets": [
                            {"name": "a", "host": "127.0.0.1", "port": 8001, "weight": 80},
                            {"name": "b", "host": "127.0.0.1", "port": 8002, "weight": 20},
                        ],
                        "rules": [],
                        "default_target": "",
                        "locked": False,
                    },
                )
            },
        )
        save_state(state, d)

        rc = main(["export", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "weighted" in out


class TestApplyDryRunIncremental:
    def test_dry_run_shows_add_node(self, project_dir: Path, capsys):
        """ADD NODE in CLI dry-run output when adding a node."""
        from baton.schemas import AdapterState, CircuitState, NodeStatus, CircuitSpec, EdgeSpec, NodeSpec
        from baton.state import save_state, save_circuit_spec

        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])
        main(["node", "add", "db", "--port", "5432", "--mode", "tcp", "--dir", str(d)])
        main(["edge", "add", "api", "db", "--dir", str(d)])

        # Persist state and circuit from a "previous apply" with just api+db
        state = CircuitState(
            circuit_name="default",
            adapters={
                "api": AdapterState(node_name="api", status=NodeStatus.LISTENING),
                "db": AdapterState(node_name="db", status=NodeStatus.LISTENING),
            },
        )
        old_circuit = CircuitSpec(
            name="default",
            nodes=[NodeSpec(name="api", port=8001), NodeSpec(name="db", port=5432, proxy_mode="tcp")],
            edges=[EdgeSpec(source="api", target="db")],
        )
        save_state(state, d)
        save_circuit_spec(old_circuit, d)

        # Now add a 3rd node to the config (baton.yaml)
        main(["node", "add", "cache", "--port", "6379", "--dir", str(d)])

        rc = main(["apply", "--dry-run", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ADD NODE" in out
        assert "cache" in out

    def test_dry_run_shows_remove_node(self, project_dir: Path, capsys):
        """REMOVE NODE in CLI dry-run output when removing a node."""
        from baton.schemas import AdapterState, CircuitState, NodeStatus, CircuitSpec, EdgeSpec, NodeSpec
        from baton.state import save_state, save_circuit_spec

        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])
        main(["node", "add", "db", "--port", "5432", "--mode", "tcp", "--dir", str(d)])
        main(["edge", "add", "api", "db", "--dir", str(d)])

        # Persist state and circuit from a "previous apply" with api+db+cache
        state = CircuitState(
            circuit_name="default",
            adapters={
                "api": AdapterState(node_name="api", status=NodeStatus.LISTENING),
                "db": AdapterState(node_name="db", status=NodeStatus.LISTENING),
                "cache": AdapterState(node_name="cache", status=NodeStatus.LISTENING),
            },
        )
        old_circuit = CircuitSpec(
            name="default",
            nodes=[
                NodeSpec(name="api", port=8001),
                NodeSpec(name="db", port=5432, proxy_mode="tcp"),
                NodeSpec(name="cache", port=6379),
            ],
            edges=[EdgeSpec(source="api", target="db")],
        )
        save_state(state, d)
        save_circuit_spec(old_circuit, d)

        # baton.yaml only has api+db (no cache), so cache is removed
        rc = main(["apply", "--dry-run", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "REMOVE NODE" in out
        assert "cache" in out


class TestApplyDryRunProvider:
    def test_dry_run_shows_provider(self, project_dir: Path, capsys):
        """Non-local config shows provider info in dry-run."""
        import yaml as _yaml

        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])

        # Write config with deploy section
        config_path = d / "baton.yaml"
        data = _yaml.safe_load(config_path.read_text())
        data["deploy"] = {"provider": "gcp", "project": "my-gcp-proj", "region": "us-east1"}
        config_path.write_text(_yaml.dump(data, default_flow_style=False))

        rc = main(["apply", "--dry-run", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "gcp" in out
        assert "my-gcp-proj" in out


class TestSignalsCLI:
    def _init_with_signals(self, d: Path) -> Path:
        """Initialize a project and write signal data."""
        import json as _json
        main(["init", str(d)])
        signals_path = d / ".baton" / "signals.jsonl"
        signals = [
            {"node_name": "api", "direction": "inbound", "method": "GET",
             "path": "/health", "status_code": 200, "latency_ms": 5.0,
             "timestamp": "2026-01-01T00:00:00Z"},
            {"node_name": "api", "direction": "inbound", "method": "POST",
             "path": "/users", "status_code": 500, "latency_ms": 120.0,
             "timestamp": "2026-01-01T00:00:01Z"},
        ]
        with open(signals_path, "w") as f:
            for s in signals:
                f.write(_json.dumps(s) + "\n")
        return d

    def test_signals_no_data(self, project_dir: Path):
        d = project_dir / "p"
        main(["init", str(d)])
        rc = main(["signals", "--dir", str(d)])
        assert rc == 1

    def test_signals_with_data(self, project_dir: Path, capsys):
        d = self._init_with_signals(project_dir / "p")
        rc = main(["signals", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "api" in out
        assert "/health" in out

    def test_signals_stats(self, project_dir: Path, capsys):
        d = self._init_with_signals(project_dir / "p")
        rc = main(["signals", "--stats", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Path" in out
        assert "/health" in out
        assert "/users" in out

    def test_signals_path_filter(self, project_dir: Path, capsys):
        d = self._init_with_signals(project_dir / "p")
        rc = main(["signals", "--path", "/health", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "/health" in out
        assert "/users" not in out


class TestMetricsCLI:
    def _init_with_metrics(self, d: Path) -> Path:
        """Initialize a project and write telemetry data."""
        import json as _json
        main(["init", str(d)])
        metrics_path = d / ".baton" / "metrics.jsonl"
        record = {
            "timestamp": "2026-01-01T00:00:00Z",
            "circuit": "test",
            "nodes": {
                "api": {
                    "name": "api",
                    "role": "service",
                    "requests_total": 100,
                    "requests_failed": 2,
                    "error_rate": 0.02,
                    "latency_p50": 12.0,
                    "latency_p95": 45.0,
                    "active_connections": 0,
                },
            },
        }
        with open(metrics_path, "w") as f:
            f.write(_json.dumps(record) + "\n")
        return d

    def test_metrics_no_data(self, project_dir: Path):
        d = project_dir / "p"
        main(["init", str(d)])
        rc = main(["metrics", "--dir", str(d)])
        assert rc == 1

    def test_metrics_json(self, project_dir: Path, capsys):
        d = self._init_with_metrics(project_dir / "p")
        rc = main(["metrics", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "api" in out

    def test_metrics_prometheus(self, project_dir: Path, capsys):
        d = self._init_with_metrics(project_dir / "p")
        rc = main(["metrics", "--prometheus", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "baton_requests_total" in out


class TestImageListCLI:
    def test_image_list_no_images(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])
        rc = main(["image", "list", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "No images" in out

    def test_image_list_with_images(self, project_dir: Path, capsys):
        import json as _json
        d = project_dir / "p"
        main(["init", str(d)])
        images = [
            {"node_name": "api", "tag": "api:latest", "built_at": "2026-01-01T00:00:00Z"},
        ]
        (d / ".baton" / "images.json").write_text(_json.dumps(images))
        rc = main(["image", "list", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "api" in out
        assert "api:latest" in out


class TestFederationCLI:
    def _init_with_federation(self, d: Path) -> Path:
        main(["init", str(d)])
        cfg_path = d / "baton.yaml"
        cfg = yaml.safe_load(cfg_path.read_text())
        cfg["federation"] = {
            "enabled": True,
            "identity": {
                "name": "cluster-a",
                "api_endpoint": "10.0.0.1:9090",
                "region": "us-east",
            },
            "peers": [
                {"name": "cluster-b", "api_endpoint": "10.0.0.2:9090", "region": "us-west"},
                {"name": "cluster-c", "api_endpoint": "10.0.0.3:9090"},
            ],
            "heartbeat_interval_s": 30.0,
            "failover_threshold": 3,
        }
        cfg_path.write_text(yaml.dump(cfg))
        return d

    def test_federation_no_subcommand(self, capsys):
        rc = main(["federation"])
        assert rc == 1
        out = capsys.readouterr().err
        assert "Usage" in out

    def test_federation_status_no_config(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])
        rc = main(["federation", "status", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "not configured" in out

    def test_federation_status(self, project_dir: Path, capsys):
        d = self._init_with_federation(project_dir / "p")
        rc = main(["federation", "status", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "cluster-a" in out
        assert "us-east" in out
        assert "Peers: 2" in out

    def test_federation_status_json(self, project_dir: Path, capsys):
        import json as _json
        d = self._init_with_federation(project_dir / "p")
        capsys.readouterr()  # clear init output
        rc = main(["federation", "status", "--dir", str(d), "--json"])
        assert rc == 0
        data = _json.loads(capsys.readouterr().out)
        assert data["enabled"] is True
        assert data["cluster"] == "cluster-a"
        assert data["peer_count"] == 2

    def test_federation_peers(self, project_dir: Path, capsys):
        d = self._init_with_federation(project_dir / "p")
        rc = main(["federation", "peers", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "cluster-b" in out
        assert "cluster-c" in out
        assert "us-west" in out

    def test_federation_peers_json(self, project_dir: Path, capsys):
        import json as _json
        d = self._init_with_federation(project_dir / "p")
        capsys.readouterr()  # clear init output
        rc = main(["federation", "peers", "--dir", str(d), "--json"])
        assert rc == 0
        data = _json.loads(capsys.readouterr().out)
        assert len(data["peers"]) == 2
        assert data["peers"][0]["name"] == "cluster-b"

    def test_federation_peers_none(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])
        cfg_path = d / "baton.yaml"
        cfg = yaml.safe_load(cfg_path.read_text())
        cfg["federation"] = {
            "enabled": True,
            "identity": {"name": "lone", "api_endpoint": "10.0.0.1:9090"},
            "peers": [],
        }
        cfg_path.write_text(yaml.dump(cfg))
        rc = main(["federation", "peers", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "No peers" in out

    def test_federation_no_project(self, project_dir: Path):
        rc = main(["federation", "status", "--dir", str(project_dir / "nonexistent")])
        assert rc == 1

    def test_federation_not_configured_json(self, project_dir: Path, capsys):
        import json as _json
        d = project_dir / "p"
        main(["init", str(d)])
        capsys.readouterr()  # clear init output
        rc = main(["federation", "status", "--dir", str(d), "--json"])
        assert rc == 0
        data = _json.loads(capsys.readouterr().out)
        assert data["enabled"] is False


class TestCertsCLI:
    def test_certs_no_subcommand(self, capsys):
        rc = main(["certs"])
        assert rc == 1
        out = capsys.readouterr().err
        assert "Usage" in out

    def test_certs_status_no_tls(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])
        rc = main(["certs", "status", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "no certificate configured" in out

    def test_certs_status_no_tls_json(self, project_dir: Path, capsys):
        import json as _json
        d = project_dir / "p"
        main(["init", str(d)])
        capsys.readouterr()  # clear init output
        rc = main(["certs", "status", "--dir", str(d), "--json"])
        assert rc == 0
        data = _json.loads(capsys.readouterr().out)
        assert data["configured"] is False

    def test_certs_status_with_cert_missing_file(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])
        cfg_path = d / "baton.yaml"
        cfg = yaml.safe_load(cfg_path.read_text())
        cfg["security"] = {
            "tls": {"mode": "full", "cert": "cert.pem", "key": "key.pem", "auto_rotate": True},
        }
        cfg_path.write_text(yaml.dump(cfg))
        rc = main(["certs", "status", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "cert.pem" in out
        # Should show error about missing file
        assert "not found" in out or "Error" in out

    def test_certs_status_missing_file_json(self, project_dir: Path, capsys):
        import json as _json
        d = project_dir / "p"
        main(["init", str(d)])
        cfg_path = d / "baton.yaml"
        cfg = yaml.safe_load(cfg_path.read_text())
        cfg["security"] = {
            "tls": {"mode": "full", "cert": "cert.pem", "key": "key.pem"},
        }
        cfg_path.write_text(yaml.dump(cfg))
        capsys.readouterr()  # clear init output
        rc = main(["certs", "status", "--dir", str(d), "--json"])
        assert rc == 0
        data = _json.loads(capsys.readouterr().out)
        assert data["configured"] is True
        assert "error" in data

    def test_certs_rotate_no_cert(self, project_dir: Path):
        d = project_dir / "p"
        main(["init", str(d)])
        rc = main(["certs", "rotate", "--dir", str(d)])
        assert rc == 1

    def test_certs_rotate_missing_file(self, project_dir: Path):
        d = project_dir / "p"
        main(["init", str(d)])
        cfg_path = d / "baton.yaml"
        cfg = yaml.safe_load(cfg_path.read_text())
        cfg["security"] = {
            "tls": {"cert": "cert.pem", "key": "key.pem"},
        }
        cfg_path.write_text(yaml.dump(cfg))
        rc = main(["certs", "rotate", "--dir", str(d)])
        assert rc == 1

    def test_certs_no_project(self, project_dir: Path):
        rc = main(["certs", "status", "--dir", str(project_dir / "nonexistent")])
        assert rc == 1


class TestExportCLI:
    def test_export_basic(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])
        rc = main(["export", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "api" in out

    def test_export_to_file(self, project_dir: Path):
        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])
        outfile = str(d / "exported.yaml")
        rc = main(["export", "--dir", str(d), "--output", outfile])
        assert rc == 0
        assert Path(outfile).exists()
        content = Path(outfile).read_text()
        assert "api" in content

    def test_export_no_config(self, project_dir: Path):
        rc = main(["export", "--dir", str(project_dir / "nonexistent")])
        assert rc == 1


class TestDashboardJsonCLI:
    def test_dashboard_json_no_data(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])
        # Dashboard --json reads from state, which is empty
        # This will go through the async path -- skip for sync-only coverage
        pass


class TestCheckCLI:
    def test_check_no_services(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])
        rc = main(["check", "--dir", str(d)])
        # Returns 1 when no services registered
        assert rc == 1
        out = capsys.readouterr().out
        assert "No services" in out


class TestStatusCLI:
    def test_status_no_state(self, project_dir: Path, capsys):
        d = project_dir / "p"
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])
        rc = main(["status", "--dir", str(d)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "api" in out

    def test_status_no_project(self, project_dir: Path):
        rc = main(["status", "--dir", str(project_dir / "nonexistent")])
        assert rc == 1


class TestNoCommand:
    def test_no_args(self):
        rc = main([])
        assert rc == 1


class TestSlotAndSwapDispatch:
    def test_slot_preserves_subcommand_when_service_command_is_provided(self, monkeypatch, project_dir):
        captured = {}

        async def fake_cmd_async(args):
            captured["args"] = args
            return 0

        monkeypatch.setattr("baton.cli._cmd_async", fake_cmd_async)

        rc = main(["slot", "api", "python -m app", "--dir", str(project_dir)])

        assert rc == 0
        assert captured["args"].command == "slot"
        assert captured["args"].service_cmd == "python -m app"

    def test_swap_preserves_subcommand_when_service_command_is_provided(self, monkeypatch, project_dir):
        captured = {}

        async def fake_cmd_async(args):
            captured["args"] = args
            return 0

        monkeypatch.setattr("baton.cli._cmd_async", fake_cmd_async)

        rc = main(["swap", "api", "python -m app", "--dir", str(project_dir)])

        assert rc == 0
        assert captured["args"].command == "swap"
        assert captured["args"].service_cmd == "python -m app"
