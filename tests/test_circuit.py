"""Tests for circuit graph operations."""

from __future__ import annotations

import pytest

from baton.circuit import (
    add_edge,
    add_node,
    has_cycle,
    remove_edge,
    remove_node,
    set_contract,
    topological_sort,
)
from baton.schemas import CircuitSpec, EdgeSpec, NodeSpec


class TestAddNode:
    def test_add_to_empty(self):
        c = CircuitSpec(name="test")
        c2 = add_node(c, "api", port=8001)
        assert len(c2.nodes) == 1
        assert c2.nodes[0].name == "api"
        assert c2.nodes[0].port == 8001

    def test_auto_port(self):
        c = CircuitSpec(name="test")
        c2 = add_node(c, "api")
        assert c2.nodes[0].port == 9001

    def test_auto_port_increments(self):
        c = CircuitSpec(name="test", nodes=[NodeSpec(name="api", port=9001)])
        c2 = add_node(c, "service")
        assert c2.nodes[1].port == 9002

    def test_duplicate_name(self, sample_circuit):
        with pytest.raises(ValueError, match="already exists"):
            add_node(sample_circuit, "api")

    def test_tcp_mode(self):
        c = CircuitSpec(name="test")
        c2 = add_node(c, "db", port=5432, proxy_mode="tcp")
        assert c2.nodes[0].proxy_mode == "tcp"

    def test_original_unchanged(self):
        c = CircuitSpec(name="test")
        c2 = add_node(c, "api", port=8001)
        assert len(c.nodes) == 0
        assert len(c2.nodes) == 1


class TestRemoveNode:
    def test_remove_existing(self, sample_circuit):
        c2 = remove_node(sample_circuit, "service")
        assert len(c2.nodes) == 2
        assert c2.node_by_name("service") is None

    def test_removes_connected_edges(self, sample_circuit):
        c2 = remove_node(sample_circuit, "service")
        assert len(c2.edges) == 0

    def test_remove_missing(self, sample_circuit):
        with pytest.raises(ValueError, match="not found"):
            remove_node(sample_circuit, "missing")


class TestAddEdge:
    def test_add_edge(self):
        c = CircuitSpec(
            name="test",
            nodes=[NodeSpec(name="a", port=8001), NodeSpec(name="b", port=8002)],
        )
        c2 = add_edge(c, "a", "b")
        assert len(c2.edges) == 1
        assert c2.edges[0].source == "a"

    def test_missing_source(self):
        c = CircuitSpec(name="test", nodes=[NodeSpec(name="a", port=8001)])
        with pytest.raises(ValueError, match="Source node"):
            add_edge(c, "missing", "a")

    def test_missing_target(self):
        c = CircuitSpec(name="test", nodes=[NodeSpec(name="a", port=8001)])
        with pytest.raises(ValueError, match="Target node"):
            add_edge(c, "a", "missing")

    def test_duplicate_edge(self, sample_circuit):
        with pytest.raises(ValueError, match="already exists"):
            add_edge(sample_circuit, "api", "service")


class TestRemoveEdge:
    def test_remove_existing(self, sample_circuit):
        c2 = remove_edge(sample_circuit, "api", "service")
        assert len(c2.edges) == 1

    def test_remove_missing(self, sample_circuit):
        with pytest.raises(ValueError, match="not found"):
            remove_edge(sample_circuit, "api", "db")


class TestSetContract:
    def test_set_contract(self, sample_circuit):
        c2 = set_contract(sample_circuit, "api", "specs/api.yaml")
        assert c2.node_by_name("api").contract == "specs/api.yaml"
        # others unchanged
        assert c2.node_by_name("service").contract == ""

    def test_missing_node(self, sample_circuit):
        with pytest.raises(ValueError, match="not found"):
            set_contract(sample_circuit, "missing", "spec.yaml")


class TestHasCycle:
    def test_no_cycle(self, sample_circuit):
        assert has_cycle(sample_circuit) is False

    def test_with_cycle(self):
        c = CircuitSpec(
            name="test",
            nodes=[
                NodeSpec(name="a", port=8001),
                NodeSpec(name="b", port=8002),
                NodeSpec(name="c", port=8003),
            ],
            edges=[
                EdgeSpec(source="a", target="b"),
                EdgeSpec(source="b", target="c"),
                EdgeSpec(source="c", target="a"),
            ],
        )
        assert has_cycle(c) is True

    def test_empty(self):
        c = CircuitSpec(name="test")
        assert has_cycle(c) is False

    def test_disconnected(self):
        c = CircuitSpec(
            name="test",
            nodes=[NodeSpec(name="a", port=8001), NodeSpec(name="b", port=8002)],
        )
        assert has_cycle(c) is False


class TestTopologicalSort:
    def test_linear(self, sample_circuit):
        order = topological_sort(sample_circuit)
        assert order.index("api") < order.index("service")
        assert order.index("service") < order.index("db")

    def test_diamond(self):
        c = CircuitSpec(
            name="test",
            nodes=[
                NodeSpec(name="a", port=8001),
                NodeSpec(name="b", port=8002),
                NodeSpec(name="c", port=8003),
                NodeSpec(name="d", port=8004),
            ],
            edges=[
                EdgeSpec(source="a", target="b"),
                EdgeSpec(source="a", target="c"),
                EdgeSpec(source="b", target="d"),
                EdgeSpec(source="c", target="d"),
            ],
        )
        order = topological_sort(c)
        assert order[0] == "a"
        assert order[-1] == "d"

    def test_cycle_raises(self):
        c = CircuitSpec(
            name="test",
            nodes=[
                NodeSpec(name="a", port=8001),
                NodeSpec(name="b", port=8002),
            ],
            edges=[
                EdgeSpec(source="a", target="b"),
                EdgeSpec(source="b", target="a"),
            ],
        )
        with pytest.raises(ValueError, match="cycle"):
            topological_sort(c)

    def test_empty(self):
        c = CircuitSpec(name="test")
        assert topological_sort(c) == []

    def test_single_node(self):
        c = CircuitSpec(name="test", nodes=[NodeSpec(name="a", port=8001)])
        assert topological_sort(c) == ["a"]
