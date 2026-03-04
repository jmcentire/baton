"""
Contract-driven tests for Circuit Graph Operations (src_baton_circuit)

This test suite verifies the circuit graph operations contract implementation
using a layered testing strategy:
1. Unit Tests for CRUD Operations
2. State Transition Tests
3. Algorithm Verification Tests
4. Error Coverage Tests
5. Domain-Specific Tests
6. Invariant Tests
7. Integration Tests

All dependencies are mocked. Tests verify behavior at boundaries only.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from typing import List, Dict, Any
import random

# Import the component under test
from src.baton.circuit import *


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def empty_circuit():
    """Create an empty circuit for testing."""
    circuit = CircuitSpec(name="test_circuit", version=1, nodes=[], edges=[])
    return circuit


@pytest.fixture
def circuit_with_one_node():
    """Create a circuit with one node."""
    node = NodeSpec(name="node1", port=9001, proxy_mode="http", 
                    contract="contract1.yaml", role="client")
    circuit = CircuitSpec(name="test_circuit", version=1, 
                         nodes=[node], edges=[])
    return circuit


@pytest.fixture
def circuit_with_multiple_nodes():
    """Create a circuit with multiple nodes."""
    nodes = [
        NodeSpec(name="A", port=9001, proxy_mode="http", 
                contract="contract_a.yaml", role="client"),
        NodeSpec(name="B", port=9002, proxy_mode="http", 
                contract="contract_b.yaml", role="server"),
        NodeSpec(name="C", port=9003, proxy_mode="http", 
                contract="contract_c.yaml", role="client"),
    ]
    circuit = CircuitSpec(name="test_circuit", version=1, 
                         nodes=nodes, edges=[])
    return circuit


@pytest.fixture
def circuit_with_edges():
    """Create a circuit with nodes and edges forming a DAG."""
    nodes = [
        NodeSpec(name="A", port=9001, proxy_mode="http", 
                contract="contract_a.yaml", role="client"),
        NodeSpec(name="B", port=9002, proxy_mode="http", 
                contract="contract_b.yaml", role="server"),
        NodeSpec(name="C", port=9003, proxy_mode="http", 
                contract="contract_c.yaml", role="client"),
    ]
    edges = [
        EdgeSpec(source="A", target="B", label="edge1"),
        EdgeSpec(source="B", target="C", label="edge2"),
    ]
    circuit = CircuitSpec(name="test_circuit", version=1, 
                         nodes=nodes, edges=edges)
    return circuit


@pytest.fixture
def circuit_with_cycle():
    """Create a circuit with a cycle."""
    nodes = [
        NodeSpec(name="A", port=9001, proxy_mode="http", 
                contract="contract_a.yaml", role="client"),
        NodeSpec(name="B", port=9002, proxy_mode="http", 
                contract="contract_b.yaml", role="server"),
        NodeSpec(name="C", port=9003, proxy_mode="http", 
                contract="contract_c.yaml", role="client"),
    ]
    edges = [
        EdgeSpec(source="A", target="B", label="edge1"),
        EdgeSpec(source="B", target="C", label="edge2"),
        EdgeSpec(source="C", target="A", label="edge3"),
    ]
    circuit = CircuitSpec(name="test_circuit", version=1, 
                         nodes=nodes, edges=edges)
    return circuit


@pytest.fixture
def circuit_nearly_full_ports():
    """Create a circuit with ports 9001-9998 occupied (one port left)."""
    nodes = [
        NodeSpec(name=f"node{i}", port=9000+i, proxy_mode="http",
                contract=f"contract{i}.yaml", role="client")
        for i in range(1, 999)  # 9001 to 9998
    ]
    circuit = CircuitSpec(name="test_circuit", version=1,
                         nodes=nodes, edges=[])
    return circuit


@pytest.fixture
def circuit_full_ports():
    """Create a circuit with all ports 9001-9999 occupied."""
    nodes = [
        NodeSpec(name=f"node{i}", port=9000+i, proxy_mode="http",
                contract=f"contract{i}.yaml", role="client")
        for i in range(1, 1000)  # 9001 to 9999
    ]
    circuit = CircuitSpec(name="test_circuit", version=1,
                         nodes=nodes, edges=[])
    return circuit


# ============================================================================
# Layer 1: Unit Tests for CRUD Operations - add_node
# ============================================================================

def test_add_node_happy_path_explicit_port(empty_circuit):
    """Add a node with explicitly specified port to an empty circuit."""
    result = add_node(empty_circuit, name="node1", port=9001, 
                     proxy_mode="http", contract="contract1.yaml", 
                     role="client")
    
    # New circuit contains the added node
    assert len(result.nodes) == 1, "New circuit should have 1 node"
    assert result.nodes[0].name == "node1", "Node name should be 'node1'"
    assert result.nodes[0].port == 9001, "Node port should be 9001"
    
    # Original circuit is unchanged
    assert len(empty_circuit.nodes) == 0, "Original circuit should remain empty"
    
    # New circuit has same name and version
    assert result.name == empty_circuit.name, "Circuit name should be preserved"
    assert result.version == empty_circuit.version, "Circuit version should be preserved"
    
    # Node has correct attributes
    assert result.nodes[0].proxy_mode == "http", "proxy_mode should be 'http'"
    assert result.nodes[0].contract == "contract1.yaml", "contract should match"
    assert result.nodes[0].role == "client", "role should be 'client'"


def test_add_node_happy_path_auto_port(empty_circuit):
    """Add a node with auto-assigned port (port=0)."""
    result = add_node(empty_circuit, name="node1", port=0,
                     proxy_mode="http", contract="contract1.yaml",
                     role="server")
    
    # Node is assigned port 9001 (first available)
    assert result.nodes[0].port == 9001, "First auto-assigned port should be 9001"
    
    # Original circuit is unchanged
    assert len(empty_circuit.nodes) == 0, "Original circuit should remain unchanged"


def test_add_node_error_duplicate_node(circuit_with_one_node):
    """Adding a node with duplicate name raises duplicate_node error."""
    with pytest.raises(Exception) as exc_info:
        add_node(circuit_with_one_node, name="node1", port=9002,
                proxy_mode="http", contract="contract2.yaml",
                role="server")
    
    # Raises exception with duplicate_node error
    assert "duplicate_node" in str(exc_info.value).lower() or \
           "duplicate" in str(exc_info.value).lower() or \
           "already exists" in str(exc_info.value).lower(), \
           "Should raise duplicate_node error"


def test_add_node_error_no_available_port(circuit_full_ports):
    """Adding a node with auto-port when all ports are used raises no_available_port error."""
    with pytest.raises(Exception) as exc_info:
        add_node(circuit_full_ports, name="new_node", port=0,
                proxy_mode="http", contract="contract.yaml",
                role="client")
    
    # Raises exception with no_available_port error
    assert "no_available_port" in str(exc_info.value).lower() or \
           "no available" in str(exc_info.value).lower() or \
           "port" in str(exc_info.value).lower(), \
           "Should raise no_available_port error"


def test_add_node_edge_case_last_available_port(circuit_nearly_full_ports):
    """Add node with auto-port when only one port remains (9999)."""
    result = add_node(circuit_nearly_full_ports, name="last_node", port=0,
                     proxy_mode="http", contract="contract.yaml",
                     role="client")
    
    # Node is assigned port 9999
    new_node = [n for n in result.nodes if n.name == "last_node"][0]
    assert new_node.port == 9999, "Last available port should be 9999"


def test_add_node_preserves_existing_nodes(circuit_with_one_node):
    """Adding a node preserves all existing nodes."""
    result = add_node(circuit_with_one_node, name="node2", port=9002,
                     proxy_mode="http", contract="contract2.yaml",
                     role="server")
    
    assert len(result.nodes) == 2, "Should have 2 nodes"
    node_names = [n.name for n in result.nodes]
    assert "node1" in node_names, "Original node should be preserved"
    assert "node2" in node_names, "New node should be added"


# ============================================================================
# Layer 1: Unit Tests for CRUD Operations - remove_node
# ============================================================================

def test_remove_node_happy_path(circuit_with_one_node):
    """Remove an existing node from circuit."""
    result = remove_node(circuit_with_one_node, name="node1")
    
    # Node is removed from new circuit
    assert len(result.nodes) == 0, "Node should be removed"
    
    # Original circuit is unchanged
    assert len(circuit_with_one_node.nodes) == 1, "Original circuit unchanged"
    
    # Name and version preserved
    assert result.name == circuit_with_one_node.name, "Name preserved"
    assert result.version == circuit_with_one_node.version, "Version preserved"


def test_remove_node_error_not_found(empty_circuit):
    """Removing non-existent node raises node_not_found error."""
    with pytest.raises(Exception) as exc_info:
        remove_node(empty_circuit, name="nonexistent")
    
    # Raises exception with node_not_found error
    assert "node_not_found" in str(exc_info.value).lower() or \
           "not found" in str(exc_info.value).lower() or \
           "does not exist" in str(exc_info.value).lower(), \
           "Should raise node_not_found error"


def test_remove_node_removes_edges(circuit_with_edges):
    """Removing a node also removes all edges connected to it."""
    result = remove_node(circuit_with_edges, name="B")
    
    # Node B is removed
    node_names = [n.name for n in result.nodes]
    assert "B" not in node_names, "Node B should be removed"
    
    # Edges involving B are removed
    edge_sources = [e.source for e in result.edges]
    edge_targets = [e.target for e in result.edges]
    assert "B" not in edge_sources, "No edges should have B as source"
    assert "B" not in edge_targets, "No edges should have B as target"
    
    # Other nodes and edges remain
    assert "A" in node_names, "Node A should remain"
    assert "C" in node_names, "Node C should remain"


def test_remove_node_from_multiple(circuit_with_multiple_nodes):
    """Remove one node from circuit with multiple nodes."""
    result = remove_node(circuit_with_multiple_nodes, name="B")
    
    assert len(result.nodes) == 2, "Should have 2 nodes remaining"
    node_names = [n.name for n in result.nodes]
    assert "A" in node_names and "C" in node_names, "A and C should remain"
    assert "B" not in node_names, "B should be removed"


# ============================================================================
# Layer 1: Unit Tests for CRUD Operations - add_edge
# ============================================================================

def test_add_edge_happy_path(circuit_with_multiple_nodes):
    """Add an edge between two existing nodes."""
    result = add_edge(circuit_with_multiple_nodes, source="A", 
                     target="B", label="connects")
    
    # Edge exists in new circuit
    assert len(result.edges) == 1, "Should have 1 edge"
    assert result.edges[0].source == "A", "Edge source should be A"
    assert result.edges[0].target == "B", "Edge target should be B"
    assert result.edges[0].label == "connects", "Edge label should be 'connects'"
    
    # Original circuit unchanged
    assert len(circuit_with_multiple_nodes.edges) == 0, "Original unchanged"
    
    # All nodes remain unchanged
    assert len(result.nodes) == len(circuit_with_multiple_nodes.nodes), \
           "Node count unchanged"


def test_add_edge_error_source_not_found(circuit_with_one_node):
    """Adding edge with non-existent source raises source_not_found error."""
    with pytest.raises(Exception) as exc_info:
        add_edge(circuit_with_one_node, source="nonexistent", 
                target="node1", label="edge")
    
    # Raises exception with source_not_found error
    assert "source" in str(exc_info.value).lower() and \
           ("not found" in str(exc_info.value).lower() or \
            "does not exist" in str(exc_info.value).lower()), \
           "Should raise source_not_found error"


def test_add_edge_error_target_not_found(circuit_with_one_node):
    """Adding edge with non-existent target raises target_not_found error."""
    with pytest.raises(Exception) as exc_info:
        add_edge(circuit_with_one_node, source="node1", 
                target="nonexistent", label="edge")
    
    # Raises exception with target_not_found error
    assert "target" in str(exc_info.value).lower() and \
           ("not found" in str(exc_info.value).lower() or \
            "does not exist" in str(exc_info.value).lower()), \
           "Should raise target_not_found error"


def test_add_edge_error_duplicate_edge(circuit_with_edges):
    """Adding duplicate edge raises duplicate_edge error."""
    with pytest.raises(Exception) as exc_info:
        add_edge(circuit_with_edges, source="A", target="B", label="dup")
    
    # Raises exception with duplicate_edge error
    assert "duplicate" in str(exc_info.value).lower() or \
           "already exists" in str(exc_info.value).lower(), \
           "Should raise duplicate_edge error"


def test_add_edge_allows_reverse_direction(circuit_with_edges):
    """Adding edge in reverse direction is allowed (directed graph)."""
    # Circuit has A->B, adding B->A should work
    result = add_edge(circuit_with_edges, source="B", target="A", 
                     label="reverse")
    
    assert len(result.edges) == 3, "Should have 3 edges total"
    edge_pairs = [(e.source, e.target) for e in result.edges]
    assert ("A", "B") in edge_pairs, "Original A->B should exist"
    assert ("B", "A") in edge_pairs, "Reverse B->A should exist"


# ============================================================================
# Layer 1: Unit Tests for CRUD Operations - remove_edge
# ============================================================================

def test_remove_edge_happy_path(circuit_with_edges):
    """Remove an existing edge from circuit."""
    result = remove_edge(circuit_with_edges, source="A", target="B")
    
    # Edge is removed from new circuit
    edge_pairs = [(e.source, e.target) for e in result.edges]
    assert ("A", "B") not in edge_pairs, "Edge A->B should be removed"
    
    # Original circuit unchanged
    assert len(circuit_with_edges.edges) == 2, "Original unchanged"
    
    # Nodes remain unchanged
    assert len(result.nodes) == len(circuit_with_edges.nodes), \
           "All nodes should remain"


def test_remove_edge_error_not_found(circuit_with_multiple_nodes):
    """Removing non-existent edge raises edge_not_found error."""
    with pytest.raises(Exception) as exc_info:
        remove_edge(circuit_with_multiple_nodes, source="A", target="B")
    
    # Raises exception with edge_not_found error
    assert "edge" in str(exc_info.value).lower() and \
           ("not found" in str(exc_info.value).lower() or \
            "does not exist" in str(exc_info.value).lower()), \
           "Should raise edge_not_found error"


def test_remove_edge_keeps_other_edges(circuit_with_edges):
    """Removing one edge keeps other edges intact."""
    result = remove_edge(circuit_with_edges, source="A", target="B")
    
    assert len(result.edges) == 1, "Should have 1 edge remaining"
    assert result.edges[0].source == "B", "Remaining edge source is B"
    assert result.edges[0].target == "C", "Remaining edge target is C"


# ============================================================================
# Layer 1: Unit Tests for CRUD Operations - set_contract
# ============================================================================

def test_set_contract_happy_path(circuit_with_one_node):
    """Update contract path for an existing node."""
    result = set_contract(circuit_with_one_node, node_name="node1",
                         contract_path="new_contract.yaml")
    
    # Node contract is updated
    assert result.nodes[0].contract == "new_contract.yaml", \
           "Contract should be updated"
    
    # Original circuit unchanged
    assert circuit_with_one_node.nodes[0].contract == "contract1.yaml", \
           "Original contract unchanged"
    
    # Other node fields unchanged
    assert result.nodes[0].name == "node1", "Name unchanged"
    assert result.nodes[0].port == 9001, "Port unchanged"
    assert result.nodes[0].proxy_mode == "http", "Proxy mode unchanged"
    assert result.nodes[0].role == "client", "Role unchanged"
    
    # All edges unchanged (though this circuit has no edges)
    assert len(result.edges) == len(circuit_with_one_node.edges), \
           "Edge count unchanged"


def test_set_contract_error_not_found(empty_circuit):
    """Setting contract for non-existent node raises node_not_found error."""
    with pytest.raises(Exception) as exc_info:
        set_contract(empty_circuit, node_name="nonexistent",
                    contract_path="contract.yaml")
    
    # Raises exception with node_not_found error
    assert "node_not_found" in str(exc_info.value).lower() or \
           "not found" in str(exc_info.value).lower() or \
           "does not exist" in str(exc_info.value).lower(), \
           "Should raise node_not_found error"


def test_set_contract_in_multi_node_circuit(circuit_with_multiple_nodes):
    """Set contract for one node in multi-node circuit."""
    result = set_contract(circuit_with_multiple_nodes, node_name="B",
                         contract_path="updated_b.yaml")
    
    # Find the updated node
    node_b = [n for n in result.nodes if n.name == "B"][0]
    assert node_b.contract == "updated_b.yaml", "Node B contract updated"
    
    # Other nodes unchanged
    node_a = [n for n in result.nodes if n.name == "A"][0]
    node_c = [n for n in result.nodes if n.name == "C"][0]
    assert node_a.contract == "contract_a.yaml", "Node A contract unchanged"
    assert node_c.contract == "contract_c.yaml", "Node C contract unchanged"


# ============================================================================
# Layer 3: Algorithm Verification Tests - has_cycle
# ============================================================================

def test_has_cycle_acyclic_graph(circuit_with_edges):
    """has_cycle returns False for acyclic graph (DAG)."""
    result = has_cycle(circuit_with_edges)
    
    # Returns False for DAG
    assert result is False, "Should return False for acyclic graph"
    
    # Original circuit unchanged
    assert len(circuit_with_edges.nodes) == 3, "Original unchanged"


def test_has_cycle_with_cycle(circuit_with_cycle):
    """has_cycle returns True for graph with cycle."""
    result = has_cycle(circuit_with_cycle)
    
    # Returns True for cyclic graph
    assert result is True, "Should return True for graph with cycle"
    
    # Original circuit unchanged
    assert len(circuit_with_cycle.nodes) == 3, "Original unchanged"


def test_has_cycle_empty_graph(empty_circuit):
    """has_cycle returns False for empty graph."""
    result = has_cycle(empty_circuit)
    
    # Returns False for empty graph
    assert result is False, "Should return False for empty graph"


def test_has_cycle_self_loop():
    """has_cycle returns True for graph with self-loop."""
    nodes = [NodeSpec(name="A", port=9001, proxy_mode="http",
                     contract="contract.yaml", role="client")]
    edges = [EdgeSpec(source="A", target="A", label="self")]
    circuit = CircuitSpec(name="test", version=1, nodes=nodes, edges=edges)
    
    result = has_cycle(circuit)
    
    # Returns True for self-loop
    assert result is True, "Should return True for self-loop"


def test_has_cycle_disconnected_components():
    """has_cycle correctly handles disconnected components."""
    nodes = [
        NodeSpec(name="A", port=9001, proxy_mode="http",
                contract="c.yaml", role="client"),
        NodeSpec(name="B", port=9002, proxy_mode="http",
                contract="c.yaml", role="client"),
        NodeSpec(name="C", port=9003, proxy_mode="http",
                contract="c.yaml", role="client"),
        NodeSpec(name="D", port=9004, proxy_mode="http",
                contract="c.yaml", role="client"),
    ]
    edges = [
        EdgeSpec(source="A", target="B", label="e1"),
        EdgeSpec(source="C", target="D", label="e2"),
    ]
    circuit = CircuitSpec(name="test", version=1, nodes=nodes, edges=edges)
    
    result = has_cycle(circuit)
    assert result is False, "Disconnected acyclic components should be acyclic"


# ============================================================================
# Layer 3: Algorithm Verification Tests - topological_sort
# ============================================================================

def test_topological_sort_happy_path():
    """topological_sort returns valid ordering for DAG."""
    nodes = [
        NodeSpec(name="A", port=9001, proxy_mode="http",
                contract="c.yaml", role="client"),
        NodeSpec(name="B", port=9002, proxy_mode="http",
                contract="c.yaml", role="client"),
        NodeSpec(name="C", port=9003, proxy_mode="http",
                contract="c.yaml", role="client"),
        NodeSpec(name="D", port=9004, proxy_mode="http",
                contract="c.yaml", role="client"),
    ]
    edges = [
        EdgeSpec(source="A", target="B", label="e1"),
        EdgeSpec(source="A", target="C", label="e2"),
        EdgeSpec(source="B", target="D", label="e3"),
        EdgeSpec(source="C", target="D", label="e4"),
    ]
    circuit = CircuitSpec(name="test", version=1, nodes=nodes, edges=edges)
    
    result = topological_sort(circuit)
    
    # Returns list of all node names
    assert len(result) == 4, "Should return all 4 nodes"
    assert set(result) == {"A", "B", "C", "D"}, "Should contain all nodes"
    
    # For every edge (u,v), u appears before v
    a_idx = result.index("A")
    b_idx = result.index("B")
    c_idx = result.index("C")
    d_idx = result.index("D")
    
    assert a_idx < b_idx, "A should appear before B"
    assert a_idx < c_idx, "A should appear before C"
    assert b_idx < d_idx, "B should appear before D"
    assert c_idx < d_idx, "C should appear before D"
    
    # Original circuit unchanged
    assert len(circuit.nodes) == 4, "Original circuit unchanged"


def test_topological_sort_error_contains_cycle(circuit_with_cycle):
    """topological_sort raises contains_cycle error for cyclic graph."""
    with pytest.raises(Exception) as exc_info:
        topological_sort(circuit_with_cycle)
    
    # Raises exception with contains_cycle error
    assert "cycle" in str(exc_info.value).lower() or \
           "contains_cycle" in str(exc_info.value).lower(), \
           "Should raise contains_cycle error"


def test_topological_sort_deterministic(circuit_with_multiple_nodes):
    """topological_sort returns deterministic result."""
    # Add edges to create a DAG with multiple valid orderings
    circuit = add_edge(circuit_with_multiple_nodes, "A", "C", "e1")
    circuit = add_edge(circuit, "B", "C", "e2")
    
    # Multiple calls return same result
    result1 = topological_sort(circuit)
    result2 = topological_sort(circuit)
    result3 = topological_sort(circuit)
    
    assert result1 == result2, "Results should be deterministic"
    assert result2 == result3, "Results should be deterministic"


def test_topological_sort_empty_graph(empty_circuit):
    """topological_sort returns empty list for empty circuit."""
    result = topological_sort(empty_circuit)
    
    # Returns empty list
    assert result == [], "Should return empty list for empty circuit"


def test_topological_sort_single_node(circuit_with_one_node):
    """topological_sort handles single node correctly."""
    result = topological_sort(circuit_with_one_node)
    
    assert result == ["node1"], "Should return single node"


def test_topological_sort_linear_chain(circuit_with_edges):
    """topological_sort handles linear chain correctly."""
    result = topological_sort(circuit_with_edges)
    
    # A->B->C, so order should be A, B, C
    assert result.index("A") < result.index("B"), "A before B"
    assert result.index("B") < result.index("C"), "B before C"


# ============================================================================
# Layer 1: Unit Tests for _next_port
# ============================================================================

def test_next_port_happy_path(empty_circuit):
    """Find next available port in empty circuit."""
    result = _next_port(empty_circuit)
    
    # Returns 9001 for empty circuit
    assert result == 9001, "First port should be 9001"
    
    # Original circuit unchanged
    assert len(empty_circuit.nodes) == 0, "Original circuit unchanged"


def test_next_port_finds_gap():
    """Find next available port skipping used ports."""
    nodes = [
        NodeSpec(name="node1", port=9001, proxy_mode="http",
                contract="c.yaml", role="client"),
        NodeSpec(name="node2", port=9002, proxy_mode="http",
                contract="c.yaml", role="client"),
    ]
    circuit = CircuitSpec(name="test", version=1, nodes=nodes, edges=[])
    
    result = _next_port(circuit)
    
    # Returns first unused port (9003)
    assert result == 9003, "Should return next available port 9003"


def test_next_port_error_no_available(circuit_full_ports):
    """No available ports raises no_available_ports error."""
    with pytest.raises(Exception) as exc_info:
        _next_port(circuit_full_ports)
    
    # Raises exception with no_available_ports error
    assert "no_available" in str(exc_info.value).lower() or \
           "no available" in str(exc_info.value).lower() or \
           "port" in str(exc_info.value).lower(), \
           "Should raise no_available_ports error"


def test_next_port_finds_gap_in_middle():
    """Find port when there's a gap in the middle."""
    nodes = [
        NodeSpec(name="node1", port=9001, proxy_mode="http",
                contract="c.yaml", role="client"),
        NodeSpec(name="node2", port=9003, proxy_mode="http",
                contract="c.yaml", role="client"),
        NodeSpec(name="node3", port=9005, proxy_mode="http",
                contract="c.yaml", role="client"),
    ]
    circuit = CircuitSpec(name="test", version=1, nodes=nodes, edges=[])
    
    result = _next_port(circuit)
    
    # Should find 9002 (first gap)
    assert result == 9002, "Should find first gap at 9002"


# ============================================================================
# Layer 6: Invariant Tests
# ============================================================================

def test_invariant_port_range(empty_circuit):
    """Verify DEFAULT_PORT_START and DEFAULT_PORT_MAX constants."""
    # Auto-assign multiple ports and verify they are in range [9001, 9999]
    circuit = empty_circuit
    for i in range(10):
        circuit = add_node(circuit, name=f"node{i}", port=0,
                          proxy_mode="http", contract="c.yaml",
                          role="client")
        last_node = circuit.nodes[-1]
        
        # Auto-assigned ports are >= 9001
        assert last_node.port >= 9001, \
               f"Port {last_node.port} should be >= 9001"
        
        # Auto-assigned ports are <= 9999
        assert last_node.port <= 9999, \
               f"Port {last_node.port} should be <= 9999"


def test_invariant_pure_functions(circuit_with_one_node):
    """Verify all functions are pure (don't mutate inputs)."""
    original_nodes_count = len(circuit_with_one_node.nodes)
    original_edges_count = len(circuit_with_one_node.edges)
    original_node_name = circuit_with_one_node.nodes[0].name
    original_node_port = circuit_with_one_node.nodes[0].port
    
    # Perform operations
    _ = add_node(circuit_with_one_node, "node2", 9002, "http", "c.yaml", "client")
    _ = set_contract(circuit_with_one_node, "node1", "new.yaml")
    _ = has_cycle(circuit_with_one_node)
    _ = topological_sort(circuit_with_one_node)
    _ = _next_port(circuit_with_one_node)
    
    # Original CircuitSpec is never modified
    assert len(circuit_with_one_node.nodes) == original_nodes_count, \
           "Node count should be unchanged"
    assert len(circuit_with_one_node.edges) == original_edges_count, \
           "Edge count should be unchanged"
    assert circuit_with_one_node.nodes[0].name == original_node_name, \
           "Node name should be unchanged"
    assert circuit_with_one_node.nodes[0].port == original_node_port, \
           "Node port should be unchanged"


def test_invariant_name_version_preservation(circuit_with_multiple_nodes):
    """Verify all CircuitSpec modifications preserve name and version fields."""
    original_name = circuit_with_multiple_nodes.name
    original_version = circuit_with_multiple_nodes.version
    
    # Perform various operations
    circuit2 = add_node(circuit_with_multiple_nodes, "D", 9004, 
                       "http", "c.yaml", "client")
    assert circuit2.name == original_name, "Name preserved after add_node"
    assert circuit2.version == original_version, "Version preserved after add_node"
    
    circuit3 = remove_node(circuit_with_multiple_nodes, "A")
    assert circuit3.name == original_name, "Name preserved after remove_node"
    assert circuit3.version == original_version, "Version preserved after remove_node"
    
    circuit4 = add_edge(circuit_with_multiple_nodes, "A", "B", "e")
    assert circuit4.name == original_name, "Name preserved after add_edge"
    assert circuit4.version == original_version, "Version preserved after add_edge"
    
    circuit5 = set_contract(circuit_with_multiple_nodes, "A", "new.yaml")
    assert circuit5.name == original_name, "Name preserved after set_contract"
    assert circuit5.version == original_version, "Version preserved after set_contract"


# ============================================================================
# Layer 2: State Transition Tests
# ============================================================================

def test_state_transition_build_circuit(empty_circuit):
    """Build a circuit through sequence of operations."""
    # Start with empty circuit
    circuit = empty_circuit
    
    # Add multiple nodes
    circuit = add_node(circuit, "A", 9001, "http", "a.yaml", "client")
    circuit = add_node(circuit, "B", 9002, "http", "b.yaml", "server")
    circuit = add_node(circuit, "C", 9003, "http", "c.yaml", "client")
    
    # All nodes are added correctly
    assert len(circuit.nodes) == 3, "Should have 3 nodes"
    node_names = [n.name for n in circuit.nodes]
    assert set(node_names) == {"A", "B", "C"}, "All nodes present"
    
    # Add edges
    circuit = add_edge(circuit, "A", "B", "e1")
    circuit = add_edge(circuit, "B", "C", "e2")
    
    # All edges connect valid nodes
    assert len(circuit.edges) == 2, "Should have 2 edges"
    for edge in circuit.edges:
        assert edge.source in node_names, "Edge source is valid node"
        assert edge.target in node_names, "Edge target is valid node"
    
    # State is consistent after each operation
    assert not has_cycle(circuit), "Circuit should be acyclic"


def test_state_transition_remove_and_re_add():
    """Remove node and re-add with same name."""
    circuit = CircuitSpec(name="test", version=1, nodes=[], edges=[])
    
    # Add node
    circuit = add_node(circuit, "A", 9001, "http", "a.yaml", "client")
    assert len(circuit.nodes) == 1, "Node added"
    
    # Remove node
    circuit = remove_node(circuit, "A")
    assert len(circuit.nodes) == 0, "Node removed"
    
    # Re-add with same name (should work)
    circuit = add_node(circuit, "A", 9002, "http", "a2.yaml", "server")
    assert len(circuit.nodes) == 1, "Node re-added"
    assert circuit.nodes[0].port == 9002, "New port assigned"


def test_state_transition_complex_graph_modifications():
    """Perform complex sequence of graph modifications."""
    circuit = CircuitSpec(name="test", version=1, nodes=[], edges=[])
    
    # Build initial graph
    circuit = add_node(circuit, "A", 0, "http", "a.yaml", "client")
    circuit = add_node(circuit, "B", 0, "http", "b.yaml", "server")
    circuit = add_node(circuit, "C", 0, "http", "c.yaml", "client")
    circuit = add_node(circuit, "D", 0, "http", "d.yaml", "server")
    
    circuit = add_edge(circuit, "A", "B", "e1")
    circuit = add_edge(circuit, "A", "C", "e2")
    circuit = add_edge(circuit, "C", "D", "e3")
    
    # Verify state
    assert len(circuit.nodes) == 4, "4 nodes present"
    assert len(circuit.edges) == 3, "3 edges present"
    assert not has_cycle(circuit), "No cycle"
    
    # Remove node C (should remove edges A->C and C->D)
    circuit = remove_node(circuit, "C")
    assert len(circuit.nodes) == 3, "3 nodes remain"
    assert len(circuit.edges) == 1, "Only 1 edge remains (A->B)"
    
    # Add new edge
    circuit = add_edge(circuit, "B", "D", "e4")
    assert len(circuit.edges) == 2, "2 edges now"
    
    # Verify topological sort still works
    sorted_nodes = topological_sort(circuit)
    assert len(sorted_nodes) == 3, "All nodes in sort"


# ============================================================================
# Layer 5: Domain-Specific Tests
# ============================================================================

def test_domain_circuit_attributes_persist():
    """Verify circuit attributes (port, proxy_mode, contract, role) persist correctly."""
    circuit = CircuitSpec(name="test", version=1, nodes=[], edges=[])
    
    circuit = add_node(circuit, "node1", 9050, "grpc", "contract_a.yaml", "client")
    
    node = circuit.nodes[0]
    assert node.name == "node1", "Name persists"
    assert node.port == 9050, "Port persists"
    assert node.proxy_mode == "grpc", "Proxy mode persists"
    assert node.contract == "contract_a.yaml", "Contract persists"
    assert node.role == "client", "Role persists"


def test_domain_set_contract_updates():
    """Verify set_contract updates work correctly."""
    circuit = CircuitSpec(name="test", version=1, nodes=[], edges=[])
    circuit = add_node(circuit, "node1", 9001, "http", "old.yaml", "client")
    
    # Update contract
    circuit = set_contract(circuit, "node1", "new.yaml")
    
    assert circuit.nodes[0].contract == "new.yaml", "Contract updated"
    
    # Other attributes unchanged
    assert circuit.nodes[0].name == "node1", "Name unchanged"
    assert circuit.nodes[0].port == 9001, "Port unchanged"
    assert circuit.nodes[0].proxy_mode == "http", "Proxy mode unchanged"
    assert circuit.nodes[0].role == "client", "Role unchanged"


def test_domain_multiple_contract_updates():
    """Multiple contract updates on different nodes."""
    circuit = CircuitSpec(name="test", version=1, nodes=[], edges=[])
    circuit = add_node(circuit, "A", 9001, "http", "a.yaml", "client")
    circuit = add_node(circuit, "B", 9002, "http", "b.yaml", "server")
    circuit = add_node(circuit, "C", 9003, "http", "c.yaml", "client")
    
    # Update contracts
    circuit = set_contract(circuit, "A", "a_v2.yaml")
    circuit = set_contract(circuit, "C", "c_v2.yaml")
    
    # Verify updates
    node_a = [n for n in circuit.nodes if n.name == "A"][0]
    node_b = [n for n in circuit.nodes if n.name == "B"][0]
    node_c = [n for n in circuit.nodes if n.name == "C"][0]
    
    assert node_a.contract == "a_v2.yaml", "A contract updated"
    assert node_b.contract == "b.yaml", "B contract unchanged"
    assert node_c.contract == "c_v2.yaml", "C contract updated"


# ============================================================================
# Layer 7: Integration Tests
# ============================================================================

def test_integration_workflow():
    """End-to-end workflow: build circuit, check cycle, sort, modify."""
    # Start fresh
    circuit = CircuitSpec(name="integration_test", version=1, 
                         nodes=[], edges=[])
    
    # Build circuit incrementally
    circuit = add_node(circuit, "frontend", 0, "http", "fe.yaml", "client")
    circuit = add_node(circuit, "api", 0, "http", "api.yaml", "server")
    circuit = add_node(circuit, "database", 0, "http", "db.yaml", "server")
    circuit = add_node(circuit, "cache", 0, "http", "cache.yaml", "server")
    
    # Circuit can be built incrementally
    assert len(circuit.nodes) == 4, "All nodes added"
    
    # Add edges to create a DAG
    circuit = add_edge(circuit, "frontend", "api", "calls")
    circuit = add_edge(circuit, "api", "database", "queries")
    circuit = add_edge(circuit, "api", "cache", "reads")
    
    # Cycle detection works correctly
    assert not has_cycle(circuit), "No cycle in DAG"
    
    # Topological sort produces valid ordering
    sorted_nodes = topological_sort(circuit)
    assert len(sorted_nodes) == 4, "All nodes in sort"
    assert sorted_nodes.index("frontend") < sorted_nodes.index("api"), \
           "Frontend before API"
    assert sorted_nodes.index("api") < sorted_nodes.index("database"), \
           "API before database"
    assert sorted_nodes.index("api") < sorted_nodes.index("cache"), \
           "API before cache"
    
    # Modifications work as expected
    circuit = set_contract(circuit, "api", "api_v2.yaml")
    api_node = [n for n in circuit.nodes if n.name == "api"][0]
    assert api_node.contract == "api_v2.yaml", "Contract updated"
    
    # Remove edge and verify
    circuit = remove_edge(circuit, "api", "cache")
    edge_pairs = [(e.source, e.target) for e in circuit.edges]
    assert ("api", "cache") not in edge_pairs, "Edge removed"
    assert len(circuit.edges) == 2, "2 edges remain"
    
    # Still a valid DAG
    assert not has_cycle(circuit), "Still acyclic"


def test_integration_cycle_detection_and_sort_consistency():
    """Verify cycle detection is consistent with topological sort."""
    # Build DAG
    circuit = CircuitSpec(name="test", version=1, nodes=[], edges=[])
    circuit = add_node(circuit, "A", 9001, "http", "a.yaml", "client")
    circuit = add_node(circuit, "B", 9002, "http", "b.yaml", "server")
    circuit = add_node(circuit, "C", 9003, "http", "c.yaml", "client")
    
    circuit = add_edge(circuit, "A", "B", "e1")
    circuit = add_edge(circuit, "B", "C", "e2")
    
    # Should be acyclic and sortable
    assert not has_cycle(circuit), "DAG has no cycle"
    sorted_nodes = topological_sort(circuit)
    assert len(sorted_nodes) == 3, "Sort succeeds"
    
    # Add cycle
    circuit = add_edge(circuit, "C", "A", "e3")
    
    # Should detect cycle and fail sort
    assert has_cycle(circuit), "Cycle detected"
    
    with pytest.raises(Exception) as exc_info:
        topological_sort(circuit)
    assert "cycle" in str(exc_info.value).lower(), "Sort fails on cycle"


def test_integration_realistic_microservices_circuit():
    """Build a realistic microservices circuit."""
    circuit = CircuitSpec(name="microservices", version=1, 
                         nodes=[], edges=[])
    
    # Add services
    services = ["gateway", "auth", "users", "orders", "inventory", 
                "payments", "notifications"]
    for service in services:
        circuit = add_node(circuit, service, 0, "grpc", 
                          f"{service}.yaml", "server")
    
    # Add dependencies
    circuit = add_edge(circuit, "gateway", "auth", "authenticate")
    circuit = add_edge(circuit, "gateway", "users", "user_data")
    circuit = add_edge(circuit, "gateway", "orders", "order_data")
    circuit = add_edge(circuit, "orders", "inventory", "check_stock")
    circuit = add_edge(circuit, "orders", "payments", "process_payment")
    circuit = add_edge(circuit, "orders", "notifications", "send_email")
    circuit = add_edge(circuit, "auth", "users", "verify_user")
    
    # Verify circuit structure
    assert len(circuit.nodes) == 7, "All services added"
    assert len(circuit.edges) == 7, "All dependencies added"
    
    # Should be acyclic
    assert not has_cycle(circuit), "Microservices DAG is acyclic"
    
    # Should be sortable
    sorted_nodes = topological_sort(circuit)
    assert len(sorted_nodes) == 7, "All services in topological order"
    
    # Verify ordering constraints
    gateway_idx = sorted_nodes.index("gateway")
    orders_idx = sorted_nodes.index("orders")
    inventory_idx = sorted_nodes.index("inventory")
    
    assert gateway_idx < orders_idx, "Gateway before orders"
    assert orders_idx < inventory_idx, "Orders before inventory"


def test_integration_random_dag_operations():
    """Test random valid operation sequences and verify invariants."""
    random.seed(42)  # For reproducibility
    
    circuit = CircuitSpec(name="random_test", version=1, nodes=[], edges=[])
    
    # Add random nodes
    num_nodes = 10
    for i in range(num_nodes):
        circuit = add_node(circuit, f"node{i}", 0, "http", 
                          f"contract{i}.yaml", "client")
    
    # Node count consistency
    assert len(circuit.nodes) == num_nodes, "All nodes added"
    
    # Add random edges (ensuring no cycles by only connecting i to j where i < j)
    edges_to_add = 15
    for _ in range(edges_to_add):
        i = random.randint(0, num_nodes - 2)
        j = random.randint(i + 1, num_nodes - 1)
        try:
            circuit = add_edge(circuit, f"node{i}", f"node{j}", f"edge_{i}_{j}")
        except:
            pass  # Edge might already exist
    
    # Edge endpoint validity
    for edge in circuit.edges:
        source_exists = any(n.name == edge.source for n in circuit.nodes)
        target_exists = any(n.name == edge.target for n in circuit.nodes)
        assert source_exists, f"Edge source {edge.source} exists"
        assert target_exists, f"Edge target {edge.target} exists"
    
    # Cycle detection consistency with topological_sort
    has_cycle_result = has_cycle(circuit)
    if not has_cycle_result:
        # Should be able to sort
        sorted_nodes = topological_sort(circuit)
        assert len(sorted_nodes) == num_nodes, "All nodes in sort"
        
        # Verify ordering
        node_indices = {name: idx for idx, name in enumerate(sorted_nodes)}
        for edge in circuit.edges:
            assert node_indices[edge.source] < node_indices[edge.target], \
                   f"Edge {edge.source}->{edge.target} respects topological order"
    else:
        # Should fail to sort
        with pytest.raises(Exception):
            topological_sort(circuit)


def test_integration_port_exhaustion_recovery():
    """Test behavior when approaching port exhaustion."""
    circuit = CircuitSpec(name="test", version=1, nodes=[], edges=[])
    
    # Add nodes until close to exhaustion
    # We'll add 50 nodes with explicit ports near the end of range
    for i in range(50):
        port = 9950 + i  # Ports 9950-9999
        circuit = add_node(circuit, f"node{i}", port, "http", 
                          "c.yaml", "client")
    
    # Now auto-assign should still work for lower ports
    circuit = add_node(circuit, "auto_node", 0, "http", "c.yaml", "client")
    auto_node = [n for n in circuit.nodes if n.name == "auto_node"][0]
    
    # Should get a port in lower range
    assert 9001 <= auto_node.port <= 9949, \
           f"Auto-assigned port {auto_node.port} in available range"
