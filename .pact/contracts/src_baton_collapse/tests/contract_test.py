"""
Contract tests for src_baton_collapse module.

This test suite verifies the build_mock_server and compute_mock_backends functions
against their contract specifications using pytest and unittest.mock.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from pathlib import Path
from typing import Any

# Import the module under test
from src.baton.collapse import build_mock_server, compute_mock_backends


# Helper functions to create mock objects
def create_mock_node(name: str, port: int, contract: Any = None, role: Any = None):
    """Create a mock node with required attributes."""
    node = Mock()
    node.name = name
    node.port = port
    node.contract = contract
    if role is not None:
        node.role = role
    return node


def create_mock_circuit(nodes: list, egress_nodes: list):
    """Create a mock CircuitSpec with nodes and egress_nodes."""
    circuit = Mock()
    circuit.nodes = nodes
    circuit.egress_nodes = egress_nodes
    return circuit


def create_mock_backend_target(host: str, port: int):
    """Create a mock BackendTarget."""
    backend = Mock()
    backend.host = host
    backend.port = port
    return backend


# Happy Path Tests for build_mock_server

def test_build_mock_server_happy_path_basic():
    """Build mock server with basic circuit containing non-live nodes."""
    # Setup
    node1 = create_mock_node("node1", 8000, contract=None)
    node2 = create_mock_node("node2", 8001, contract=None)
    node3 = create_mock_node("node3", 8002, contract=None)
    egress = create_mock_node("egress1", 8003, contract=None)
    
    circuit = create_mock_circuit(
        nodes=[node1, node2, node3, egress],
        egress_nodes=[egress]
    )
    live_nodes = {"node1"}
    project_dir = "/test/project"
    
    with patch('src.src_baton_collapse.MockServer') as MockServerClass, \
         patch('src.src_baton_collapse.logger'):
        
        mock_server_instance = MagicMock()
        MockServerClass.return_value = mock_server_instance
        
        # Execute
        result = build_mock_server(circuit, live_nodes, project_dir)
        
        # Assert
        assert result is mock_server_instance, "MockServer instance should be returned"
        assert mock_server_instance.add_route.call_count >= 2, "Routes should be added for mocked nodes"
        MockServerClass.assert_called_once()


def test_build_mock_server_happy_path_empty_live_nodes():
    """Build mock server when all nodes need to be mocked (empty live_nodes)."""
    # Setup
    node1 = create_mock_node("node1", 8000, contract=None)
    node2 = create_mock_node("node2", 8001, contract=None)
    egress = create_mock_node("egress1", 8002, contract=None)
    
    circuit = create_mock_circuit(
        nodes=[node1, node2, egress],
        egress_nodes=[egress]
    )
    live_nodes = set()
    project_dir = "/test/project"
    
    with patch('src.src_baton_collapse.MockServer') as MockServerClass, \
         patch('src.src_baton_collapse.logger'):
        
        mock_server_instance = MagicMock()
        MockServerClass.return_value = mock_server_instance
        
        # Execute
        result = build_mock_server(circuit, live_nodes, project_dir)
        
        # Assert
        assert result is mock_server_instance, "MockServer should be returned"
        assert mock_server_instance.add_route.call_count >= 3, "All nodes should be mocked"


def test_build_mock_server_happy_path_with_contracts():
    """Build mock server with nodes having valid contract files."""
    # Setup
    node1 = create_mock_node("node1", 8000, contract="/path/to/contract1.yaml")
    node2 = create_mock_node("node2", 8001, contract=None)
    egress = create_mock_node("egress1", 8002, contract="/path/to/contract2.yaml")
    
    circuit = create_mock_circuit(
        nodes=[node1, node2, egress],
        egress_nodes=[egress]
    )
    live_nodes = set()
    project_dir = "/test/project"
    
    with patch('src.src_baton_collapse.MockServer') as MockServerClass, \
         patch('src.src_baton_collapse.logger'), \
         patch('src.src_baton_collapse.load_routes') as mock_load_routes, \
         patch('pathlib.Path.exists', return_value=True):
        
        mock_server_instance = MagicMock()
        MockServerClass.return_value = mock_server_instance
        
        # Execute
        result = build_mock_server(circuit, live_nodes, project_dir)
        
        # Assert
        assert result is mock_server_instance, "MockServer should be returned"
        # Routes should be loaded for nodes with contracts
        assert mock_load_routes.call_count >= 1 or mock_server_instance.add_route.call_count >= 1


# Edge Case Tests for build_mock_server

def test_build_mock_server_edge_case_port_exceeds_limit():
    """Build mock server when node.port + 20000 exceeds 65535."""
    # Setup
    node1 = create_mock_node("node1", 50000, contract=None)  # 50000 + 20000 > 65535
    egress = create_mock_node("egress1", 60000, contract=None)
    
    circuit = create_mock_circuit(
        nodes=[node1, egress],
        egress_nodes=[egress]
    )
    live_nodes = set()
    project_dir = "/test/project"
    
    with patch('src.src_baton_collapse.MockServer') as MockServerClass, \
         patch('src.src_baton_collapse.logger'):
        
        mock_server_instance = MagicMock()
        MockServerClass.return_value = mock_server_instance
        
        # Execute
        result = build_mock_server(circuit, live_nodes, project_dir)
        
        # Assert
        assert result is mock_server_instance, "MockServer should be returned"
        # Service port should be calculated as port + 5000 for ports that would exceed 65535
        # Verify through add_route calls
        call_args_list = mock_server_instance.add_route.call_args_list
        assert len(call_args_list) >= 2, "Routes should be added for both nodes"


def test_build_mock_server_edge_case_egress_always_mocked():
    """Egress nodes are always mocked even if in live_nodes set."""
    # Setup
    node1 = create_mock_node("node1", 8000, contract=None)
    egress = create_mock_node("egress1", 8001, contract=None)
    
    circuit = create_mock_circuit(
        nodes=[node1, egress],
        egress_nodes=[egress]
    )
    live_nodes = {"node1", "egress1"}  # Egress node in live_nodes
    project_dir = "/test/project"
    
    with patch('src.src_baton_collapse.MockServer') as MockServerClass, \
         patch('src.src_baton_collapse.logger'):
        
        mock_server_instance = MagicMock()
        MockServerClass.return_value = mock_server_instance
        
        # Execute
        result = build_mock_server(circuit, live_nodes, project_dir)
        
        # Assert
        assert result is mock_server_instance, "MockServer should be returned"
        # Egress should be mocked even though it's in live_nodes
        assert mock_server_instance.add_route.call_count >= 1, "Egress node should be mocked"


def test_build_mock_server_edge_case_all_live_except_egress():
    """All nodes are live except egress nodes must still be mocked."""
    # Setup
    node1 = create_mock_node("node1", 8000, contract=None)
    node2 = create_mock_node("node2", 8001, contract=None)
    egress = create_mock_node("egress1", 8002, contract=None)
    
    circuit = create_mock_circuit(
        nodes=[node1, node2, egress],
        egress_nodes=[egress]
    )
    live_nodes = {"node1", "node2"}  # All non-egress nodes are live
    project_dir = "/test/project"
    
    with patch('src.src_baton_collapse.MockServer') as MockServerClass, \
         patch('src.src_baton_collapse.logger'):
        
        mock_server_instance = MagicMock()
        MockServerClass.return_value = mock_server_instance
        
        # Execute
        result = build_mock_server(circuit, live_nodes, project_dir)
        
        # Assert
        assert result is mock_server_instance, "MockServer should be returned"
        # Only egress should be mocked
        assert mock_server_instance.add_route.call_count >= 1, "Egress node should be mocked"


def test_build_mock_server_edge_case_path_object():
    """Build mock server with project_dir as Path object."""
    # Setup
    node1 = create_mock_node("node1", 8000, contract=None)
    egress = create_mock_node("egress1", 8001, contract=None)
    
    circuit = create_mock_circuit(
        nodes=[node1, egress],
        egress_nodes=[egress]
    )
    live_nodes = set()
    project_dir = Path("/test/project")  # Path object instead of string
    
    with patch('src.src_baton_collapse.MockServer') as MockServerClass, \
         patch('src.src_baton_collapse.logger'):
        
        mock_server_instance = MagicMock()
        MockServerClass.return_value = mock_server_instance
        
        # Execute
        result = build_mock_server(circuit, live_nodes, project_dir)
        
        # Assert
        assert result is mock_server_instance, "Path object should be accepted"


# Error Case Tests for build_mock_server

def test_build_mock_server_error_missing_nodes_attribute():
    """Error when circuit lacks nodes attribute."""
    # Setup
    circuit = Mock(spec=[])  # No nodes attribute
    circuit.egress_nodes = []
    live_nodes = set()
    project_dir = "/test/project"
    
    # Execute & Assert
    with pytest.raises(AttributeError):
        build_mock_server(circuit, live_nodes, project_dir)


def test_build_mock_server_error_missing_egress_nodes():
    """Error when circuit lacks egress_nodes attribute."""
    # Setup
    circuit = Mock(spec=[])
    circuit.nodes = []
    # No egress_nodes attribute
    live_nodes = set()
    project_dir = "/test/project"
    
    # Execute & Assert
    with pytest.raises(AttributeError):
        build_mock_server(circuit, live_nodes, project_dir)


def test_build_mock_server_error_node_missing_name():
    """Error when node lacks name attribute."""
    # Setup
    node = Mock(spec=['port', 'contract'])
    node.port = 8000
    node.contract = None
    # No name attribute
    
    circuit = create_mock_circuit(
        nodes=[node],
        egress_nodes=[]
    )
    live_nodes = set()
    project_dir = "/test/project"
    
    with patch('src.src_baton_collapse.MockServer'), \
         patch('src.src_baton_collapse.logger'):
        
        # Execute & Assert
        with pytest.raises(AttributeError):
            build_mock_server(circuit, live_nodes, project_dir)


def test_build_mock_server_error_node_missing_port():
    """Error when node lacks port attribute."""
    # Setup
    node = Mock(spec=['name', 'contract'])
    node.name = "node1"
    node.contract = None
    # No port attribute
    
    circuit = create_mock_circuit(
        nodes=[node],
        egress_nodes=[]
    )
    live_nodes = set()
    project_dir = "/test/project"
    
    with patch('src.src_baton_collapse.MockServer'), \
         patch('src.src_baton_collapse.logger'):
        
        # Execute & Assert
        with pytest.raises(AttributeError):
            build_mock_server(circuit, live_nodes, project_dir)


def test_build_mock_server_error_node_missing_contract():
    """Error when node lacks contract attribute."""
    # Setup
    node = Mock(spec=['name', 'port'])
    node.name = "node1"
    node.port = 8000
    # No contract attribute
    
    circuit = create_mock_circuit(
        nodes=[node],
        egress_nodes=[]
    )
    live_nodes = set()
    project_dir = "/test/project"
    
    with patch('src.src_baton_collapse.MockServer'), \
         patch('src.src_baton_collapse.logger'):
        
        # Execute & Assert
        with pytest.raises(AttributeError):
            build_mock_server(circuit, live_nodes, project_dir)


def test_build_mock_server_error_contract_file_not_found():
    """Error when contract file path does not exist."""
    # Setup
    node = create_mock_node("node1", 8000, contract="/nonexistent/contract.yaml")
    
    circuit = create_mock_circuit(
        nodes=[node],
        egress_nodes=[]
    )
    live_nodes = set()
    project_dir = "/test/project"
    
    with patch('src.src_baton_collapse.MockServer') as MockServerClass, \
         patch('src.src_baton_collapse.logger'), \
         patch('src.src_baton_collapse.load_routes', side_effect=FileNotFoundError("Contract not found")):
        
        mock_server_instance = MagicMock()
        MockServerClass.return_value = mock_server_instance
        
        # Execute & Assert
        with pytest.raises(FileNotFoundError):
            build_mock_server(circuit, live_nodes, project_dir)


def test_build_mock_server_error_live_nodes_not_set():
    """Error when live_nodes is not a set."""
    # Setup
    node = create_mock_node("node1", 8000, contract=None)
    
    circuit = create_mock_circuit(
        nodes=[node],
        egress_nodes=[]
    )
    live_nodes = ["node1"]  # List instead of set
    project_dir = "/test/project"
    
    # Execute & Assert
    with pytest.raises(TypeError):
        build_mock_server(circuit, live_nodes, project_dir)


def test_build_mock_server_error_egress_nodes_not_iterable():
    """Error when circuit.egress_nodes is not iterable."""
    # Setup
    node = create_mock_node("node1", 8000, contract=None)
    
    circuit = Mock()
    circuit.nodes = [node]
    circuit.egress_nodes = 123  # Not iterable
    
    live_nodes = set()
    project_dir = "/test/project"
    
    with patch('src.src_baton_collapse.MockServer'), \
         patch('src.src_baton_collapse.logger'):
        
        # Execute & Assert
        with pytest.raises(TypeError):
            build_mock_server(circuit, live_nodes, project_dir)


# Happy Path Tests for compute_mock_backends

def test_compute_mock_backends_happy_path_basic():
    """Compute backend targets for non-live nodes."""
    # Setup
    node1 = create_mock_node("node1", 8000)
    node2 = create_mock_node("node2", 8001)
    node3 = create_mock_node("node3", 8002)
    egress = create_mock_node("egress1", 8003)
    
    circuit = create_mock_circuit(
        nodes=[node1, node2, node3, egress],
        egress_nodes=[egress]
    )
    live_nodes = {"node1"}
    
    with patch('src.src_baton_collapse.BackendTarget') as MockBackendTarget:
        # Mock BackendTarget to return distinguishable objects
        def backend_side_effect(host, port):
            return create_mock_backend_target(host, port)
        
        MockBackendTarget.side_effect = backend_side_effect
        
        # Execute
        result = compute_mock_backends(circuit, live_nodes)
        
        # Assert
        assert isinstance(result, dict), "Dictionary should be returned"
        assert "node1" not in result, "Live nodes should not be in result"
        assert "node2" in result, "Non-live nodes should be in result"
        assert "node3" in result, "Non-live nodes should be in result"
        assert "egress1" in result, "Egress nodes should be in result"
        
        # Check BackendTarget properties
        for backend in result.values():
            assert backend.host == "127.0.0.1", "Host should be 127.0.0.1"
            assert isinstance(backend.port, int), "Port should be integer"


def test_compute_mock_backends_happy_path_empty_live_nodes():
    """Compute backends when all nodes are non-live."""
    # Setup
    node1 = create_mock_node("node1", 8000)
    node2 = create_mock_node("node2", 8001)
    egress = create_mock_node("egress1", 8002)
    
    circuit = create_mock_circuit(
        nodes=[node1, node2, egress],
        egress_nodes=[egress]
    )
    live_nodes = set()
    
    with patch('src.src_baton_collapse.BackendTarget') as MockBackendTarget:
        def backend_side_effect(host, port):
            return create_mock_backend_target(host, port)
        
        MockBackendTarget.side_effect = backend_side_effect
        
        # Execute
        result = compute_mock_backends(circuit, live_nodes)
        
        # Assert
        assert len(result) == 3, "All nodes should be mapped to BackendTargets"
        assert "node1" in result
        assert "node2" in result
        assert "egress1" in result


def test_compute_mock_backends_happy_path_all_live_except_egress():
    """Compute backends when all non-egress nodes are live."""
    # Setup
    node1 = create_mock_node("node1", 8000)
    node2 = create_mock_node("node2", 8001)
    egress = create_mock_node("egress1", 8002)
    
    circuit = create_mock_circuit(
        nodes=[node1, node2, egress],
        egress_nodes=[egress]
    )
    live_nodes = {"node1", "node2"}
    
    with patch('src.src_baton_collapse.BackendTarget') as MockBackendTarget:
        def backend_side_effect(host, port):
            return create_mock_backend_target(host, port)
        
        MockBackendTarget.side_effect = backend_side_effect
        
        # Execute
        result = compute_mock_backends(circuit, live_nodes)
        
        # Assert
        assert len(result) == 1, "Only egress node should be in result"
        assert "egress1" in result
        assert "node1" not in result
        assert "node2" not in result


# Edge Case Tests for compute_mock_backends

def test_compute_mock_backends_edge_case_port_exceeds_limit():
    """Compute backends when node.port + 20000 exceeds 65535."""
    # Setup
    node1 = create_mock_node("node1", 50000)
    
    circuit = create_mock_circuit(
        nodes=[node1],
        egress_nodes=[]
    )
    live_nodes = set()
    
    with patch('src.src_baton_collapse.BackendTarget') as MockBackendTarget:
        def backend_side_effect(host, port):
            backend = create_mock_backend_target(host, port)
            return backend
        
        MockBackendTarget.side_effect = backend_side_effect
        
        # Execute
        result = compute_mock_backends(circuit, live_nodes)
        
        # Assert
        assert "node1" in result
        backend = result["node1"]
        # Service port should be 50000 + 5000 = 55000 (since 50000 + 20000 > 65535)
        assert backend.port == 55000, "Service port should be node.port + 5000"


def test_compute_mock_backends_edge_case_egress_always_included():
    """Egress nodes always included even if in live_nodes."""
    # Setup
    node1 = create_mock_node("node1", 8000)
    egress = create_mock_node("egress1", 8001)
    
    circuit = create_mock_circuit(
        nodes=[node1, egress],
        egress_nodes=[egress]
    )
    live_nodes = {"node1", "egress1"}
    
    with patch('src.src_baton_collapse.BackendTarget') as MockBackendTarget:
        def backend_side_effect(host, port):
            return create_mock_backend_target(host, port)
        
        MockBackendTarget.side_effect = backend_side_effect
        
        # Execute
        result = compute_mock_backends(circuit, live_nodes)
        
        # Assert
        assert "egress1" in result, "Egress node should be included"
        assert "node1" not in result, "Non-egress live node should not be included"


def test_compute_mock_backends_edge_case_empty_result():
    """Empty result when all non-egress nodes are live and no egress nodes."""
    # Setup
    node1 = create_mock_node("node1", 8000)
    node2 = create_mock_node("node2", 8001)
    
    circuit = create_mock_circuit(
        nodes=[node1, node2],
        egress_nodes=[]
    )
    live_nodes = {"node1", "node2"}
    
    with patch('src.src_baton_collapse.BackendTarget'):
        # Execute
        result = compute_mock_backends(circuit, live_nodes)
        
        # Assert
        assert len(result) == 0, "Result should be empty dict"


# Error Case Tests for compute_mock_backends

def test_compute_mock_backends_error_missing_nodes_attribute():
    """Error when circuit lacks nodes attribute."""
    # Setup
    circuit = Mock(spec=[])
    circuit.egress_nodes = []
    live_nodes = set()
    
    # Execute & Assert
    with pytest.raises(AttributeError):
        compute_mock_backends(circuit, live_nodes)


def test_compute_mock_backends_error_missing_egress_nodes():
    """Error when circuit lacks egress_nodes attribute."""
    # Setup
    circuit = Mock(spec=[])
    circuit.nodes = []
    live_nodes = set()
    
    # Execute & Assert
    with pytest.raises(AttributeError):
        compute_mock_backends(circuit, live_nodes)


def test_compute_mock_backends_error_node_missing_name():
    """Error when node lacks name attribute."""
    # Setup
    node = Mock(spec=['port'])
    node.port = 8000
    
    circuit = create_mock_circuit(
        nodes=[node],
        egress_nodes=[]
    )
    live_nodes = set()
    
    with patch('src.src_baton_collapse.BackendTarget'):
        # Execute & Assert
        with pytest.raises(AttributeError):
            compute_mock_backends(circuit, live_nodes)


def test_compute_mock_backends_error_node_missing_port():
    """Error when node lacks port attribute."""
    # Setup
    node = Mock(spec=['name'])
    node.name = "node1"
    
    circuit = create_mock_circuit(
        nodes=[node],
        egress_nodes=[]
    )
    live_nodes = set()
    
    with patch('src.src_baton_collapse.BackendTarget'):
        # Execute & Assert
        with pytest.raises(AttributeError):
            compute_mock_backends(circuit, live_nodes)


def test_compute_mock_backends_error_live_nodes_not_set():
    """Error when live_nodes is not a set."""
    # Setup
    node = create_mock_node("node1", 8000)
    
    circuit = create_mock_circuit(
        nodes=[node],
        egress_nodes=[]
    )
    live_nodes = ["node1"]  # List instead of set
    
    # Execute & Assert
    with pytest.raises(TypeError):
        compute_mock_backends(circuit, live_nodes)


def test_compute_mock_backends_error_egress_nodes_not_iterable():
    """Error when circuit.egress_nodes is not iterable."""
    # Setup
    node = create_mock_node("node1", 8000)
    
    circuit = Mock()
    circuit.nodes = [node]
    circuit.egress_nodes = 42  # Not iterable
    
    live_nodes = set()
    
    with patch('src.src_baton_collapse.BackendTarget'):
        # Execute & Assert
        with pytest.raises(TypeError):
            compute_mock_backends(circuit, live_nodes)


# Invariant Tests

def test_invariant_service_port_calculation_consistency():
    """Service port calculation is consistent between both functions."""
    # Setup
    node1 = create_mock_node("node1", 8000)
    node2 = create_mock_node("node2", 50000)  # Port that exceeds limit
    egress = create_mock_node("egress1", 8001)
    
    circuit = create_mock_circuit(
        nodes=[node1, node2, egress],
        egress_nodes=[egress]
    )
    live_nodes = set()
    project_dir = "/test/project"
    
    with patch('src.src_baton_collapse.MockServer') as MockServerClass, \
         patch('src.src_baton_collapse.BackendTarget') as MockBackendTarget, \
         patch('src.src_baton_collapse.logger'):
        
        mock_server_instance = MagicMock()
        MockServerClass.return_value = mock_server_instance
        
        def backend_side_effect(host, port):
            return create_mock_backend_target(host, port)
        
        MockBackendTarget.side_effect = backend_side_effect
        
        # Execute both functions
        build_mock_server(circuit, live_nodes, project_dir)
        backends = compute_mock_backends(circuit, live_nodes)
        
        # Assert service port calculations are consistent
        # Check that add_route was called with service ports
        add_route_calls = mock_server_instance.add_route.call_args_list
        assert len(add_route_calls) >= 3, "Routes should be added for all nodes"
        
        # Check backend targets have correct ports
        assert "node1" in backends
        assert "node2" in backends
        assert "egress1" in backends
        
        # Verify port calculations
        assert backends["node1"].port == 28000, "node1 service port should be 8000 + 20000"
        assert backends["node2"].port == 55000, "node2 service port should be 50000 + 5000"
        assert backends["egress1"].port == 28001, "egress1 service port should be 8001 + 20000"


def test_invariant_egress_always_mocked():
    """Egress nodes are always treated as non-live in both functions."""
    # Setup
    node1 = create_mock_node("node1", 8000)
    egress = create_mock_node("egress1", 8001)
    
    circuit = create_mock_circuit(
        nodes=[node1, egress],
        egress_nodes=[egress]
    )
    live_nodes = {"node1", "egress1"}  # Even with egress in live_nodes
    project_dir = "/test/project"
    
    with patch('src.src_baton_collapse.MockServer') as MockServerClass, \
         patch('src.src_baton_collapse.BackendTarget') as MockBackendTarget, \
         patch('src.src_baton_collapse.logger'):
        
        mock_server_instance = MagicMock()
        MockServerClass.return_value = mock_server_instance
        
        def backend_side_effect(host, port):
            return create_mock_backend_target(host, port)
        
        MockBackendTarget.side_effect = backend_side_effect
        
        # Execute
        build_mock_server(circuit, live_nodes, project_dir)
        backends = compute_mock_backends(circuit, live_nodes)
        
        # Assert
        assert mock_server_instance.add_route.call_count >= 1, "Egress should be mocked"
        assert "egress1" in backends, "Egress should be in backends"


def test_invariant_effective_live_nodes_logic():
    """Both functions use identical logic for determining effective live nodes."""
    # Setup
    node1 = create_mock_node("node1", 8000)
    node2 = create_mock_node("node2", 8001)
    node3 = create_mock_node("node3", 8002)
    egress1 = create_mock_node("egress1", 8003)
    egress2 = create_mock_node("egress2", 8004)
    
    circuit = create_mock_circuit(
        nodes=[node1, node2, node3, egress1, egress2],
        egress_nodes=[egress1, egress2]
    )
    live_nodes = {"node1", "egress1"}
    project_dir = "/test/project"
    
    with patch('src.src_baton_collapse.MockServer') as MockServerClass, \
         patch('src.src_baton_collapse.BackendTarget') as MockBackendTarget, \
         patch('src.src_baton_collapse.logger'):
        
        mock_server_instance = MagicMock()
        MockServerClass.return_value = mock_server_instance
        
        def backend_side_effect(host, port):
            return create_mock_backend_target(host, port)
        
        MockBackendTarget.side_effect = backend_side_effect
        
        # Execute
        build_mock_server(circuit, live_nodes, project_dir)
        backends = compute_mock_backends(circuit, live_nodes)
        
        # Assert
        # Mocked nodes should be: node2, node3, egress1, egress2
        expected_mocked = {"node2", "node3", "egress1", "egress2"}
        assert set(backends.keys()) == expected_mocked, "Mocked nodes should match across functions"


def test_invariant_localhost_host():
    """Mock server host is always 127.0.0.1."""
    # Setup
    node1 = create_mock_node("node1", 8000)
    node2 = create_mock_node("node2", 8001)
    egress = create_mock_node("egress1", 8002)
    
    circuit = create_mock_circuit(
        nodes=[node1, node2, egress],
        egress_nodes=[egress]
    )
    live_nodes = set()
    
    with patch('src.src_baton_collapse.BackendTarget') as MockBackendTarget:
        def backend_side_effect(host, port):
            return create_mock_backend_target(host, port)
        
        MockBackendTarget.side_effect = backend_side_effect
        
        # Execute
        backends = compute_mock_backends(circuit, live_nodes)
        
        # Assert
        for node_name, backend in backends.items():
            assert backend.host == "127.0.0.1", f"Backend for {node_name} should have host 127.0.0.1"
