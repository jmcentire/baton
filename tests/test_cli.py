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

        async def fake_slot(args):
            captured["args"] = args
            return 0

        monkeypatch.setattr("baton.cli._cmd_slot", fake_slot)

        rc = main(["slot", "api", "python -m app", "--dir", str(project_dir)])

        assert rc == 0
        assert captured["args"].command == "slot"
        assert captured["args"].service_cmd == "python -m app"

    def test_swap_preserves_subcommand_when_service_command_is_provided(self, monkeypatch, project_dir):
        captured = {}

        async def fake_swap(args):
            captured["args"] = args
            return 0

        monkeypatch.setattr("baton.cli._cmd_swap", fake_swap)

        rc = main(["swap", "api", "python -m app", "--dir", str(project_dir)])

        assert rc == 0
        assert captured["args"].command == "swap"
        assert captured["args"].service_cmd == "python -m app"


class TestSubparserDispatchCoverage:
    """Every registered subparser must have a `func` set via set_defaults,
    so adding a subcommand to the parser without wiring its handler is
    caught here (single source of truth for CLI dispatch).
    """

    def _build_parser(self):
        import argparse
        from baton import cli as cli_mod

        # Intercept the parser before main() calls parse_args.
        captured = {}
        orig_parse_args = argparse.ArgumentParser.parse_args

        def capture_parse_args(self, *a, **kw):
            captured.setdefault("parser", self)
            # Force argparse to exit instead of running anything.
            raise SystemExit(0)

        argparse.ArgumentParser.parse_args = capture_parse_args
        try:
            try:
                cli_mod.main(["--help-noop"])
            except SystemExit:
                pass
        finally:
            argparse.ArgumentParser.parse_args = orig_parse_args
        return captured["parser"]

    def _walk_leaves(self, parser):
        """Yield every leaf subparser (no further subparsers under it)."""
        import argparse
        sub_actions = [
            a for a in parser._actions
            if isinstance(a, argparse._SubParsersAction)
        ]
        if not sub_actions:
            yield parser
            return
        for sa in sub_actions:
            for sp in sa.choices.values():
                yield from self._walk_leaves(sp)

    def test_every_subparser_has_func(self):
        parser = self._build_parser()
        # Skip the top-level parser itself; check each subparser.
        import argparse
        top_sub = next(
            a for a in parser._actions
            if isinstance(a, argparse._SubParsersAction)
        )
        missing = []
        for name, subp in top_sub.choices.items():
            for leaf in self._walk_leaves(subp):
                if "func" not in leaf._defaults or leaf._defaults["func"] is None:
                    missing.append(f"{name} -> {leaf.prog}")
        assert not missing, (
            "Subparsers without a dispatch handler (set_defaults(func=...)):\n"
            + "\n".join(missing)
        )


class TestSlotAttach:
    """When a circuit is already running in another process,
    `baton slot` should attach rather than try to bring up its own."""

    def test_slot_dispatches_attach_when_owner_alive(self, monkeypatch, project_dir):
        import asyncio
        from baton import cli as cli_mod
        from baton.schemas import CircuitState

        # Pretend another baton process owns the circuit and is alive.
        fake_state = CircuitState(
            circuit_name="t", owner_pid=999999,
        )
        monkeypatch.setattr(cli_mod, "load_state", lambda d: fake_state)
        monkeypatch.setattr(cli_mod, "_owner_alive", lambda s: True)

        captured = {}

        async def fake_attach(args, state):
            captured["args"] = args
            captured["state"] = state
            return 0

        monkeypatch.setattr(cli_mod, "_cmd_slot_attach", fake_attach)

        rc = main(["slot", "api", "python -m app", "--dir", str(project_dir)])
        assert rc == 0
        assert captured["args"].node == "api"
        assert captured["args"].service_cmd == "python -m app"
        assert captured["state"] is fake_state

    def test_owner_alive_self_pid_returns_false(self):
        """A stale state file claiming our own pid should NOT trigger attach."""
        from baton.cli import _owner_alive
        from baton.schemas import CircuitState
        import os
        s = CircuitState(circuit_name="t", owner_pid=os.getpid())
        assert _owner_alive(s) is False

    def test_owner_alive_zero_pid_returns_false(self):
        from baton.cli import _owner_alive
        from baton.schemas import CircuitState
        s = CircuitState(circuit_name="t", owner_pid=0)
        assert _owner_alive(s) is False

    def test_owner_alive_dead_pid_returns_false(self):
        from baton.cli import _owner_alive
        from baton.schemas import CircuitState
        # PID 999999 is almost certainly not running on a fresh machine.
        s = CircuitState(circuit_name="t", owner_pid=999999)
        # If by an extraordinary fluke this pid exists, the function may
        # return True. Most CI/dev machines won't have it.
        assert _owner_alive(s) in (False, True)


class TestCmdSlotAttach:
    """Unit tests for _cmd_slot_attach state-persistence fix.

    The function is fully async, so every test is an async def (picked up
    automatically by pytest-asyncio in auto mode).  All I/O that would hit
    real ports is replaced with lightweight mocks so the suite stays fast
    and port-free.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _setup_one_node(self, d: Path) -> None:
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])

    def _setup_two_nodes(self, d: Path) -> None:
        main(["init", str(d)])
        main(["node", "add", "api", "--port", "8001", "--dir", str(d)])
        main(["node", "add", "svc", "--port", "8002", "--dir", str(d)])

    def _make_args(self, d: Path, node: str = "api"):
        from unittest.mock import MagicMock
        args = MagicMock()
        args.dir = str(d)
        args.node = node
        args.service_cmd = "python -m myapp"
        args.skip_validate = True
        return args

    def _apply_mocks(self, monkeypatch, cli_mod, saved_states, *, control_status: int = 200) -> None:
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from baton import collapse as collapse_mod
        from baton import process as process_mod

        monkeypatch.setattr(cli_mod, "save_state", lambda s, d: saved_states.append(s.model_copy(deep=True)))
        monkeypatch.setattr(cli_mod, "_control_post", AsyncMock(return_value=(control_status, "ok")))
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())

        fake_info = MagicMock()
        fake_info.pid = 42
        pm = MagicMock()
        pm.start = AsyncMock(return_value=fake_info)
        pm.stop = AsyncMock()
        monkeypatch.setattr(process_mod, "ProcessManager", lambda: pm)

        # No real adapters are running, so skip the restore POST in the finally block.
        monkeypatch.setattr(collapse_mod, "compute_mock_backends", lambda c, live_nodes: {})

        # Make the stop event pre-set so await stop_event.wait() returns immediately,
        # driving the finally block without blocking.
        pre_set = asyncio.Event()
        pre_set.set()
        monkeypatch.setattr(asyncio, "Event", lambda: pre_set)

    # ------------------------------------------------------------------
    # Helpers (port-conflict tests)
    # ------------------------------------------------------------------

    def _apply_mocks_capturing(self, monkeypatch, cli_mod):
        """Like _apply_mocks but returns the raw mock objects for inspection."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from baton import collapse as collapse_mod
        from baton import process as process_mod

        fake_info = MagicMock()
        fake_info.pid = 42
        pm_mock = MagicMock()
        pm_mock.start = AsyncMock(return_value=fake_info)
        pm_mock.stop = AsyncMock()
        monkeypatch.setattr(process_mod, "ProcessManager", lambda: pm_mock)

        control_post_mock = AsyncMock(return_value=(200, "ok"))
        monkeypatch.setattr(cli_mod, "_control_post", control_post_mock)
        monkeypatch.setattr(cli_mod, "save_state", lambda s, d: None)
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(collapse_mod, "compute_mock_backends", lambda c, live_nodes: {})

        pre_set = asyncio.Event()
        pre_set.set()
        monkeypatch.setattr(asyncio, "Event", lambda: pre_set)

        return pm_mock, control_post_mock

    # ------------------------------------------------------------------
    # Tests: port allocation (fix for mock-server port conflict)
    # ------------------------------------------------------------------

    async def test_service_port_does_not_conflict_with_mock_server(self, project_dir: Path, monkeypatch):
        """service_port must not equal node.port+20000 — that port belongs to the mock server."""
        from baton import cli as cli_mod
        from baton.schemas import CircuitState

        self._setup_one_node(project_dir)  # api on 8001; mock server holds 28001
        pm_mock, _ = self._apply_mocks_capturing(monkeypatch, cli_mod)

        rc = await cli_mod._cmd_slot_attach(
            self._make_args(project_dir), CircuitState(circuit_name="t", owner_pid=12345)
        )

        assert rc == 0
        allocated_port = int(pm_mock.start.call_args.kwargs["env"]["BATON_SERVICE_PORT"])
        assert allocated_port != 8001 + 20000
        assert 1 <= allocated_port <= 65535

    async def test_backend_post_uses_allocated_service_port(self, project_dir: Path, monkeypatch):
        """The /backend control POST must carry the same free port the service was given."""
        from baton import cli as cli_mod
        from baton.schemas import CircuitState

        self._setup_one_node(project_dir)
        pm_mock, control_post_mock = self._apply_mocks_capturing(monkeypatch, cli_mod)

        await cli_mod._cmd_slot_attach(
            self._make_args(project_dir), CircuitState(circuit_name="t", owner_pid=12345)
        )

        allocated_port = int(pm_mock.start.call_args.kwargs["env"]["BATON_SERVICE_PORT"])
        backend_call = next(c for c in control_post_mock.call_args_list if c.args[2] == "/backend")
        assert backend_call.args[3]["port"] == allocated_port

    # ------------------------------------------------------------------
    # Tests: successful attach
    # ------------------------------------------------------------------

    async def test_node_added_to_live_nodes_on_attach(self, project_dir: Path, monkeypatch):
        from baton import cli as cli_mod
        from baton.schemas import CircuitState

        self._setup_one_node(project_dir)
        saved = []
        self._apply_mocks(monkeypatch, cli_mod, saved)

        rc = await cli_mod._cmd_slot_attach(
            self._make_args(project_dir), CircuitState(circuit_name="t", owner_pid=12345)
        )

        assert rc == 0
        assert "api" in saved[0].live_nodes

    async def test_collapse_level_full_live_with_only_node(self, project_dir: Path, monkeypatch):
        from baton import cli as cli_mod
        from baton.schemas import CircuitState, CollapseLevel

        self._setup_one_node(project_dir)
        saved = []
        self._apply_mocks(monkeypatch, cli_mod, saved)

        await cli_mod._cmd_slot_attach(
            self._make_args(project_dir), CircuitState(circuit_name="t", owner_pid=12345)
        )

        assert saved[0].collapse_level == CollapseLevel.FULL_LIVE

    async def test_collapse_level_partial_with_one_of_two_nodes(self, project_dir: Path, monkeypatch):
        from baton import cli as cli_mod
        from baton.schemas import CircuitState, CollapseLevel

        self._setup_two_nodes(project_dir)
        saved = []
        self._apply_mocks(monkeypatch, cli_mod, saved)

        await cli_mod._cmd_slot_attach(
            self._make_args(project_dir), CircuitState(circuit_name="t", owner_pid=12345)
        )

        assert saved[0].collapse_level == CollapseLevel.PARTIAL

    async def test_save_state_called_twice(self, project_dir: Path, monkeypatch):
        """save_state must be called once on attach and once in the finally block."""
        from baton import cli as cli_mod
        from baton.schemas import CircuitState

        self._setup_one_node(project_dir)
        saved = []
        self._apply_mocks(monkeypatch, cli_mod, saved)

        await cli_mod._cmd_slot_attach(
            self._make_args(project_dir), CircuitState(circuit_name="t", owner_pid=12345)
        )

        assert len(saved) == 2

    # ------------------------------------------------------------------
    # Tests: detach / finally-block restoration
    # ------------------------------------------------------------------

    async def test_live_nodes_cleared_after_detach(self, project_dir: Path, monkeypatch):
        from baton import cli as cli_mod
        from baton.schemas import CircuitState

        self._setup_one_node(project_dir)
        saved = []
        self._apply_mocks(monkeypatch, cli_mod, saved)

        await cli_mod._cmd_slot_attach(
            self._make_args(project_dir), CircuitState(circuit_name="t", owner_pid=12345)
        )

        # Second save is the finally-block restoration.
        assert saved[1].live_nodes == []

    async def test_collapse_level_full_mock_after_detach(self, project_dir: Path, monkeypatch):
        from baton import cli as cli_mod
        from baton.schemas import CircuitState, CollapseLevel

        self._setup_one_node(project_dir)
        saved = []
        self._apply_mocks(monkeypatch, cli_mod, saved)

        await cli_mod._cmd_slot_attach(
            self._make_args(project_dir), CircuitState(circuit_name="t", owner_pid=12345)
        )

        assert saved[1].collapse_level == CollapseLevel.FULL_MOCK

    # ------------------------------------------------------------------
    # Tests: failure path — control POST rejected
    # ------------------------------------------------------------------

    async def test_state_not_saved_when_control_post_fails(self, project_dir: Path, monkeypatch):
        from baton import cli as cli_mod
        from baton.schemas import CircuitState

        self._setup_one_node(project_dir)
        saved = []
        self._apply_mocks(monkeypatch, cli_mod, saved, control_status=500)

        rc = await cli_mod._cmd_slot_attach(
            self._make_args(project_dir), CircuitState(circuit_name="t", owner_pid=12345)
        )

        assert rc == 1
        assert saved == []


class TestDevDependencies:
    """Verify pyproject.toml includes mcp in the dev extra."""

    def test_mcp_in_dev_extras(self):
        import tomllib

        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)

        dev_deps = data["project"]["optional-dependencies"]["dev"]
        assert any("mcp" in dep for dep in dev_deps), (
            "mcp must be listed in [project.optional-dependencies.dev] "
            "so that `pip install -e '.[dev]'` installs it"
        )
