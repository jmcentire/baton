"""Tests for service registry and circuit derivation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from baton.manifest import MANIFEST_FILENAME
from baton.registry import derive_circuit, load_manifests
from baton.schemas import DependencySpec, NodeRole, ServiceManifest


def _write_manifest(d: Path, data: dict) -> None:
    (d / MANIFEST_FILENAME).write_text(yaml.dump(data))


class TestLoadManifests:
    def test_load_multiple(self, tmp_path: Path):
        d1 = tmp_path / "api"
        d1.mkdir()
        _write_manifest(d1, {"name": "api"})

        d2 = tmp_path / "db"
        d2.mkdir()
        _write_manifest(d2, {"name": "db"})

        manifests = load_manifests([d1, d2])
        assert len(manifests) == 2
        assert manifests[0].name == "api"
        assert manifests[1].name == "db"

    def test_duplicate_names_rejected(self, tmp_path: Path):
        d1 = tmp_path / "svc1"
        d1.mkdir()
        _write_manifest(d1, {"name": "api"})

        d2 = tmp_path / "svc2"
        d2.mkdir()
        _write_manifest(d2, {"name": "api"})

        with pytest.raises(ValueError, match="Duplicate service names"):
            load_manifests([d1, d2])


class TestDeriveCircuit:
    def test_derive_simple(self):
        manifests = [
            ServiceManifest(name="api", dependencies=[DependencySpec(name="db")]),
            ServiceManifest(name="db", proxy_mode="tcp"),
        ]
        circuit = derive_circuit(manifests, "test")
        assert circuit.name == "test"
        assert len(circuit.nodes) == 2
        assert len(circuit.edges) == 1
        assert circuit.edges[0].source == "api"
        assert circuit.edges[0].target == "db"

    def test_derive_auto_ports(self):
        manifests = [
            ServiceManifest(name="a"),
            ServiceManifest(name="b"),
            ServiceManifest(name="c"),
        ]
        circuit = derive_circuit(manifests)
        ports = [n.port for n in circuit.nodes]
        assert ports == [9001, 9002, 9003]

    def test_derive_explicit_ports(self):
        manifests = [
            ServiceManifest(name="api", port=8080),
            ServiceManifest(name="db", port=5432),
        ]
        circuit = derive_circuit(manifests)
        assert circuit.node_by_name("api").port == 8080
        assert circuit.node_by_name("db").port == 5432

    def test_derive_mixed_ports(self):
        manifests = [
            ServiceManifest(name="api", port=8080),
            ServiceManifest(name="service"),  # auto
        ]
        circuit = derive_circuit(manifests)
        assert circuit.node_by_name("api").port == 8080
        assert circuit.node_by_name("service").port == 9001

    def test_derive_preserves_contract(self):
        manifests = [
            ServiceManifest(name="api", api_spec="specs/api.yaml"),
        ]
        circuit = derive_circuit(manifests)
        assert circuit.node_by_name("api").contract == "specs/api.yaml"

    def test_derive_mock_spec_priority(self):
        manifests = [
            ServiceManifest(
                name="api",
                api_spec="specs/api.yaml",
                mock_spec="specs/mock.yaml",
            ),
        ]
        circuit = derive_circuit(manifests)
        assert circuit.node_by_name("api").contract == "specs/mock.yaml"

    def test_derive_missing_dependency(self):
        manifests = [
            ServiceManifest(
                name="api",
                dependencies=[DependencySpec(name="missing")],
            ),
        ]
        with pytest.raises(ValueError, match="not registered"):
            derive_circuit(manifests)

    def test_derive_optional_missing_dependency(self):
        manifests = [
            ServiceManifest(
                name="api",
                dependencies=[DependencySpec(name="cache", optional=True)],
            ),
        ]
        circuit = derive_circuit(manifests)
        assert len(circuit.edges) == 0
        assert len(circuit.nodes) == 1

    def test_derive_ingress_node(self):
        manifests = [
            ServiceManifest(name="gateway", role="ingress",
                            dependencies=[DependencySpec(name="api")]),
            ServiceManifest(name="api"),
        ]
        circuit = derive_circuit(manifests)
        gw = circuit.node_by_name("gateway")
        assert gw.role == NodeRole.INGRESS
        assert len(circuit.edges) == 1
        assert circuit.edges[0].source == "gateway"
        assert circuit.edges[0].target == "api"

    def test_derive_egress_node(self):
        manifests = [
            ServiceManifest(name="api", dependencies=[DependencySpec(name="stripe")]),
            ServiceManifest(
                name="stripe", role="egress",
                api_spec="specs/stripe.yaml",
            ),
        ]
        circuit = derive_circuit(manifests)
        stripe = circuit.node_by_name("stripe")
        assert stripe.role == NodeRole.EGRESS
        assert stripe.contract == "specs/stripe.yaml"

    def test_derive_edge_direction(self):
        """Consumer is source, provider is target."""
        manifests = [
            ServiceManifest(name="web", dependencies=[DependencySpec(name="api")]),
            ServiceManifest(name="api", dependencies=[DependencySpec(name="db")]),
            ServiceManifest(name="db"),
        ]
        circuit = derive_circuit(manifests)
        sources = [e.source for e in circuit.edges]
        targets = [e.target for e in circuit.edges]
        assert "web" in sources
        assert "api" in sources
        assert "api" in targets
        assert "db" in targets

    def test_derive_multiple_dependencies(self):
        manifests = [
            ServiceManifest(
                name="api",
                dependencies=[
                    DependencySpec(name="db"),
                    DependencySpec(name="cache"),
                    DependencySpec(name="auth"),
                ],
            ),
            ServiceManifest(name="db"),
            ServiceManifest(name="cache"),
            ServiceManifest(name="auth"),
        ]
        circuit = derive_circuit(manifests)
        assert len(circuit.edges) == 3
        targets = {e.target for e in circuit.edges}
        assert targets == {"db", "cache", "auth"}

    def test_derive_empty(self):
        circuit = derive_circuit([])
        assert len(circuit.nodes) == 0
        assert len(circuit.edges) == 0

    def test_derive_port_conflict(self):
        manifests = [
            ServiceManifest(name="api", port=8080),
            ServiceManifest(name="db", port=8080),
        ]
        with pytest.raises(ValueError, match="Port conflict"):
            derive_circuit(manifests)

    def test_derive_preserves_metadata(self):
        manifests = [
            ServiceManifest(name="api", metadata={"team": "platform"}),
        ]
        circuit = derive_circuit(manifests)
        assert circuit.node_by_name("api").metadata["team"] == "platform"

    def test_derive_no_cycles(self):
        """Linear dependency chain should not be detected as a cycle."""
        from baton.circuit import has_cycle
        manifests = [
            ServiceManifest(name="a", dependencies=[DependencySpec(name="b")]),
            ServiceManifest(name="b", dependencies=[DependencySpec(name="c")]),
            ServiceManifest(name="c"),
        ]
        circuit = derive_circuit(manifests)
        assert not has_cycle(circuit)
