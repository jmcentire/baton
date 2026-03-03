"""Tests for config loading and saving."""

from __future__ import annotations

from pathlib import Path

import pytest

from baton.config import load_circuit, save_circuit
from baton.schemas import CircuitSpec, EdgeSpec, NodeSpec


class TestLoadCircuit:
    def test_load_empty(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text("name: empty\n")
        c = load_circuit(project_dir)
        assert c.name == "empty"
        assert c.nodes == []
        assert c.edges == []

    def test_load_with_nodes(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text(
            "name: test\nnodes:\n  - name: api\n    port: 8001\n  - name: db\n    port: 5432\n"
        )
        c = load_circuit(project_dir)
        assert len(c.nodes) == 2
        assert c.nodes[0].name == "api"
        assert c.nodes[1].port == 5432

    def test_load_with_edges(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text(
            "name: test\nnodes:\n  - name: api\n    port: 8001\n  - name: db\n    port: 5432\n"
            "edges:\n  - source: api\n    target: db\n"
        )
        c = load_circuit(project_dir)
        assert len(c.edges) == 1
        assert c.edges[0].source == "api"

    def test_missing_file(self, project_dir: Path):
        with pytest.raises(FileNotFoundError):
            load_circuit(project_dir)

    def test_empty_yaml(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text("")
        c = load_circuit(project_dir)
        assert c.name == "default"

    def test_tcp_mode(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text(
            "name: test\nnodes:\n  - name: db\n    port: 5432\n    proxy_mode: tcp\n"
        )
        c = load_circuit(project_dir)
        assert c.nodes[0].proxy_mode == "tcp"


class TestSaveCircuit:
    def test_roundtrip(self, project_dir: Path):
        circuit = CircuitSpec(
            name="roundtrip",
            nodes=[
                NodeSpec(name="api", port=8001),
                NodeSpec(name="db", port=5432, proxy_mode="tcp"),
            ],
            edges=[EdgeSpec(source="api", target="db")],
        )
        save_circuit(circuit, project_dir)
        loaded = load_circuit(project_dir)
        assert loaded.name == "roundtrip"
        assert len(loaded.nodes) == 2
        assert len(loaded.edges) == 1
        assert loaded.nodes[0].name == "api"
        assert loaded.nodes[1].proxy_mode == "tcp"

    def test_save_empty(self, project_dir: Path):
        circuit = CircuitSpec(name="empty")
        save_circuit(circuit, project_dir)
        loaded = load_circuit(project_dir)
        assert loaded.name == "empty"
        assert loaded.nodes == []

    def test_preserves_contract(self, project_dir: Path):
        circuit = CircuitSpec(
            name="test",
            nodes=[NodeSpec(name="api", port=8001, contract="specs/api.yaml")],
        )
        save_circuit(circuit, project_dir)
        loaded = load_circuit(project_dir)
        assert loaded.nodes[0].contract == "specs/api.yaml"
