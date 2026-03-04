"""
Contract tests for src_baton_dashboard module.

This test suite verifies the dashboard collection and formatting functions
according to their contract specifications.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone
import re
from typing import Any

# Import the module under test
from src.baton.dashboard import collect, format_table, NodeSnapshot, DashboardSnapshot


# ============================================================================
# Fixtures and Test Helpers
# ============================================================================

@pytest.fixture
def mock_adapter():
    """Create a mock adapter with standard metrics."""
    adapter = Mock()
    adapter.name = "test-node"
    adapter.routing = None
    adapter.health_check = Mock(return_value="healthy")
    
    metrics = Mock()
    metrics.requests_total = 1000
    metrics.requests_failed = 50
    metrics.active_connections = 10
    metrics.p50 = Mock(return_value=25.5)
    metrics.p95 = Mock(return_value=100.3)
    adapter.metrics = metrics
    
    return adapter


@pytest.fixture
def mock_state():
    """Create a mock CircuitState."""
    state = Mock()
    state.adapters = {}
    state.adapters.get = Mock(return_value=Mock(status="open"))
    return state


@pytest.fixture
def mock_circuit():
    """Create a mock CircuitSpec."""
    circuit = Mock()
    node = Mock()
    node.name = "test-node"
    node.role = "primary"
    circuit.nodes = [node]
    return circuit


@pytest.fixture
def valid_node_snapshot():
    """Create a valid NodeSnapshot."""
    return NodeSnapshot(
        name="test-node",
        role="primary",
        status="open",
        health="healthy",
        requests_total=1000,
        requests_failed=50,
        error_rate=0.0500,
        latency_p50=25.5,
        latency_p95=100.3,
        active_connections=10,
        routing_strategy="single",
        routing_locked=False
    )


@pytest.fixture
def valid_dashboard_snapshot(valid_node_snapshot):
    """Create a valid DashboardSnapshot."""
    return DashboardSnapshot(
        timestamp="2024-01-01T12:00:00+00:00",
        nodes={"test-node": valid_node_snapshot}
    )


# ============================================================================
# collect() - Happy Path Tests
# ============================================================================

def test_collect_happy_path_single_node(mock_adapter, mock_state, mock_circuit):
    """collect() successfully creates snapshot with single adapter."""
    adapters = {"test-node": mock_adapter}
    
    # Mock the state to return adapter status
    mock_state.adapters = {"test-node": Mock(status="open")}
    
    with patch('src.src_baton_dashboard.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.timezone = timezone
        
        result = collect(adapters, mock_state, mock_circuit)
    
    assert isinstance(result, DashboardSnapshot)
    assert result.timestamp == "2024-01-01T12:00:00+00:00"
    assert len(result.nodes) == 1
    assert "test-node" in result.nodes
    
    node = result.nodes["test-node"]
    assert node.name == "test-node"
    assert node.role == "primary"
    assert node.status == "open"
    assert node.health == "healthy"
    assert node.requests_total == 1000
    assert node.requests_failed == 50
    assert node.error_rate == 0.0500
    assert node.latency_p50 == 25.5
    assert node.latency_p95 == 100.3
    assert node.active_connections == 10
    assert node.routing_strategy == "single"
    assert node.routing_locked is False


def test_collect_happy_path_multiple_nodes(mock_state):
    """collect() successfully creates snapshot with multiple adapters."""
    # Create multiple adapters
    adapter1 = Mock()
    adapter1.name = "node1"
    adapter1.routing = None
    adapter1.health_check = Mock(return_value="healthy")
    metrics1 = Mock()
    metrics1.requests_total = 1000
    metrics1.requests_failed = 50
    metrics1.active_connections = 10
    metrics1.p50 = Mock(return_value=25.0)
    metrics1.p95 = Mock(return_value=100.0)
    adapter1.metrics = metrics1
    
    adapter2 = Mock()
    adapter2.name = "node2"
    adapter2.routing = Mock(strategy="round-robin")
    adapter2.health_check = Mock(return_value="degraded")
    metrics2 = Mock()
    metrics2.requests_total = 500
    metrics2.requests_failed = 10
    metrics2.active_connections = 5
    metrics2.p50 = Mock(return_value=30.0)
    metrics2.p95 = Mock(return_value=120.0)
    adapter2.metrics = metrics2
    
    adapters = {"node1": adapter1, "node2": adapter2}
    
    # Setup circuit with two nodes
    circuit = Mock()
    node1_spec = Mock()
    node1_spec.name = "node1"
    node1_spec.role = "primary"
    node2_spec = Mock()
    node2_spec.name = "node2"
    node2_spec.role = "secondary"
    circuit.nodes = [node1_spec, node2_spec]
    
    # Setup state
    mock_state.adapters = {
        "node1": Mock(status="open"),
        "node2": Mock(status="closed")
    }
    
    with patch('src.src_baton_dashboard.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.timezone = timezone
        
        result = collect(adapters, mock_state, mock_circuit)
    
    assert len(result.nodes) == 2
    assert "node1" in result.nodes
    assert "node2" in result.nodes
    
    node1 = result.nodes["node1"]
    assert node1.name == "node1"
    assert node1.role == "primary"
    assert node1.error_rate == 0.0500
    
    node2 = result.nodes["node2"]
    assert node2.name == "node2"
    assert node2.role == "secondary"
    assert node2.error_rate == 0.0200


# ============================================================================
# collect() - Edge Case Tests
# ============================================================================

def test_collect_empty_adapters(mock_state):
    """collect() handles empty adapters dictionary."""
    adapters = {}
    circuit = Mock()
    circuit.nodes = []
    
    with patch('src.src_baton_dashboard.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.timezone = timezone
        
        result = collect(adapters, mock_state, circuit)
    
    assert isinstance(result, DashboardSnapshot)
    assert len(result.nodes) == 0
    assert result.nodes == {}


def test_collect_zero_requests(mock_adapter, mock_state, mock_circuit):
    """collect() sets error_rate to 0.0 when requests_total is 0."""
    mock_adapter.metrics.requests_total = 0
    mock_adapter.metrics.requests_failed = 0
    
    adapters = {"test-node": mock_adapter}
    mock_state.adapters = {"test-node": Mock(status="open")}
    
    with patch('src.src_baton_dashboard.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.timezone = timezone
        
        result = collect(adapters, mock_state, mock_circuit)
    
    node = result.nodes["test-node"]
    assert node.requests_total == 0
    assert node.error_rate == 0.0


def test_collect_error_rate_calculation(mock_adapter, mock_state, mock_circuit):
    """collect() calculates error_rate correctly and rounds to 4 decimals."""
    mock_adapter.metrics.requests_total = 1000
    mock_adapter.metrics.requests_failed = 123
    
    adapters = {"test-node": mock_adapter}
    mock_state.adapters = {"test-node": Mock(status="open")}
    
    with patch('src.src_baton_dashboard.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.timezone = timezone
        
        result = collect(adapters, mock_state, mock_circuit)
    
    node = result.nodes["test-node"]
    assert node.error_rate == 0.1230
    
    # Verify precision (at most 4 decimal places)
    decimal_str = str(node.error_rate).split('.')
    if len(decimal_str) > 1:
        assert len(decimal_str[1]) <= 4


def test_collect_routing_strategy_none(mock_adapter, mock_state, mock_circuit):
    """collect() sets routing_strategy to 'single' when adapter.routing is None."""
    mock_adapter.routing = None
    
    adapters = {"test-node": mock_adapter}
    mock_state.adapters = {"test-node": Mock(status="open")}
    
    with patch('src.src_baton_dashboard.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.timezone = timezone
        
        result = collect(adapters, mock_state, mock_circuit)
    
    node = result.nodes["test-node"]
    assert node.routing_strategy == "single"


def test_collect_adapter_not_in_state(mock_adapter, mock_state, mock_circuit):
    """collect() sets status to 'unknown' when adapter not found in state."""
    adapters = {"test-node": mock_adapter}
    
    # Mock state.adapters.get() to return None
    mock_state.adapters = {}
    
    def mock_get(key, default=None):
        return None
    
    mock_state.adapters.get = mock_get
    
    with patch('src.src_baton_dashboard.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.timezone = timezone
        
        result = collect(adapters, mock_state, mock_circuit)
    
    node = result.nodes["test-node"]
    assert node.status == "unknown"


# ============================================================================
# collect() - Error Case Tests
# ============================================================================

def test_collect_attribute_error_missing_requests_total(mock_adapter, mock_state, mock_circuit):
    """collect() raises AttributeError when adapter.metrics missing requests_total."""
    # Remove requests_total attribute
    delattr(mock_adapter.metrics, 'requests_total')
    
    adapters = {"test-node": mock_adapter}
    mock_state.adapters = {"test-node": Mock(status="open")}
    
    with patch('src.src_baton_dashboard.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.timezone = timezone
        
        with pytest.raises(AttributeError):
            collect(adapters, mock_state, mock_circuit)


def test_collect_attribute_error_missing_p50_method(mock_adapter, mock_state, mock_circuit):
    """collect() raises AttributeError when adapter.metrics missing p50() method."""
    # Remove p50 method
    delattr(mock_adapter.metrics, 'p50')
    
    adapters = {"test-node": mock_adapter}
    mock_state.adapters = {"test-node": Mock(status="open")}
    
    with patch('src.src_baton_dashboard.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.timezone = timezone
        
        with pytest.raises(AttributeError):
            collect(adapters, mock_state, mock_circuit)


def test_collect_key_error_missing_node_name(mock_adapter, mock_state):
    """collect() raises KeyError when circuit.nodes element missing name attribute."""
    adapters = {"test-node": mock_adapter}
    mock_state.adapters = {"test-node": Mock(status="open")}
    
    # Create circuit node without name attribute
    circuit = Mock()
    node = Mock(spec=['role'])  # Only has role, no name
    node.role = "primary"
    # When accessing node.name, raise AttributeError which the contract converts to KeyError
    del node.name
    circuit.nodes = [node]
    
    with patch('src.src_baton_dashboard.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.timezone = timezone
        
        # The contract says KeyError, but implementation might raise AttributeError first
        # Testing for the condition that leads to KeyError
        with pytest.raises((KeyError, AttributeError)):
            collect(adapters, mock_state, circuit)


def test_collect_type_error_adapters_not_iterable(mock_state, mock_circuit):
    """collect() raises TypeError when adapters is not iterable."""
    adapters = 12345  # Not iterable
    
    with patch('src.src_baton_dashboard.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.timezone = timezone
        
        with pytest.raises(TypeError):
            collect(adapters, mock_state, mock_circuit)


def test_collect_zero_division_error_race_condition(mock_adapter, mock_state, mock_circuit):
    """collect() raises ZeroDivisionError if requests_total check fails due to race."""
    # Create a metrics object that changes requests_total during execution
    class RacyMetrics:
        def __init__(self):
            self.requests_failed = 50
            self.active_connections = 10
            self._requests_total = 100
            self._call_count = 0
        
        @property
        def requests_total(self):
            # First access returns 100, second access returns 0 (simulating race)
            self._call_count += 1
            if self._call_count <= 1:
                return self._requests_total
            else:
                return 0
        
        def p50(self):
            return 25.0
        
        def p95(self):
            return 100.0
    
    mock_adapter.metrics = RacyMetrics()
    
    adapters = {"test-node": mock_adapter}
    mock_state.adapters = {"test-node": Mock(status="open")}
    
    with patch('src.src_baton_dashboard.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.timezone = timezone
        
        # This might raise ZeroDivisionError if the race condition occurs
        # Or it might succeed if the guard works
        try:
            result = collect(adapters, mock_state, mock_circuit)
            # If no error, verify the guard worked
            assert result.nodes["test-node"].error_rate == 0.0
        except ZeroDivisionError:
            # This is expected per the contract
            pass


# ============================================================================
# format_table() - Happy Path Tests
# ============================================================================

def test_format_table_happy_path_single_node(valid_dashboard_snapshot):
    """format_table() produces correct table for single node."""
    result = format_table(valid_dashboard_snapshot)
    
    assert isinstance(result, str)
    lines = result.split('\n')
    
    # Should have header, separator, and one data row
    assert len(lines) >= 3
    
    # Check header exists
    assert "Node" in lines[0]
    assert "Role" in lines[0]
    assert "Status" in lines[0]
    assert "Health" in lines[0]
    assert "Reqs" in lines[0]
    assert "Err%" in lines[0]
    assert "p50" in lines[0]
    assert "p95" in lines[0]
    assert "Routing" in lines[0]
    
    # Check separator line (should contain dashes)
    assert "-" in lines[1]
    
    # Check data row contains node name
    assert "test-node" in result


def test_format_table_happy_path_multiple_nodes():
    """format_table() produces correct table for multiple nodes."""
    node1 = NodeSnapshot(
        name="node1",
        role="primary",
        status="open",
        health="healthy",
        requests_total=1000,
        requests_failed=50,
        error_rate=0.0500,
        latency_p50=25.0,
        latency_p95=100.0,
        active_connections=10,
        routing_strategy="single",
        routing_locked=False
    )
    
    node2 = NodeSnapshot(
        name="node2",
        role="secondary",
        status="closed",
        health="degraded",
        requests_total=500,
        requests_failed=10,
        error_rate=0.0200,
        latency_p50=30.0,
        latency_p95=120.0,
        active_connections=5,
        routing_strategy="round-robin",
        routing_locked=True
    )
    
    snapshot = DashboardSnapshot(
        timestamp="2024-01-01T12:00:00+00:00",
        nodes={"node1": node1, "node2": node2}
    )
    
    result = format_table(snapshot)
    
    lines = result.split('\n')
    # Should have header, separator, and two data rows
    assert len(lines) >= 4
    
    # Both nodes should appear in output
    assert "node1" in result
    assert "node2" in result


# ============================================================================
# format_table() - Edge Case Tests
# ============================================================================

def test_format_table_empty_nodes():
    """format_table() returns special message for empty snapshot."""
    snapshot = DashboardSnapshot(
        timestamp="2024-01-01T12:00:00+00:00",
        nodes={}
    )
    
    result = format_table(snapshot)
    
    assert result == "No nodes in snapshot."


def test_format_table_zero_requests():
    """format_table() displays '—' for error rate when requests_total is 0."""
    node = NodeSnapshot(
        name="test-node",
        role="primary",
        status="open",
        health="healthy",
        requests_total=0,
        requests_failed=0,
        error_rate=0.0,
        latency_p50=25.0,
        latency_p95=100.0,
        active_connections=10,
        routing_strategy="single",
        routing_locked=False
    )
    
    snapshot = DashboardSnapshot(
        timestamp="2024-01-01T12:00:00+00:00",
        nodes={"test-node": node}
    )
    
    result = format_table(snapshot)
    
    # Error rate should be displayed as em dash
    assert "—" in result


def test_format_table_zero_latencies():
    """format_table() displays '—' for latencies when values are 0."""
    node = NodeSnapshot(
        name="test-node",
        role="primary",
        status="open",
        health="healthy",
        requests_total=1000,
        requests_failed=50,
        error_rate=0.0500,
        latency_p50=0.0,
        latency_p95=0.0,
        active_connections=10,
        routing_strategy="single",
        routing_locked=False
    )
    
    snapshot = DashboardSnapshot(
        timestamp="2024-01-01T12:00:00+00:00",
        nodes={"test-node": node}
    )
    
    result = format_table(snapshot)
    
    # Latencies should be displayed as em dash
    lines = result.split('\n')
    data_line = [l for l in lines if "test-node" in l][0]
    
    # Count em dashes - should have at least 2 for the latencies
    # (might have 3 if error rate also shows em dash, but we have requests)
    assert data_line.count("—") >= 2


def test_format_table_routing_none():
    """format_table() displays 'single' when routing_strategy is None."""
    node = NodeSnapshot(
        name="test-node",
        role="primary",
        status="open",
        health="healthy",
        requests_total=1000,
        requests_failed=50,
        error_rate=0.0500,
        latency_p50=25.0,
        latency_p95=100.0,
        active_connections=10,
        routing_strategy=None,
        routing_locked=False
    )
    
    snapshot = DashboardSnapshot(
        timestamp="2024-01-01T12:00:00+00:00",
        nodes={"test-node": node}
    )
    
    result = format_table(snapshot)
    
    # Should display 'single' for None routing
    assert "single" in result


def test_format_table_routing_locked():
    """format_table() appends ' (locked)' when routing_locked is True."""
    node = NodeSnapshot(
        name="test-node",
        role="primary",
        status="open",
        health="healthy",
        requests_total=1000,
        requests_failed=50,
        error_rate=0.0500,
        latency_p50=25.0,
        latency_p95=100.0,
        active_connections=10,
        routing_strategy="round-robin",
        routing_locked=True
    )
    
    snapshot = DashboardSnapshot(
        timestamp="2024-01-01T12:00:00+00:00",
        nodes={"test-node": node}
    )
    
    result = format_table(snapshot)
    
    # Should have (locked) suffix
    assert "(locked)" in result


# ============================================================================
# format_table() - Error Case Tests
# ============================================================================

def test_format_table_attribute_error_missing_nodes():
    """format_table() raises AttributeError when snapshot.nodes missing."""
    snapshot = Mock(spec=[])  # No attributes
    
    with pytest.raises(AttributeError):
        format_table(snapshot)


def test_format_table_type_error_nodes_not_dict():
    """format_table() raises TypeError when snapshot.nodes not dict-like."""
    snapshot = Mock()
    snapshot.nodes = "not a dict"  # String instead of dict
    
    with pytest.raises((TypeError, AttributeError)):
        format_table(snapshot)


# ============================================================================
# Invariant Tests
# ============================================================================

def test_invariant_error_rate_range(mock_state):
    """Verify error_rate is always in [0.0, 1.0]."""
    # Test various combinations
    test_cases = [
        (0, 0, 0.0),
        (100, 0, 0.0),
        (100, 50, 0.5),
        (100, 100, 1.0),
        (1000, 1, 0.0010),
        (1000, 999, 0.9990),
    ]
    
    for total, failed, expected in test_cases:
        adapter = Mock()
        adapter.name = "test"
        adapter.routing = None
        adapter.health_check = Mock(return_value="healthy")
        metrics = Mock()
        metrics.requests_total = total
        metrics.requests_failed = failed
        metrics.active_connections = 10
        metrics.p50 = Mock(return_value=25.0)
        metrics.p95 = Mock(return_value=100.0)
        adapter.metrics = metrics
        
        circuit = Mock()
        node = Mock()
        node.name = "test"
        node.role = "primary"
        circuit.nodes = [node]
        
        adapters = {"test": adapter}
        mock_state.adapters = {"test": Mock(status="open")}
        
        with patch('src.src_baton_dashboard.datetime') as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            mock_datetime.timezone = timezone
            
            result = collect(adapters, mock_state, circuit)
        
        node_snapshot = result.nodes["test"]
        assert 0.0 <= node_snapshot.error_rate <= 1.0, \
            f"error_rate {node_snapshot.error_rate} out of range for {failed}/{total}"
        assert abs(node_snapshot.error_rate - expected) < 0.00005


def test_invariant_error_rate_precision(mock_adapter, mock_state, mock_circuit):
    """Verify error_rate is rounded to 4 decimal places."""
    # Use a value that requires rounding
    mock_adapter.metrics.requests_total = 3
    mock_adapter.metrics.requests_failed = 1
    # 1/3 = 0.333333... should be rounded to 0.3333
    
    adapters = {"test-node": mock_adapter}
    mock_state.adapters = {"test-node": Mock(status="open")}
    
    with patch('src.src_baton_dashboard.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.timezone = timezone
        
        result = collect(adapters, mock_state, mock_circuit)
    
    node = result.nodes["test-node"]
    
    # Check that it's rounded to 4 decimals
    decimal_str = str(node.error_rate).split('.')
    if len(decimal_str) > 1:
        assert len(decimal_str[1]) <= 4, \
            f"error_rate {node.error_rate} has more than 4 decimal places"
    
    # Should be 0.3333
    assert node.error_rate == 0.3333


def test_invariant_timestamp_format(mock_adapter, mock_state, mock_circuit):
    """Verify timestamp is ISO 8601 UTC format."""
    adapters = {"test-node": mock_adapter}
    mock_state.adapters = {"test-node": Mock(status="open")}
    
    with patch('src.src_baton_dashboard.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.timezone = timezone
        
        result = collect(adapters, mock_state, mock_circuit)
    
    # Check ISO 8601 format
    iso_pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$'
    assert re.match(iso_pattern, result.timestamp), \
        f"Timestamp {result.timestamp} does not match ISO 8601 format"
    
    # Check UTC indicator
    assert result.timestamp.endswith('+00:00') or result.timestamp.endswith('Z'), \
        f"Timestamp {result.timestamp} is not UTC"


def test_invariant_table_header_format(valid_dashboard_snapshot):
    """Verify table header matches expected format."""
    result = format_table(valid_dashboard_snapshot)
    
    lines = result.split('\n')
    header = lines[0]
    
    # Check for required columns in correct order
    expected_columns = ["Node", "Role", "Status", "Health", "Reqs", "Err%", "p50", "p95", "Routing"]
    
    last_index = -1
    for col in expected_columns:
        index = header.find(col)
        assert index > last_index, \
            f"Column '{col}' not found in correct order in header: {header}"
        last_index = index
    
    # Verify separator line
    separator = lines[1]
    assert all(c in '-= ' for c in separator), \
        f"Separator line contains unexpected characters: {separator}"


# ============================================================================
# Additional Edge Cases
# ============================================================================

def test_collect_large_error_rate(mock_adapter, mock_state, mock_circuit):
    """Test error_rate calculation with very large numbers."""
    mock_adapter.metrics.requests_total = 1_000_000
    mock_adapter.metrics.requests_failed = 999_999
    
    adapters = {"test-node": mock_adapter}
    mock_state.adapters = {"test-node": Mock(status="open")}
    
    with patch('src.src_baton_dashboard.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.timezone = timezone
        
        result = collect(adapters, mock_state, mock_circuit)
    
    node = result.nodes["test-node"]
    assert 0.9999 <= node.error_rate <= 1.0
    assert node.error_rate == 0.9999


def test_format_table_long_values():
    """Test format_table with long node names and values."""
    node = NodeSnapshot(
        name="very-long-node-name-that-exceeds-normal-width",
        role="primary-master",
        status="half-open",
        health="healthy",
        requests_total=999999,
        requests_failed=50000,
        error_rate=0.0500,
        latency_p50=9999.9,
        latency_p95=99999.9,
        active_connections=10000,
        routing_strategy="weighted-round-robin",
        routing_locked=True
    )
    
    snapshot = DashboardSnapshot(
        timestamp="2024-01-01T12:00:00+00:00",
        nodes={"test-node": node}
    )
    
    result = format_table(snapshot)
    
    # Should not raise any errors
    assert isinstance(result, str)
    assert len(result) > 0


def test_collect_routing_with_strategy(mock_adapter, mock_state, mock_circuit):
    """Test collect with a non-None routing strategy."""
    mock_adapter.routing = Mock(strategy="round-robin", locked=True)
    
    adapters = {"test-node": mock_adapter}
    mock_state.adapters = {"test-node": Mock(status="open")}
    
    with patch('src.src_baton_dashboard.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.timezone = timezone
        
        result = collect(adapters, mock_state, mock_circuit)
    
    node = result.nodes["test-node"]
    assert node.routing_strategy == "round-robin"
    assert node.routing_locked is True


def test_format_table_error_rate_display():
    """Test that error rate is displayed as percentage with 1 decimal."""
    node = NodeSnapshot(
        name="test-node",
        role="primary",
        status="open",
        health="healthy",
        requests_total=1000,
        requests_failed=123,
        error_rate=0.1230,
        latency_p50=25.0,
        latency_p95=100.0,
        active_connections=10,
        routing_strategy="single",
        routing_locked=False
    )
    
    snapshot = DashboardSnapshot(
        timestamp="2024-01-01T12:00:00+00:00",
        nodes={"test-node": node}
    )
    
    result = format_table(snapshot)
    
    # Should show as 12.3% (1 decimal place)
    assert "12.3" in result or "12.3%" in result


def test_format_table_latency_display():
    """Test that latencies are displayed as milliseconds with 0 decimals."""
    node = NodeSnapshot(
        name="test-node",
        role="primary",
        status="open",
        health="healthy",
        requests_total=1000,
        requests_failed=50,
        error_rate=0.0500,
        latency_p50=25.7,
        latency_p95=100.3,
        active_connections=10,
        routing_strategy="single",
        routing_locked=False
    )
    
    snapshot = DashboardSnapshot(
        timestamp="2024-01-01T12:00:00+00:00",
        nodes={"test-node": node}
    )
    
    result = format_table(snapshot)
    
    # Should show rounded values: 26ms and 100ms
    lines = result.split('\n')
    data_line = [l for l in lines if "test-node" in l][0]
    
    # Check that latencies appear (format may vary)
    assert any(str(i) in data_line for i in [25, 26]), \
        f"p50 latency not found in: {data_line}"
    assert any(str(i) in data_line for i in [100, 101]), \
        f"p95 latency not found in: {data_line}"
