"""Tests for Baton CLI."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from baton.cli import main
from baton.config import load_circuit


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


class TestNoCommand:
    def test_no_args(self):
        rc = main([])
        assert rc == 1
