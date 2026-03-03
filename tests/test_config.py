"""Tests for config loading and saving."""

from __future__ import annotations

from pathlib import Path

import pytest

import yaml

from baton.config import add_service_path, load_circuit, load_circuit_from_services, save_circuit, _discover_service_dirs
from baton.manifest import MANIFEST_FILENAME
from baton.schemas import CircuitSpec, EdgeSpec, NodeRole, NodeSpec


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

    def test_roundtrip_with_role(self, project_dir: Path):
        circuit = CircuitSpec(
            name="test",
            nodes=[
                NodeSpec(name="gateway", port=8001, role="ingress"),
                NodeSpec(name="stripe", port=8002, role="egress"),
                NodeSpec(name="api", port=8003),
            ],
        )
        save_circuit(circuit, project_dir)
        loaded = load_circuit(project_dir)
        assert loaded.nodes[0].role == NodeRole.INGRESS
        assert loaded.nodes[1].role == NodeRole.EGRESS
        assert loaded.nodes[2].role == NodeRole.SERVICE


class TestLoadCircuitFromServices:
    def test_derive_from_service_dirs(self, project_dir: Path):
        # Create service dirs with manifests
        api_dir = project_dir / "api"
        api_dir.mkdir()
        (api_dir / MANIFEST_FILENAME).write_text(
            yaml.dump({"name": "api", "dependencies": ["db"]})
        )
        db_dir = project_dir / "db"
        db_dir.mkdir()
        (db_dir / MANIFEST_FILENAME).write_text(
            yaml.dump({"name": "db", "proxy_mode": "tcp"})
        )

        circuit = load_circuit_from_services(project_dir, [api_dir, db_dir])
        assert len(circuit.nodes) == 2
        assert len(circuit.edges) == 1

    def test_derive_with_baton_yaml_name(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text("name: myapp\n")
        api_dir = project_dir / "api"
        api_dir.mkdir()
        (api_dir / MANIFEST_FILENAME).write_text(yaml.dump({"name": "api"}))

        circuit = load_circuit_from_services(project_dir, [api_dir])
        assert circuit.name == "myapp"

    def test_no_service_dirs(self, project_dir: Path):
        with pytest.raises(FileNotFoundError, match="No service directories"):
            load_circuit_from_services(project_dir)


class TestDiscoverServiceDirs:
    def test_from_yaml(self, project_dir: Path):
        api_dir = project_dir / "services" / "api"
        api_dir.mkdir(parents=True)
        (api_dir / MANIFEST_FILENAME).write_text(yaml.dump({"name": "api"}))

        (project_dir / "baton.yaml").write_text(
            yaml.dump({"name": "test", "services": ["services/api"]})
        )
        dirs = _discover_service_dirs(project_dir)
        assert len(dirs) == 1
        assert dirs[0] == project_dir / "services" / "api"

    def test_scan_subdirs(self, project_dir: Path):
        for name in ["api", "db"]:
            d = project_dir / name
            d.mkdir()
            (d / MANIFEST_FILENAME).write_text(yaml.dump({"name": name}))

        dirs = _discover_service_dirs(project_dir)
        assert len(dirs) == 2


class TestAddServicePath:
    def test_add_service(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text("name: test\n")
        add_service_path(project_dir, "./api")

        with open(project_dir / "baton.yaml") as f:
            raw = yaml.safe_load(f)
        assert "./api" in raw["services"]

    def test_add_idempotent(self, project_dir: Path):
        (project_dir / "baton.yaml").write_text("name: test\n")
        add_service_path(project_dir, "./api")
        add_service_path(project_dir, "./api")

        with open(project_dir / "baton.yaml") as f:
            raw = yaml.safe_load(f)
        assert raw["services"].count("./api") == 1

    def test_missing_baton_yaml(self, project_dir: Path):
        with pytest.raises(FileNotFoundError):
            add_service_path(project_dir, "./api")
