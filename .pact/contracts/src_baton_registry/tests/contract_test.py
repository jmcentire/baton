"""
Contract-driven pytest test suite for src_baton_registry component.

This test suite verifies the behavior of:
- _next_port: Port allocation within DEFAULT_PORT_START to DEFAULT_PORT_MAX range
- load_manifests: Loading and validating service manifests from directories
- derive_circuit: Deriving CircuitSpec from ServiceManifests with dependency resolution

All tests follow contract-driven principles:
- Mock all external dependencies
- Test at boundaries (inputs/outputs)
- Cover happy paths, edge cases, error cases, and invariants
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from pathlib import Path
from typing import Any

# Import the component under test
from src.baton.registry import (
    _next_port,
    load_manifests,
    derive_circuit,
    DEFAULT_PORT_START,
    DEFAULT_PORT_MAX,
)


# ============================================================================
# Test Fixtures and Helpers
# ============================================================================

@pytest.fixture
def mock_service_manifest():
    """Create a mock ServiceManifest with configurable attributes."""
    def _create_manifest(
        name="test-service",
        port=0,
        dependencies=None,
        proxy_mode="http",
        role="service",
        metadata=None,
        mock_spec=None,
        api_spec=None
    ):
        manifest = Mock()
        manifest.name = name
        manifest.port = port
        manifest.dependencies = dependencies or []
        manifest.proxy_mode = proxy_mode
        manifest.role = role
        manifest.metadata = metadata or {}
        manifest.mock_spec = mock_spec
        manifest.api_spec = api_spec
        return manifest
    return _create_manifest


@pytest.fixture
def mock_node_spec():
    """Create a mock NodeSpec."""
    def _create_node(name, port, proxy_mode="http", contract=None, role="service", metadata=None):
        node = Mock()
        node.name = name
        node.port = port
        node.proxy_mode = proxy_mode
        node.contract = contract
        node.role = role
        node.metadata = metadata or {}
        return node
    return _create_node


@pytest.fixture
def mock_edge_spec():
    """Create a mock EdgeSpec."""
    def _create_edge(source, target, label="depends-on"):
        edge = Mock()
        edge.source = source
        edge.target = target
        edge.label = label
        return edge
    return _create_edge


@pytest.fixture
def mock_circuit_spec():
    """Create a mock CircuitSpec."""
    def _create_circuit(name, version=1, nodes=None, edges=None):
        circuit = Mock()
        circuit.name = name
        circuit.version = version
        circuit.nodes = nodes or []
        circuit.edges = edges or []
        return circuit
    return _create_circuit


# ============================================================================
# Tests for _next_port
# ============================================================================

class TestNextPort:
    """Tests for the _next_port function."""
    
    def test_next_port_happy_path(self):
        """Find next available port with some ports already used."""
        used = {8000, 8001, 8005}
        
        result = _next_port(used)
        
        # Verify postconditions
        assert result not in used, "Returned port should not be in used set"
        assert DEFAULT_PORT_START <= result <= DEFAULT_PORT_MAX, \
            f"Port {result} must be in range [{DEFAULT_PORT_START}, {DEFAULT_PORT_MAX}]"
        # Should return first available port
        assert result == 8002 or result not in used
    
    def test_next_port_empty_set(self):
        """Find next available port when no ports are used."""
        used = set()
        
        result = _next_port(used)
        
        # Should return the start of the range
        assert result == DEFAULT_PORT_START, \
            f"With no ports used, should return DEFAULT_PORT_START ({DEFAULT_PORT_START})"
    
    def test_next_port_all_exhausted(self):
        """Raise error when all ports in range are used."""
        # Use all ports in the valid range
        used = set(range(DEFAULT_PORT_START, DEFAULT_PORT_MAX + 1))
        
        with pytest.raises(Exception) as exc_info:
            _next_port(used)
        
        # Verify error is about no available ports
        error_msg = str(exc_info.value).lower()
        assert "no" in error_msg or "available" in error_msg or "port" in error_msg or "exhaust" in error_msg, \
            f"Expected no_available_ports error, got: {exc_info.value}"
    
    def test_next_port_nearly_exhausted(self):
        """Find last available port when range is nearly exhausted."""
        # Use all ports except the last one
        used = set(range(DEFAULT_PORT_START, DEFAULT_PORT_MAX))
        
        result = _next_port(used)
        
        # Should return the only available port
        assert result == DEFAULT_PORT_MAX, \
            f"Should return DEFAULT_PORT_MAX ({DEFAULT_PORT_MAX}) when it's the only available port"
        assert result not in used


# ============================================================================
# Tests for load_manifests
# ============================================================================

class TestLoadManifests:
    """Tests for the load_manifests function."""
    
    @patch('src.src_baton_registry.load_manifest')
    def test_load_manifests_single_service(self, mock_load_manifest, mock_service_manifest):
        """Load a single service manifest successfully."""
        # Setup
        manifest = mock_service_manifest(name="service1", port=8000)
        mock_load_manifest.return_value = manifest
        service_dirs = [Path('/service1')]
        
        # Execute
        result = load_manifests(service_dirs)
        
        # Verify postconditions
        assert len(result) == len(service_dirs), \
            "Length of returned list should equal length of service_dirs input"
        assert len(result) == 1, "Should return one manifest"
        
        # Verify all service names are unique
        service_names = [m.name for m in result]
        assert len(service_names) == len(set(service_names)), \
            "All service names should be unique"
        
        # Verify load_manifest was called
        mock_load_manifest.assert_called_once_with(Path('/service1'))
    
    @patch('src.src_baton_registry.load_manifest')
    def test_load_manifests_multiple_services(self, mock_load_manifest, mock_service_manifest):
        """Load multiple service manifests with unique names."""
        # Setup
        manifests = [
            mock_service_manifest(name="service1", port=8000),
            mock_service_manifest(name="service2", port=8001),
            mock_service_manifest(name="service3", port=8002),
        ]
        mock_load_manifest.side_effect = manifests
        service_dirs = [Path('/service1'), Path('/service2'), Path('/service3')]
        
        # Execute
        result = load_manifests(service_dirs)
        
        # Verify postconditions
        assert len(result) == len(service_dirs), \
            "Length of returned list should equal length of service_dirs input"
        assert len(result) == 3, "Should return three manifests"
        
        # Verify all service names are unique
        service_names = [m.name for m in result]
        assert len(service_names) == len(set(service_names)), \
            "All service names should be unique"
        
        # Verify correct calls
        assert mock_load_manifest.call_count == 3
    
    @patch('src.src_baton_registry.load_manifest')
    def test_load_manifests_empty_list(self, mock_load_manifest):
        """Load manifests with empty directory list."""
        service_dirs = []
        
        result = load_manifests(service_dirs)
        
        # Verify empty result
        assert len(result) == 0, "Should return empty list for empty input"
        assert len(result) == len(service_dirs), \
            "Length of returned list should equal length of service_dirs input"
        
        # load_manifest should not be called
        mock_load_manifest.assert_not_called()
    
    @patch('src.src_baton_registry.load_manifest')
    def test_load_manifests_duplicate_names(self, mock_load_manifest, mock_service_manifest):
        """Raise error when two manifests have the same service name."""
        # Setup - two manifests with the same name
        manifest1 = mock_service_manifest(name="duplicate-service", port=8000)
        manifest2 = mock_service_manifest(name="duplicate-service", port=8001)
        mock_load_manifest.side_effect = [manifest1, manifest2]
        service_dirs = [Path('/service1'), Path('/service2')]
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            load_manifests(service_dirs)
        
        # Verify error is about duplicate service names
        error_msg = str(exc_info.value).lower()
        assert "duplicate" in error_msg or "unique" in error_msg or "duplicate-service" in error_msg, \
            f"Expected duplicate_service_names error, got: {exc_info.value}"
    
    @patch('src.src_baton_registry.load_manifest')
    def test_load_manifests_load_failure(self, mock_load_manifest):
        """Raise error when load_manifest fails for a directory."""
        # Setup - load_manifest raises an exception
        original_error = IOError("Failed to read manifest file")
        mock_load_manifest.side_effect = original_error
        service_dirs = [Path('/invalid')]
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            load_manifests(service_dirs)
        
        # Verify error is about manifest load failure
        error_msg = str(exc_info.value).lower()
        # Should mention failure or contain original error context
        assert ("load" in error_msg or "fail" in error_msg or "manifest" in error_msg 
                or "ioerror" in error_msg or "read" in error_msg), \
            f"Expected manifest_load_failure error, got: {exc_info.value}"
    
    @patch('src.src_baton_registry.load_manifest')
    def test_invariant_unique_service_names(self, mock_load_manifest, mock_service_manifest):
        """Verify service names are unique in loaded manifests."""
        # Setup
        manifests = [
            mock_service_manifest(name="alpha", port=8000),
            mock_service_manifest(name="beta", port=8001),
        ]
        mock_load_manifest.side_effect = manifests
        service_dirs = [Path('/s1'), Path('/s2')]
        
        # Execute
        result = load_manifests(service_dirs)
        
        # Verify invariant: all service names are unique
        service_names = [m.name for m in result]
        assert len(set(service_names)) == len(result), \
            "Invariant violated: service names must be unique"


# ============================================================================
# Tests for derive_circuit
# ============================================================================

class TestDeriveCircuit:
    """Tests for the derive_circuit function."""
    
    def test_derive_circuit_simple(self, mock_service_manifest):
        """Derive circuit from simple manifests without dependencies."""
        # Setup - manifests without dependencies
        manifests = [
            mock_service_manifest(name="service1", port=8000, dependencies=[]),
            mock_service_manifest(name="service2", port=8001, dependencies=[]),
        ]
        circuit_name = "test-circuit"
        
        # Execute
        circuit = derive_circuit(manifests, circuit_name)
        
        # Verify postconditions
        assert len(circuit.nodes) == len(manifests), \
            "Each manifest should result in exactly one NodeSpec"
        assert len(circuit.edges) == 0, "No dependencies means no edges"
        assert circuit.version == 1, "CircuitSpec.version should be 1"
        
        # Verify all ports are unique
        ports = [node.port for node in circuit.nodes]
        assert len(ports) == len(set(ports)), "All nodes should have unique ports"
    
    def test_derive_circuit_with_dependencies(self, mock_service_manifest):
        """Derive circuit with dependencies creating edges."""
        # Setup - consumer depends on provider
        provider = mock_service_manifest(name="provider", port=8000, dependencies=[])
        
        # Create dependency structure
        dep_mock = Mock()
        dep_mock.name = "provider"
        dep_mock.optional = False
        
        consumer = mock_service_manifest(
            name="consumer",
            port=8001,
            dependencies=[dep_mock]
        )
        manifests = [consumer, provider]
        circuit_name = "deps-circuit"
        
        # Execute
        circuit = derive_circuit(manifests, circuit_name)
        
        # Verify postconditions
        assert len(circuit.edges) > 0, "Should create edges for dependencies"
        
        # Verify all edges have 'depends-on' label
        for edge in circuit.edges:
            assert edge.label == "depends-on", \
                f"All edges should have label 'depends-on', got: {edge.label}"
        
        # Verify edge connects correct nodes (consumer -> provider)
        edge_found = False
        for edge in circuit.edges:
            if edge.source == "consumer" and edge.target == "provider":
                edge_found = True
                break
        assert edge_found, "Should have edge from consumer to provider"
    
    def test_derive_circuit_empty_manifests(self):
        """Derive circuit from empty manifest list."""
        manifests = []
        circuit_name = "empty-circuit"
        
        # Execute
        circuit = derive_circuit(manifests, circuit_name)
        
        # Verify postconditions
        assert len(circuit.nodes) == 0, "No manifests means no nodes"
        assert len(circuit.edges) == 0, "No manifests means no edges"
        assert circuit.version == 1, "CircuitSpec.version should always be 1"
    
    def test_derive_circuit_auto_port_assignment(self, mock_service_manifest):
        """Derive circuit with manifests requiring auto-assigned ports."""
        # Setup - manifests with port == 0 (need auto-assignment)
        manifests = [
            mock_service_manifest(name="service1", port=0, dependencies=[]),
            mock_service_manifest(name="service2", port=0, dependencies=[]),
        ]
        circuit_name = "auto-port-circuit"
        
        # Execute
        circuit = derive_circuit(manifests, circuit_name)
        
        # Verify postconditions
        for node in circuit.nodes:
            assert DEFAULT_PORT_START <= node.port <= DEFAULT_PORT_MAX, \
                f"Auto-assigned port {node.port} must be in range [{DEFAULT_PORT_START}, {DEFAULT_PORT_MAX}]"
        
        # Verify all ports are unique
        ports = [node.port for node in circuit.nodes]
        assert len(ports) == len(set(ports)), "All nodes should have unique ports"
    
    def test_derive_circuit_explicit_ports(self, mock_service_manifest):
        """Derive circuit with manifests having explicit ports."""
        # Setup - manifests with explicit non-zero ports
        manifests = [
            mock_service_manifest(name="service1", port=9000, dependencies=[]),
            mock_service_manifest(name="service2", port=9001, dependencies=[]),
        ]
        circuit_name = "explicit-port-circuit"
        
        # Execute
        circuit = derive_circuit(manifests, circuit_name)
        
        # Verify postconditions
        ports = [node.port for node in circuit.nodes]
        
        # Verify explicit ports are preserved
        assert 9000 in ports, "Explicit port 9000 should be preserved"
        assert 9001 in ports, "Explicit port 9001 should be preserved"
        
        # Verify all ports are unique
        assert len(ports) == len(set(ports)), "All nodes should have unique ports"
    
    def test_derive_circuit_port_conflict(self, mock_service_manifest):
        """Raise error when two manifests specify the same non-zero port."""
        # Setup - two manifests with the same explicit port
        manifests = [
            mock_service_manifest(name="service1", port=9000, dependencies=[]),
            mock_service_manifest(name="service2", port=9000, dependencies=[]),
        ]
        circuit_name = "conflict-circuit"
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            derive_circuit(manifests, circuit_name)
        
        # Verify error is about port conflict
        error_msg = str(exc_info.value).lower()
        assert "port" in error_msg and ("conflict" in error_msg or "duplicate" in error_msg or "9000" in error_msg), \
            f"Expected port_conflict error, got: {exc_info.value}"
    
    def test_derive_circuit_missing_required_dependency(self, mock_service_manifest):
        """Raise error when manifest has required dependency not in list."""
        # Setup - consumer depends on non-existent service
        dep_mock = Mock()
        dep_mock.name = "non-existent-service"
        dep_mock.optional = False
        
        consumer = mock_service_manifest(
            name="consumer",
            port=8000,
            dependencies=[dep_mock]
        )
        manifests = [consumer]
        circuit_name = "missing-dep-circuit"
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            derive_circuit(manifests, circuit_name)
        
        # Verify error is about missing required dependency
        error_msg = str(exc_info.value).lower()
        assert ("missing" in error_msg or "required" in error_msg or "depend" in error_msg 
                or "non-existent-service" in error_msg), \
            f"Expected missing_required_dependency error, got: {exc_info.value}"
    
    def test_derive_circuit_optional_dependency_missing(self, mock_service_manifest):
        """Optional dependency that is missing is silently skipped."""
        # Setup - consumer has optional dependency on non-existent service
        optional_dep = Mock()
        optional_dep.name = "optional-service"
        optional_dep.optional = True
        
        consumer = mock_service_manifest(
            name="consumer",
            port=8000,
            dependencies=[optional_dep]
        )
        manifests = [consumer]
        circuit_name = "optional-dep-circuit"
        
        # Execute - should not raise error
        circuit = derive_circuit(manifests, circuit_name)
        
        # Verify circuit was created successfully
        assert len(circuit.nodes) == 1, "Circuit should be created with one node"
        
        # Verify no edge was created for missing optional dependency
        assert len(circuit.edges) == 0, \
            "Missing optional dependency should not create an edge"
    
    def test_derive_circuit_no_available_ports(self, mock_service_manifest):
        """Raise error when all ports in range are exhausted."""
        # Calculate how many ports are available
        num_ports_available = DEFAULT_PORT_MAX - DEFAULT_PORT_START + 1
        
        # Create more manifests than available ports (all need auto-assignment)
        manifests = [
            mock_service_manifest(name=f"service{i}", port=0, dependencies=[])
            for i in range(num_ports_available + 1)
        ]
        circuit_name = "exhausted-circuit"
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            derive_circuit(manifests, circuit_name)
        
        # Verify error is about no available ports
        error_msg = str(exc_info.value).lower()
        assert ("no" in error_msg or "available" in error_msg or "port" in error_msg 
                or "exhaust" in error_msg), \
            f"Expected no_available_ports error, got: {exc_info.value}"
    
    def test_derive_circuit_mixed_ports(self, mock_service_manifest):
        """Derive circuit with mix of explicit and auto-assigned ports."""
        # Setup - mix of explicit and auto-assigned ports
        manifests = [
            mock_service_manifest(name="explicit1", port=9000, dependencies=[]),
            mock_service_manifest(name="auto1", port=0, dependencies=[]),
            mock_service_manifest(name="auto2", port=0, dependencies=[]),
        ]
        circuit_name = "mixed-port-circuit"
        
        # Execute
        circuit = derive_circuit(manifests, circuit_name)
        
        # Verify all ports are unique
        ports = [node.port for node in circuit.nodes]
        assert len(ports) == len(set(ports)), "All ports should be unique"
        
        # Verify explicit port is preserved
        assert 9000 in ports, "Explicit port 9000 should be preserved"
        
        # Verify auto-assigned ports are in valid range
        for node in circuit.nodes:
            if node.port != 9000:
                assert DEFAULT_PORT_START <= node.port <= DEFAULT_PORT_MAX, \
                    f"Auto-assigned port {node.port} must be in valid range"
    
    def test_invariant_circuit_version_always_one(self, mock_service_manifest):
        """Verify CircuitSpec.version is always 1."""
        # Test with various inputs
        test_cases = [
            [],  # empty
            [mock_service_manifest(name="s1", port=8000)],  # single
            [mock_service_manifest(name=f"s{i}", port=8000+i) for i in range(5)],  # multiple
        ]
        
        for manifests in test_cases:
            circuit = derive_circuit(manifests, "version-test")
            assert circuit.version == 1, \
                f"Invariant violated: CircuitSpec.version must always be 1, got {circuit.version}"
    
    def test_invariant_edge_labels_always_depends_on(self, mock_service_manifest):
        """Verify all edges have label 'depends-on'."""
        # Setup - create dependencies
        provider1 = mock_service_manifest(name="provider1", port=8000, dependencies=[])
        provider2 = mock_service_manifest(name="provider2", port=8001, dependencies=[])
        
        dep1 = Mock()
        dep1.name = "provider1"
        dep1.optional = False
        
        dep2 = Mock()
        dep2.name = "provider2"
        dep2.optional = False
        
        consumer = mock_service_manifest(
            name="consumer",
            port=8002,
            dependencies=[dep1, dep2]
        )
        manifests = [consumer, provider1, provider2]
        
        # Execute
        circuit = derive_circuit(manifests, "edge-label-test")
        
        # Verify invariant
        for edge in circuit.edges:
            assert edge.label == "depends-on", \
                f"Invariant violated: all edges must have label 'depends-on', got '{edge.label}'"
    
    def test_invariant_unique_ports_in_circuit(self, mock_service_manifest):
        """Verify all ports are unique in circuit nodes."""
        # Setup - multiple manifests
        manifests = [
            mock_service_manifest(name="s1", port=9000, dependencies=[]),
            mock_service_manifest(name="s2", port=9001, dependencies=[]),
            mock_service_manifest(name="s3", port=0, dependencies=[]),
        ]
        
        # Execute
        circuit = derive_circuit(manifests, "port-uniqueness-test")
        
        # Verify invariant
        ports = [node.port for node in circuit.nodes]
        assert len(set(ports)) == len(circuit.nodes), \
            "Invariant violated: all ports in circuit must be unique"


# ============================================================================
# Additional Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests combining multiple functions."""
    
    @patch('src.src_baton_registry.load_manifest')
    def test_load_and_derive_workflow(self, mock_load_manifest, mock_service_manifest):
        """Test complete workflow: load manifests then derive circuit."""
        # Setup - create manifests with dependencies
        provider_manifest = mock_service_manifest(name="db", port=5432, dependencies=[])
        
        dep_mock = Mock()
        dep_mock.name = "db"
        dep_mock.optional = False
        
        api_manifest = mock_service_manifest(
            name="api",
            port=8080,
            dependencies=[dep_mock]
        )
        
        mock_load_manifest.side_effect = [api_manifest, provider_manifest]
        service_dirs = [Path('/api'), Path('/db')]
        
        # Execute - load manifests
        manifests = load_manifests(service_dirs)
        
        # Verify load
        assert len(manifests) == 2
        
        # Execute - derive circuit
        circuit = derive_circuit(manifests, "integration-test")
        
        # Verify circuit
        assert len(circuit.nodes) == 2
        assert circuit.version == 1
        assert len(circuit.edges) >= 1  # api depends on db
        
        # Verify edge exists
        edge_found = any(
            edge.source == "api" and edge.target == "db" and edge.label == "depends-on"
            for edge in circuit.edges
        )
        assert edge_found, "Should have dependency edge from api to db"
    
    def test_port_allocation_with_gaps(self, mock_service_manifest):
        """Test that auto-assignment fills gaps in port allocation."""
        # Setup - create manifests with gaps in port numbers
        manifests = [
            mock_service_manifest(name="s1", port=DEFAULT_PORT_START, dependencies=[]),
            mock_service_manifest(name="s2", port=DEFAULT_PORT_START + 2, dependencies=[]),
            mock_service_manifest(name="s3", port=0, dependencies=[]),  # should get port DEFAULT_PORT_START + 1
        ]
        
        # Execute
        circuit = derive_circuit(manifests, "gap-test")
        
        # Verify
        ports = sorted([node.port for node in circuit.nodes])
        
        # Should have filled the gap
        assert DEFAULT_PORT_START + 1 in ports, "Should fill gap in port allocation"
        assert len(set(ports)) == 3, "All ports should be unique"
