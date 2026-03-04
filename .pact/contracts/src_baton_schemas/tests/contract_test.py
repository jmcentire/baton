"""
Contract-driven test suite for Baton Schemas component.

This test suite verifies that the Baton Schemas implementation adheres to its contract,
covering validators, query methods, and invariants for circuit board configuration and routing.

Test categories:
- Happy path: Normal operation with valid inputs
- Edge cases: Boundary conditions and special scenarios
- Error cases: Invalid inputs that should raise specific errors
- Invariants: Cross-cutting constraints that always hold
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime
from enum import Enum
from typing import Literal
import re


# Import the component under test
try:
    from src.baton.schemas import *
except ImportError:
    # Fallback import paths
    try:
        from src_baton_schemas import *
    except ImportError:
        from baton_schemas import *


# ============================================================================
# Test Fixtures and Helpers
# ============================================================================

@pytest.fixture
def valid_node_spec_data():
    """Factory for valid NodeSpec data."""
    return {
        "name": "service_a",
        "host": "localhost",
        "port": 8080,
        "proxy_mode": ProxyMode.HTTP,
        "contract": "api.v1",
        "role": NodeRole.SERVICE,
        "management_port": 0,
        "metadata": {"env": "test"}
    }


@pytest.fixture
def valid_edge_spec_data():
    """Factory for valid EdgeSpec data."""
    return {
        "source": "service_a",
        "target": "service_b",
        "label": "http"
    }


@pytest.fixture
def valid_circuit_spec_data():
    """Factory for valid CircuitSpec data."""
    return {
        "name": "test_circuit",
        "version": 1,
        "nodes": [
            {
                "name": "ingress",
                "host": "localhost",
                "port": 8080,
                "proxy_mode": ProxyMode.HTTP,
                "contract": "api.v1",
                "role": NodeRole.INGRESS,
                "management_port": 0,
                "metadata": {}
            },
            {
                "name": "service_a",
                "host": "localhost",
                "port": 8081,
                "proxy_mode": ProxyMode.HTTP,
                "contract": "api.v1",
                "role": NodeRole.SERVICE,
                "management_port": 0,
                "metadata": {}
            },
            {
                "name": "egress",
                "host": "localhost",
                "port": 8082,
                "proxy_mode": ProxyMode.TCP,
                "contract": "tcp.v1",
                "role": NodeRole.EGRESS,
                "management_port": 0,
                "metadata": {}
            }
        ],
        "edges": [
            {"source": "ingress", "target": "service_a", "label": "http"},
            {"source": "service_a", "target": "egress", "label": "tcp"}
        ]
    }


@pytest.fixture
def valid_routing_config_data():
    """Factory for valid RoutingConfig data."""
    return {
        "strategy": RoutingStrategy.WEIGHTED,
        "targets": [
            {"name": "primary", "host": "localhost", "port": 8080, "weight": 60},
            {"name": "secondary", "host": "localhost", "port": 8081, "weight": 40}
        ],
        "rules": [],
        "default_target": "",
        "locked": False
    }


# ============================================================================
# auto_management_port Tests
# ============================================================================

def test_auto_management_port_happy_path(valid_node_spec_data):
    """Test auto_management_port assigns port + 10000 when management_port is 0."""
    valid_node_spec_data["management_port"] = 0
    valid_node_spec_data["port"] = 8080
    
    node = NodeSpec(**valid_node_spec_data)
    
    assert node.management_port == 18080, \
        f"Expected management_port to be 18080 (8080 + 10000), got {node.management_port}"
    assert node.port == 8080, "Port should remain unchanged"


def test_auto_management_port_overflow(valid_node_spec_data):
    """Test auto_management_port uses port + 1000 when port + 10000 exceeds 65535."""
    valid_node_spec_data["management_port"] = 0
    valid_node_spec_data["port"] = 60000
    
    node = NodeSpec(**valid_node_spec_data)
    
    assert node.management_port == 61000, \
        f"Expected management_port to be 61000 (60000 + 1000), got {node.management_port}"


def test_auto_management_port_already_set(valid_node_spec_data):
    """Test auto_management_port leaves non-zero management_port unchanged."""
    valid_node_spec_data["management_port"] = 9000
    valid_node_spec_data["port"] = 8080
    
    node = NodeSpec(**valid_node_spec_data)
    
    assert node.management_port == 9000, \
        f"Expected management_port to remain 9000, got {node.management_port}"


def test_auto_management_port_boundary_exactly_55535(valid_node_spec_data):
    """Test auto_management_port at exact boundary where port + 10000 = 65535."""
    valid_node_spec_data["management_port"] = 0
    valid_node_spec_data["port"] = 55535
    
    node = NodeSpec(**valid_node_spec_data)
    
    # 55535 + 10000 = 65535, which is valid
    assert node.management_port == 65535, \
        f"Expected management_port to be 65535, got {node.management_port}"


def test_auto_management_port_boundary_exceeds_by_one(valid_node_spec_data):
    """Test auto_management_port when port + 10000 = 65536 (exceeds by 1)."""
    valid_node_spec_data["management_port"] = 0
    valid_node_spec_data["port"] = 55536
    
    node = NodeSpec(**valid_node_spec_data)
    
    # 55536 + 10000 = 65536 > 65535, so use port + 1000 = 56536
    assert node.management_port == 56536, \
        f"Expected management_port to be 56536, got {node.management_port}"


# ============================================================================
# no_self_loop Tests
# ============================================================================

def test_no_self_loop_happy_path(valid_edge_spec_data):
    """Test no_self_loop allows edge with different source and target."""
    valid_edge_spec_data["source"] = "service_a"
    valid_edge_spec_data["target"] = "service_b"
    
    edge = EdgeSpec(**valid_edge_spec_data)
    
    assert edge.source == "service_a"
    assert edge.target == "service_b"


def test_no_self_loop_error(valid_edge_spec_data):
    """Test no_self_loop raises SelfLoopError when source equals target."""
    valid_edge_spec_data["source"] = "service_a"
    valid_edge_spec_data["target"] = "service_a"
    
    with pytest.raises(Exception) as exc_info:
        EdgeSpec(**valid_edge_spec_data)
    
    # Check that it's a validation error related to self-loop
    assert "self" in str(exc_info.value).lower() or "loop" in str(exc_info.value).lower(), \
        f"Expected SelfLoopError, got: {exc_info.value}"


# ============================================================================
# unique_node_names Tests
# ============================================================================

def test_unique_node_names_happy_path(valid_circuit_spec_data):
    """Test unique_node_names allows circuit with unique node names."""
    circuit = CircuitSpec(**valid_circuit_spec_data)
    
    node_names = [node.name for node in circuit.nodes]
    assert len(node_names) == len(set(node_names)), \
        "All node names should be unique"


def test_unique_node_names_error():
    """Test unique_node_names raises DuplicateNodeNamesError for duplicate names."""
    circuit_data = {
        "name": "test_circuit",
        "version": 1,
        "nodes": [
            {
                "name": "service_a",
                "host": "localhost",
                "port": 8080,
                "proxy_mode": ProxyMode.HTTP,
                "contract": "api.v1",
                "role": NodeRole.SERVICE,
                "management_port": 0,
                "metadata": {}
            },
            {
                "name": "service_a",  # Duplicate name
                "host": "localhost",
                "port": 8081,
                "proxy_mode": ProxyMode.HTTP,
                "contract": "api.v1",
                "role": NodeRole.SERVICE,
                "management_port": 0,
                "metadata": {}
            }
        ],
        "edges": []
    }
    
    with pytest.raises(Exception) as exc_info:
        CircuitSpec(**circuit_data)
    
    assert "duplicate" in str(exc_info.value).lower() or "unique" in str(exc_info.value).lower(), \
        f"Expected DuplicateNodeNamesError, got: {exc_info.value}"


# ============================================================================
# unique_ports Tests
# ============================================================================

def test_unique_ports_happy_path(valid_circuit_spec_data):
    """Test unique_ports allows circuit with unique node ports."""
    circuit = CircuitSpec(**valid_circuit_spec_data)
    
    ports = [node.port for node in circuit.nodes]
    assert len(ports) == len(set(ports)), \
        "All node ports should be unique"


def test_unique_ports_error():
    """Test unique_ports raises DuplicatePortsError for duplicate ports."""
    circuit_data = {
        "name": "test_circuit",
        "version": 1,
        "nodes": [
            {
                "name": "service_a",
                "host": "localhost",
                "port": 8080,
                "proxy_mode": ProxyMode.HTTP,
                "contract": "api.v1",
                "role": NodeRole.SERVICE,
                "management_port": 0,
                "metadata": {}
            },
            {
                "name": "service_b",
                "host": "localhost",
                "port": 8080,  # Duplicate port
                "proxy_mode": ProxyMode.HTTP,
                "contract": "api.v1",
                "role": NodeRole.SERVICE,
                "management_port": 0,
                "metadata": {}
            }
        ],
        "edges": []
    }
    
    with pytest.raises(Exception) as exc_info:
        CircuitSpec(**circuit_data)
    
    assert "port" in str(exc_info.value).lower() and \
           ("duplicate" in str(exc_info.value).lower() or "unique" in str(exc_info.value).lower()), \
        f"Expected DuplicatePortsError, got: {exc_info.value}"


# ============================================================================
# egress_not_edge_source Tests
# ============================================================================

def test_egress_not_edge_source_happy_path(valid_circuit_spec_data):
    """Test egress_not_edge_source allows egress nodes only as edge targets."""
    # Default circuit has egress only as target
    circuit = CircuitSpec(**valid_circuit_spec_data)
    
    egress_names = {node.name for node in circuit.nodes if node.role == NodeRole.EGRESS}
    source_names = {edge.source for edge in circuit.edges}
    
    assert not egress_names.intersection(source_names), \
        "Egress nodes should not be edge sources"


def test_egress_not_edge_source_error():
    """Test egress_not_edge_source raises EgressAsSourceError when egress is edge source."""
    circuit_data = {
        "name": "test_circuit",
        "version": 1,
        "nodes": [
            {
                "name": "service_a",
                "host": "localhost",
                "port": 8080,
                "proxy_mode": ProxyMode.HTTP,
                "contract": "api.v1",
                "role": NodeRole.SERVICE,
                "management_port": 0,
                "metadata": {}
            },
            {
                "name": "egress",
                "host": "localhost",
                "port": 8081,
                "proxy_mode": ProxyMode.TCP,
                "contract": "tcp.v1",
                "role": NodeRole.EGRESS,
                "management_port": 0,
                "metadata": {}
            }
        ],
        "edges": [
            {"source": "egress", "target": "service_a", "label": "invalid"}  # Egress as source
        ]
    }
    
    with pytest.raises(Exception) as exc_info:
        CircuitSpec(**circuit_data)
    
    assert "egress" in str(exc_info.value).lower() and "source" in str(exc_info.value).lower(), \
        f"Expected EgressAsSourceError, got: {exc_info.value}"


# ============================================================================
# edges_reference_existing_nodes Tests
# ============================================================================

def test_edges_reference_existing_nodes_happy_path(valid_circuit_spec_data):
    """Test edges_reference_existing_nodes allows valid edge references."""
    circuit = CircuitSpec(**valid_circuit_spec_data)
    
    node_names = {node.name for node in circuit.nodes}
    for edge in circuit.edges:
        assert edge.source in node_names, f"Edge source {edge.source} should exist in nodes"
        assert edge.target in node_names, f"Edge target {edge.target} should exist in nodes"


def test_edges_reference_existing_nodes_source_not_found():
    """Test edges_reference_existing_nodes raises EdgeSourceNotFoundError for invalid source."""
    circuit_data = {
        "name": "test_circuit",
        "version": 1,
        "nodes": [
            {
                "name": "service_a",
                "host": "localhost",
                "port": 8080,
                "proxy_mode": ProxyMode.HTTP,
                "contract": "api.v1",
                "role": NodeRole.SERVICE,
                "management_port": 0,
                "metadata": {}
            }
        ],
        "edges": [
            {"source": "nonexistent", "target": "service_a", "label": "invalid"}
        ]
    }
    
    with pytest.raises(Exception) as exc_info:
        CircuitSpec(**circuit_data)
    
    assert "source" in str(exc_info.value).lower() and \
           ("not found" in str(exc_info.value).lower() or "exist" in str(exc_info.value).lower()), \
        f"Expected EdgeSourceNotFoundError, got: {exc_info.value}"


def test_edges_reference_existing_nodes_target_not_found():
    """Test edges_reference_existing_nodes raises EdgeTargetNotFoundError for invalid target."""
    circuit_data = {
        "name": "test_circuit",
        "version": 1,
        "nodes": [
            {
                "name": "service_a",
                "host": "localhost",
                "port": 8080,
                "proxy_mode": ProxyMode.HTTP,
                "contract": "api.v1",
                "role": NodeRole.SERVICE,
                "management_port": 0,
                "metadata": {}
            }
        ],
        "edges": [
            {"source": "service_a", "target": "nonexistent", "label": "invalid"}
        ]
    }
    
    with pytest.raises(Exception) as exc_info:
        CircuitSpec(**circuit_data)
    
    assert "target" in str(exc_info.value).lower() and \
           ("not found" in str(exc_info.value).lower() or "exist" in str(exc_info.value).lower()), \
        f"Expected EdgeTargetNotFoundError, got: {exc_info.value}"


# ============================================================================
# node_by_name Tests
# ============================================================================

def test_node_by_name_found(valid_circuit_spec_data):
    """Test node_by_name returns NodeSpec when node exists."""
    circuit = CircuitSpec(**valid_circuit_spec_data)
    
    node = circuit.node_by_name("service_a")
    
    assert node is not None, "Node should be found"
    assert node.name == "service_a", f"Expected node name 'service_a', got {node.name}"
    assert isinstance(node, NodeSpec), "Should return NodeSpec instance"


def test_node_by_name_not_found(valid_circuit_spec_data):
    """Test node_by_name returns None when node does not exist."""
    circuit = CircuitSpec(**valid_circuit_spec_data)
    
    node = circuit.node_by_name("nonexistent")
    
    assert node is None, "Should return None for nonexistent node"


# ============================================================================
# neighbors Tests
# ============================================================================

def test_neighbors_returns_targets(valid_circuit_spec_data):
    """Test neighbors returns list of outbound edge targets."""
    # Modify to have service_a connect to multiple targets
    valid_circuit_spec_data["nodes"].append({
        "name": "service_b",
        "host": "localhost",
        "port": 8083,
        "proxy_mode": ProxyMode.HTTP,
        "contract": "api.v1",
        "role": NodeRole.SERVICE,
        "management_port": 0,
        "metadata": {}
    })
    valid_circuit_spec_data["edges"] = [
        {"source": "ingress", "target": "service_a", "label": "http"},
        {"source": "service_a", "target": "egress", "label": "tcp"},
        {"source": "service_a", "target": "service_b", "label": "http"}
    ]
    
    circuit = CircuitSpec(**valid_circuit_spec_data)
    neighbors = circuit.neighbors("service_a")
    
    assert set(neighbors) == {"egress", "service_b"}, \
        f"Expected neighbors ['egress', 'service_b'], got {neighbors}"


def test_neighbors_no_edges(valid_circuit_spec_data):
    """Test neighbors returns empty list when node has no outbound edges."""
    circuit = CircuitSpec(**valid_circuit_spec_data)
    
    neighbors = circuit.neighbors("egress")
    
    assert neighbors == [], f"Expected empty list for node with no outbound edges, got {neighbors}"


# ============================================================================
# dependents Tests
# ============================================================================

def test_dependents_returns_sources(valid_circuit_spec_data):
    """Test dependents returns list of inbound edge sources."""
    # Modify to have egress receive from multiple sources
    valid_circuit_spec_data["nodes"].append({
        "name": "service_b",
        "host": "localhost",
        "port": 8083,
        "proxy_mode": ProxyMode.HTTP,
        "contract": "api.v1",
        "role": NodeRole.SERVICE,
        "management_port": 0,
        "metadata": {}
    })
    valid_circuit_spec_data["edges"] = [
        {"source": "ingress", "target": "service_a", "label": "http"},
        {"source": "service_a", "target": "egress", "label": "tcp"},
        {"source": "service_b", "target": "egress", "label": "tcp"}
    ]
    
    circuit = CircuitSpec(**valid_circuit_spec_data)
    dependents = circuit.dependents("egress")
    
    assert set(dependents) == {"service_a", "service_b"}, \
        f"Expected dependents ['service_a', 'service_b'], got {dependents}"


def test_dependents_no_edges(valid_circuit_spec_data):
    """Test dependents returns empty list when node has no inbound edges."""
    circuit = CircuitSpec(**valid_circuit_spec_data)
    
    dependents = circuit.dependents("ingress")
    
    assert dependents == [], f"Expected empty list for node with no inbound edges, got {dependents}"


# ============================================================================
# ingress_nodes Tests
# ============================================================================

def test_ingress_nodes_property(valid_circuit_spec_data):
    """Test ingress_nodes returns all nodes with INGRESS role."""
    circuit = CircuitSpec(**valid_circuit_spec_data)
    
    ingress_nodes = circuit.ingress_nodes()
    
    assert len(ingress_nodes) == 1, f"Expected 1 ingress node, got {len(ingress_nodes)}"
    assert all(node.role == NodeRole.INGRESS for node in ingress_nodes), \
        "All returned nodes should have INGRESS role"
    assert ingress_nodes[0].name == "ingress", \
        f"Expected ingress node named 'ingress', got {ingress_nodes[0].name}"


def test_ingress_nodes_empty():
    """Test ingress_nodes returns empty list when no INGRESS nodes."""
    circuit_data = {
        "name": "test_circuit",
        "version": 1,
        "nodes": [
            {
                "name": "service_a",
                "host": "localhost",
                "port": 8080,
                "proxy_mode": ProxyMode.HTTP,
                "contract": "api.v1",
                "role": NodeRole.SERVICE,
                "management_port": 0,
                "metadata": {}
            }
        ],
        "edges": []
    }
    
    circuit = CircuitSpec(**circuit_data)
    ingress_nodes = circuit.ingress_nodes()
    
    assert ingress_nodes == [], f"Expected empty list when no INGRESS nodes, got {ingress_nodes}"


# ============================================================================
# egress_nodes Tests
# ============================================================================

def test_egress_nodes_property(valid_circuit_spec_data):
    """Test egress_nodes returns all nodes with EGRESS role."""
    circuit = CircuitSpec(**valid_circuit_spec_data)
    
    egress_nodes = circuit.egress_nodes()
    
    assert len(egress_nodes) == 1, f"Expected 1 egress node, got {len(egress_nodes)}"
    assert all(node.role == NodeRole.EGRESS for node in egress_nodes), \
        "All returned nodes should have EGRESS role"
    assert egress_nodes[0].name == "egress", \
        f"Expected egress node named 'egress', got {egress_nodes[0].name}"


def test_egress_nodes_empty():
    """Test egress_nodes returns empty list when no EGRESS nodes."""
    circuit_data = {
        "name": "test_circuit",
        "version": 1,
        "nodes": [
            {
                "name": "service_a",
                "host": "localhost",
                "port": 8080,
                "proxy_mode": ProxyMode.HTTP,
                "contract": "api.v1",
                "role": NodeRole.SERVICE,
                "management_port": 0,
                "metadata": {}
            }
        ],
        "edges": []
    }
    
    circuit = CircuitSpec(**circuit_data)
    egress_nodes = circuit.egress_nodes()
    
    assert egress_nodes == [], f"Expected empty list when no EGRESS nodes, got {egress_nodes}"


# ============================================================================
# weights_sum_to_100 Tests
# ============================================================================

def test_weights_sum_to_100_weighted_strategy(valid_routing_config_data):
    """Test weights_sum_to_100 allows WEIGHTED strategy with weights summing to 100."""
    valid_routing_config_data["strategy"] = RoutingStrategy.WEIGHTED
    valid_routing_config_data["targets"] = [
        {"name": "primary", "host": "localhost", "port": 8080, "weight": 60},
        {"name": "secondary", "host": "localhost", "port": 8081, "weight": 40}
    ]
    
    config = RoutingConfig(**valid_routing_config_data)
    
    total_weight = sum(t.weight for t in config.targets)
    assert total_weight == 100, f"Expected total weight 100, got {total_weight}"


def test_weights_sum_to_100_canary_strategy(valid_routing_config_data):
    """Test weights_sum_to_100 allows CANARY strategy with weights summing to 100."""
    valid_routing_config_data["strategy"] = RoutingStrategy.CANARY
    valid_routing_config_data["targets"] = [
        {"name": "stable", "host": "localhost", "port": 8080, "weight": 90},
        {"name": "canary", "host": "localhost", "port": 8081, "weight": 10}
    ]
    
    config = RoutingConfig(**valid_routing_config_data)
    
    total_weight = sum(t.weight for t in config.targets)
    assert total_weight == 100, f"Expected total weight 100, got {total_weight}"


def test_weights_sum_to_100_with_zero_weights(valid_routing_config_data):
    """Test weights_sum_to_100 allows zero weights if non-zero weights sum to 100."""
    valid_routing_config_data["strategy"] = RoutingStrategy.WEIGHTED
    valid_routing_config_data["targets"] = [
        {"name": "primary", "host": "localhost", "port": 8080, "weight": 100},
        {"name": "secondary", "host": "localhost", "port": 8081, "weight": 0}
    ]
    
    config = RoutingConfig(**valid_routing_config_data)
    
    non_zero_weights = [t.weight for t in config.targets if t.weight > 0]
    assert sum(non_zero_weights) == 100, \
        f"Expected non-zero weights to sum to 100, got {sum(non_zero_weights)}"


def test_weights_sum_to_100_error_invalid_sum(valid_routing_config_data):
    """Test weights_sum_to_100 raises WeightSumError when weights don't sum to 100."""
    valid_routing_config_data["strategy"] = RoutingStrategy.WEIGHTED
    valid_routing_config_data["targets"] = [
        {"name": "primary", "host": "localhost", "port": 8080, "weight": 60},
        {"name": "secondary", "host": "localhost", "port": 8081, "weight": 50}
    ]
    
    with pytest.raises(Exception) as exc_info:
        RoutingConfig(**valid_routing_config_data)
    
    assert "weight" in str(exc_info.value).lower() and \
           ("sum" in str(exc_info.value).lower() or "100" in str(exc_info.value)), \
        f"Expected WeightSumError, got: {exc_info.value}"


def test_weights_sum_to_100_single_strategy_ignored(valid_routing_config_data):
    """Test weights_sum_to_100 ignores weight validation for SINGLE strategy."""
    valid_routing_config_data["strategy"] = RoutingStrategy.SINGLE
    valid_routing_config_data["targets"] = [
        {"name": "primary", "host": "localhost", "port": 8080, "weight": 50}  # Not 100
    ]
    
    # Should not raise error for SINGLE strategy
    config = RoutingConfig(**valid_routing_config_data)
    
    assert config.strategy == RoutingStrategy.SINGLE


# ============================================================================
# header_requires_rules Tests
# ============================================================================

def test_header_requires_rules_happy_path(valid_routing_config_data):
    """Test header_requires_rules allows HEADER strategy with rules and default_target."""
    valid_routing_config_data["strategy"] = RoutingStrategy.HEADER
    valid_routing_config_data["targets"] = [
        {"name": "v1", "host": "localhost", "port": 8080, "weight": 0},
        {"name": "v2", "host": "localhost", "port": 8081, "weight": 0}
    ]
    valid_routing_config_data["rules"] = [
        {"header": "X-API-Version", "value": "v2", "target": "v2"}
    ]
    valid_routing_config_data["default_target"] = "v1"
    
    config = RoutingConfig(**valid_routing_config_data)
    
    assert config.strategy == RoutingStrategy.HEADER
    assert len(config.rules) > 0
    assert config.default_target != ""


def test_header_requires_rules_error_no_rules(valid_routing_config_data):
    """Test header_requires_rules raises NoRulesError when HEADER strategy has no rules."""
    valid_routing_config_data["strategy"] = RoutingStrategy.HEADER
    valid_routing_config_data["targets"] = [
        {"name": "v1", "host": "localhost", "port": 8080, "weight": 0}
    ]
    valid_routing_config_data["rules"] = []  # Empty rules
    valid_routing_config_data["default_target"] = "v1"
    
    with pytest.raises(Exception) as exc_info:
        RoutingConfig(**valid_routing_config_data)
    
    assert "rule" in str(exc_info.value).lower(), \
        f"Expected NoRulesError, got: {exc_info.value}"


def test_header_requires_rules_error_no_default(valid_routing_config_data):
    """Test header_requires_rules raises NoDefaultTargetError when HEADER strategy missing default_target."""
    valid_routing_config_data["strategy"] = RoutingStrategy.HEADER
    valid_routing_config_data["targets"] = [
        {"name": "v1", "host": "localhost", "port": 8080, "weight": 0}
    ]
    valid_routing_config_data["rules"] = [
        {"header": "X-API-Version", "value": "v1", "target": "v1"}
    ]
    valid_routing_config_data["default_target"] = ""  # Empty default
    
    with pytest.raises(Exception) as exc_info:
        RoutingConfig(**valid_routing_config_data)
    
    assert "default" in str(exc_info.value).lower(), \
        f"Expected NoDefaultTargetError, got: {exc_info.value}"


def test_header_requires_rules_non_header_strategy(valid_routing_config_data):
    """Test header_requires_rules ignores validation for non-HEADER strategies."""
    valid_routing_config_data["strategy"] = RoutingStrategy.SINGLE
    valid_routing_config_data["targets"] = [
        {"name": "primary", "host": "localhost", "port": 8080, "weight": 0}
    ]
    valid_routing_config_data["rules"] = []  # No rules for SINGLE strategy
    valid_routing_config_data["default_target"] = ""
    
    # Should not raise error for SINGLE strategy
    config = RoutingConfig(**valid_routing_config_data)
    
    assert config.strategy == RoutingStrategy.SINGLE


# ============================================================================
# no_duplicate_target_names Tests
# ============================================================================

def test_no_duplicate_target_names_happy_path(valid_routing_config_data):
    """Test no_duplicate_target_names allows unique target names."""
    valid_routing_config_data["targets"] = [
        {"name": "primary", "host": "localhost", "port": 8080, "weight": 60},
        {"name": "secondary", "host": "localhost", "port": 8081, "weight": 40}
    ]
    
    config = RoutingConfig(**valid_routing_config_data)
    
    target_names = [t.name for t in config.targets]
    assert len(target_names) == len(set(target_names)), \
        "All target names should be unique"


def test_no_duplicate_target_names_error(valid_routing_config_data):
    """Test no_duplicate_target_names raises DuplicateTargetNamesError for duplicate names."""
    valid_routing_config_data["targets"] = [
        {"name": "primary", "host": "localhost", "port": 8080, "weight": 50},
        {"name": "primary", "host": "localhost", "port": 8081, "weight": 50}  # Duplicate
    ]
    
    with pytest.raises(Exception) as exc_info:
        RoutingConfig(**valid_routing_config_data)
    
    assert "duplicate" in str(exc_info.value).lower() or "unique" in str(exc_info.value).lower(), \
        f"Expected DuplicateTargetNamesError, got: {exc_info.value}"


# ============================================================================
# Invariant Tests
# ============================================================================

def test_node_name_pattern_validation():
    """Test node names must match pattern ^[a-z][a-z0-9_-]*$."""
    valid_names = ["service", "service_a", "service-b", "s123", "api_gateway"]
    invalid_names = ["Service", "1service", "service.a", "service@", ""]
    
    for name in valid_names:
        node_data = {
            "name": name,
            "host": "localhost",
            "port": 8080,
            "proxy_mode": ProxyMode.HTTP,
            "contract": "api.v1",
            "role": NodeRole.SERVICE,
            "management_port": 0,
            "metadata": {}
        }
        # Should not raise
        node = NodeSpec(**node_data)
        assert node.name == name
    
    for name in invalid_names:
        node_data = {
            "name": name,
            "host": "localhost",
            "port": 8080,
            "proxy_mode": ProxyMode.HTTP,
            "contract": "api.v1",
            "role": NodeRole.SERVICE,
            "management_port": 0,
            "metadata": {}
        }
        with pytest.raises(Exception):
            NodeSpec(**node_data)


def test_port_range_validation():
    """Test node ports must be in range 1024-65535."""
    valid_ports = [1024, 8080, 65535]
    invalid_ports = [0, 1023, 65536, 100000, -1]
    
    for port in valid_ports:
        node_data = {
            "name": "service_a",
            "host": "localhost",
            "port": port,
            "proxy_mode": ProxyMode.HTTP,
            "contract": "api.v1",
            "role": NodeRole.SERVICE,
            "management_port": 0,
            "metadata": {}
        }
        # Should not raise
        node = NodeSpec(**node_data)
        assert node.port == port
    
    for port in invalid_ports:
        node_data = {
            "name": "service_a",
            "host": "localhost",
            "port": port,
            "proxy_mode": ProxyMode.HTTP,
            "contract": "api.v1",
            "role": NodeRole.SERVICE,
            "management_port": 0,
            "metadata": {}
        }
        with pytest.raises(Exception):
            NodeSpec(**node_data)


def test_routing_weight_range_validation():
    """Test routing target weights must be in range 0-100."""
    valid_weights = [0, 50, 100]
    invalid_weights = [-1, 101, 200, -50]
    
    for weight in valid_weights:
        target_data = {
            "name": "primary",
            "host": "localhost",
            "port": 8080,
            "weight": weight
        }
        # Should not raise
        target = RoutingTarget(**target_data)
        assert target.weight == weight
    
    for weight in invalid_weights:
        target_data = {
            "name": "primary",
            "host": "localhost",
            "port": 8080,
            "weight": weight
        }
        with pytest.raises(Exception):
            RoutingTarget(**target_data)


def test_struct_immutability():
    """Test frozen structs are immutable after creation."""
    node_data = {
        "name": "service_a",
        "host": "localhost",
        "port": 8080,
        "proxy_mode": ProxyMode.HTTP,
        "contract": "api.v1",
        "role": NodeRole.SERVICE,
        "management_port": 0,
        "metadata": {}
    }
    
    node = NodeSpec(**node_data)
    
    # Attempt to modify should raise error
    with pytest.raises(Exception):
        node.port = 9090
    
    with pytest.raises(Exception):
        node.name = "new_name"


# ============================================================================
# Complex Integration Tests
# ============================================================================

def test_complex_circuit_topology():
    """Test complex circuit with multiple node types and edges."""
    circuit_data = {
        "name": "complex_circuit",
        "version": 1,
        "nodes": [
            {
                "name": "ingress_http",
                "host": "localhost",
                "port": 8080,
                "proxy_mode": ProxyMode.HTTP,
                "contract": "api.v1",
                "role": NodeRole.INGRESS,
                "management_port": 0,
                "metadata": {}
            },
            {
                "name": "service_a",
                "host": "localhost",
                "port": 8081,
                "proxy_mode": ProxyMode.HTTP,
                "contract": "api.v1",
                "role": NodeRole.SERVICE,
                "management_port": 0,
                "metadata": {}
            },
            {
                "name": "service_b",
                "host": "localhost",
                "port": 8082,
                "proxy_mode": ProxyMode.HTTP,
                "contract": "api.v1",
                "role": NodeRole.SERVICE,
                "management_port": 0,
                "metadata": {}
            },
            {
                "name": "egress_db",
                "host": "localhost",
                "port": 5432,
                "proxy_mode": ProxyMode.TCP,
                "contract": "postgres",
                "role": NodeRole.EGRESS,
                "management_port": 0,
                "metadata": {}
            }
        ],
        "edges": [
            {"source": "ingress_http", "target": "service_a", "label": "http"},
            {"source": "service_a", "target": "service_b", "label": "http"},
            {"source": "service_a", "target": "egress_db", "label": "tcp"},
            {"source": "service_b", "target": "egress_db", "label": "tcp"}
        ]
    }
    
    circuit = CircuitSpec(**circuit_data)
    
    # Test ingress nodes
    ingress_nodes = circuit.ingress_nodes()
    assert len(ingress_nodes) == 1
    assert ingress_nodes[0].name == "ingress_http"
    
    # Test egress nodes
    egress_nodes = circuit.egress_nodes()
    assert len(egress_nodes) == 1
    assert egress_nodes[0].name == "egress_db"
    
    # Test neighbors
    service_a_neighbors = circuit.neighbors("service_a")
    assert set(service_a_neighbors) == {"service_b", "egress_db"}
    
    # Test dependents
    egress_dependents = circuit.dependents("egress_db")
    assert set(egress_dependents) == {"service_a", "service_b"}
    
    # Test node lookup
    node = circuit.node_by_name("service_b")
    assert node is not None
    assert node.port == 8082


def test_empty_circuit():
    """Test circuit with no nodes or edges."""
    circuit_data = {
        "name": "empty_circuit",
        "version": 1,
        "nodes": [],
        "edges": []
    }
    
    circuit = CircuitSpec(**circuit_data)
    
    assert circuit.node_by_name("any") is None
    assert circuit.neighbors("any") == []
    assert circuit.dependents("any") == []
    assert circuit.ingress_nodes() == []
    assert circuit.egress_nodes() == []


# ============================================================================
# Enum Validation Tests
# ============================================================================

@pytest.mark.parametrize("status", [
    NodeStatus.IDLE,
    NodeStatus.LISTENING,
    NodeStatus.ACTIVE,
    NodeStatus.DRAINING,
    NodeStatus.FAULTED
])
def test_node_status_enum_values(status):
    """Test all NodeStatus enum values are valid."""
    # Create an AdapterState with each status
    state_data = {
        "node_name": "test_node",
        "status": status,
        "adapter_pid": 12345,
        "service": {
            "command": "python app.py",
            "is_mock": False,
            "pid": 0,
            "started_at": ""
        },
        "last_health_check": "",
        "last_health_verdict": HealthVerdict.UNKNOWN,
        "consecutive_failures": 0,
        "routing_config": None
    }
    
    state = AdapterState(**state_data)
    assert state.status == status


@pytest.mark.parametrize("mode", [ProxyMode.HTTP, ProxyMode.TCP])
def test_proxy_mode_enum_values(mode):
    """Test all ProxyMode enum values are valid."""
    node_data = {
        "name": "test_node",
        "host": "localhost",
        "port": 8080,
        "proxy_mode": mode,
        "contract": "api.v1",
        "role": NodeRole.SERVICE,
        "management_port": 0,
        "metadata": {}
    }
    
    node = NodeSpec(**node_data)
    assert node.proxy_mode == mode


@pytest.mark.parametrize("role", [NodeRole.SERVICE, NodeRole.INGRESS, NodeRole.EGRESS])
def test_node_role_enum_values(role):
    """Test all NodeRole enum values are valid."""
    node_data = {
        "name": "test_node",
        "host": "localhost",
        "port": 8080,
        "proxy_mode": ProxyMode.HTTP,
        "contract": "api.v1",
        "role": role,
        "management_port": 0,
        "metadata": {}
    }
    
    node = NodeSpec(**node_data)
    assert node.role == role


@pytest.mark.parametrize("strategy", [
    RoutingStrategy.SINGLE,
    RoutingStrategy.WEIGHTED,
    RoutingStrategy.HEADER,
    RoutingStrategy.CANARY
])
def test_routing_strategy_enum_values(strategy):
    """Test all RoutingStrategy enum values are valid."""
    config_data = {
        "strategy": strategy,
        "targets": [{"name": "primary", "host": "localhost", "port": 8080, "weight": 100}],
        "rules": [],
        "default_target": "",
        "locked": False
    }
    
    # Special handling for HEADER strategy
    if strategy == RoutingStrategy.HEADER:
        config_data["rules"] = [{"header": "X-Test", "value": "v1", "target": "primary"}]
        config_data["default_target"] = "primary"
    
    config = RoutingConfig(**config_data)
    assert config.strategy == strategy


# ============================================================================
# Additional Edge Cases
# ============================================================================

def test_circuit_with_single_node():
    """Test circuit with single node and no edges."""
    circuit_data = {
        "name": "single_node_circuit",
        "version": 1,
        "nodes": [
            {
                "name": "standalone",
                "host": "localhost",
                "port": 8080,
                "proxy_mode": ProxyMode.HTTP,
                "contract": "api.v1",
                "role": NodeRole.SERVICE,
                "management_port": 0,
                "metadata": {}
            }
        ],
        "edges": []
    }
    
    circuit = CircuitSpec(**circuit_data)
    
    assert len(circuit.nodes) == 1
    assert circuit.neighbors("standalone") == []
    assert circuit.dependents("standalone") == []


def test_routing_config_all_zero_weights_error():
    """Test that all zero weights is invalid for WEIGHTED strategy."""
    config_data = {
        "strategy": RoutingStrategy.WEIGHTED,
        "targets": [
            {"name": "primary", "host": "localhost", "port": 8080, "weight": 0},
            {"name": "secondary", "host": "localhost", "port": 8081, "weight": 0}
        ],
        "rules": [],
        "default_target": "",
        "locked": False
    }
    
    with pytest.raises(Exception) as exc_info:
        RoutingConfig(**config_data)
    
    assert "weight" in str(exc_info.value).lower()


def test_metadata_fields_allow_arbitrary_strings():
    """Test that metadata fields accept arbitrary key-value pairs."""
    node_data = {
        "name": "service_a",
        "host": "localhost",
        "port": 8080,
        "proxy_mode": ProxyMode.HTTP,
        "contract": "api.v1",
        "role": NodeRole.SERVICE,
        "management_port": 0,
        "metadata": {
            "env": "production",
            "owner": "team-a",
            "custom_key": "custom_value"
        }
    }
    
    node = NodeSpec(**node_data)
    
    assert node.metadata["env"] == "production"
    assert node.metadata["owner"] == "team-a"
    assert node.metadata["custom_key"] == "custom_value"


def test_dependency_spec_optional_field():
    """Test DependencySpec with optional flag."""
    dep_data = {
        "name": "cache_service",
        "expected_api": "redis.v1",
        "optional": True
    }
    
    dep = DependencySpec(**dep_data)
    
    assert dep.name == "cache_service"
    assert dep.optional is True


def test_health_check_timestamp():
    """Test HealthCheck struct with timestamp."""
    now = datetime.utcnow().isoformat()
    
    health_data = {
        "node_name": "service_a",
        "verdict": HealthVerdict.HEALTHY,
        "latency_ms": 15.5,
        "detail": "All checks passed",
        "timestamp": now
    }
    
    health = HealthCheck(**health_data)
    
    assert health.verdict == HealthVerdict.HEALTHY
    assert health.latency_ms == 15.5
    assert health.timestamp == now


def test_signal_record_inbound_outbound():
    """Test SignalRecord with inbound and outbound directions."""
    for direction in ['inbound', 'outbound']:
        signal_data = {
            "node_name": "service_a",
            "direction": direction,
            "method": "GET",
            "path": "/api/users",
            "status_code": 200,
            "body_bytes": 1024,
            "latency_ms": 25.3,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        signal = SignalRecord(**signal_data)
        
        assert signal.direction == direction
        assert signal.method == "GET"
        assert signal.status_code == 200


def test_custodian_event_all_actions():
    """Test CustodianEvent with all action types."""
    actions = [
        CustodianAction.RESTART_SERVICE,
        CustodianAction.REPLACE_SERVICE,
        CustodianAction.BOOT_SECONDARY,
        CustodianAction.REROUTE,
        CustodianAction.ESCALATE
    ]
    
    for action in actions:
        event_data = {
            "node_name": "service_a",
            "action": action,
            "reason": "Health check failed",
            "success": True,
            "detail": "Action completed",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        event = CustodianEvent(**event_data)
        
        assert event.action == action
        assert event.success is True
