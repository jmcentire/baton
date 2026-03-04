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


class TestNoCommand:
    def test_no_args(self):
        rc = main([])
        assert rc == 1
