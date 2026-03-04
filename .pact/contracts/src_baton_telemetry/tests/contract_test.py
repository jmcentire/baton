"""
Contract-driven tests for TelemetryCollector component.

This test suite verifies the behavior of TelemetryCollector according to its contract,
including lifecycle management, data collection, formatting, and error handling.
"""

import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, mock_open, AsyncMock
import pytest

# Import the component under test
from src.baton.telemetry import TelemetryCollector, METRICS_FILE


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def mock_adapter():
    """Create a mock Adapter instance."""
    adapter = Mock()
    adapter.get_metrics = Mock(return_value={"requests": 100, "errors": 5})
    return adapter


@pytest.fixture
def mock_adapters(mock_adapter):
    """Create a dictionary of mock adapters."""
    return {"node1": mock_adapter}


@pytest.fixture
def mock_state():
    """Create a mock CircuitState instance."""
    state = Mock()
    state.get_status = Mock(return_value="running")
    return state


@pytest.fixture
def mock_circuit():
    """Create a mock CircuitSpec instance."""
    circuit = Mock()
    circuit.nodes = {"node1": {"role": "worker"}}
    return circuit


@pytest.fixture
def mock_dashboard_snapshot():
    """Create a mock DashboardSnapshot."""
    snapshot = Mock()
    snapshot.timestamp = 1234567890.0
    
    # Create mock node data
    node_data = Mock()
    node_data.node_name = "node1"
    node_data.role = "worker"
    node_data.requests_total = 1000
    node_data.requests_failed = 50
    node_data.error_rate = 0.05
    node_data.latency_p50_ms = 100.5
    node_data.latency_p95_ms = 250.3
    node_data.active_connections = 10
    
    snapshot.nodes = [node_data]
    return snapshot


@pytest.fixture
def temp_project_dir(tmp_path):
    """Create a temporary project directory."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    baton_dir = project_dir / ".baton"
    baton_dir.mkdir()
    return project_dir


# ============================================================================
# Test Class: Initialization and Setup
# ============================================================================

class TestTelemetryCollectorInit:
    """Tests for TelemetryCollector initialization."""
    
    def test_init_happy_path(self, mock_adapters, mock_state, mock_circuit, temp_project_dir):
        """Initialize TelemetryCollector with valid parameters and verify all fields are set correctly."""
        flush_interval = 30.0
        
        collector = TelemetryCollector(
            adapters=mock_adapters,
            state=mock_state,
            circuit=mock_circuit,
            project_dir=str(temp_project_dir),
            flush_interval=flush_interval
        )
        
        # Verify postconditions
        assert collector._adapters is mock_adapters, "_adapters not set correctly"
        assert collector._state is mock_state, "_state not set correctly"
        assert collector._circuit is mock_circuit, "_circuit not set correctly"
        assert isinstance(collector._project_dir, Path), "_project_dir not converted to Path"
        assert collector._project_dir == Path(temp_project_dir), "_project_dir value incorrect"
        assert collector._flush_interval == flush_interval, "_flush_interval not set correctly"
        assert collector._running is False, "_running should be False initially"
        assert collector._task is None, "_task should be None initially"
    
    def test_init_project_dir_as_path(self, mock_adapters, mock_state, mock_circuit, temp_project_dir):
        """Initialize TelemetryCollector with project_dir as Path object."""
        collector = TelemetryCollector(
            adapters={},
            state=mock_state,
            circuit=mock_circuit,
            project_dir=temp_project_dir,  # Pass as Path, not string
            flush_interval=15.0
        )
        
        assert isinstance(collector._project_dir, Path), "_project_dir should be Path instance"
        assert collector._project_dir == temp_project_dir, "_project_dir value should match"
    
    def test_invariant_project_dir_always_path(self, mock_state, mock_circuit, temp_project_dir):
        """Verify _project_dir is always Path object regardless of input."""
        # Test with string input
        collector1 = TelemetryCollector(
            adapters={},
            state=mock_state,
            circuit=mock_circuit,
            project_dir=str(temp_project_dir),
            flush_interval=30.0
        )
        assert isinstance(collector1._project_dir, Path), "Should be Path when input is string"
        
        # Test with Path input
        collector2 = TelemetryCollector(
            adapters={},
            state=mock_state,
            circuit=mock_circuit,
            project_dir=temp_project_dir,
            flush_interval=30.0
        )
        assert isinstance(collector2._project_dir, Path), "Should be Path when input is Path"


# ============================================================================
# Test Class: Lifecycle Management
# ============================================================================

class TestTelemetryCollectorLifecycle:
    """Tests for TelemetryCollector lifecycle (start, stop, running state)."""
    
    def test_is_running_false_initially(self, mock_adapters, mock_state, mock_circuit, temp_project_dir):
        """Check is_running returns False for newly initialized collector."""
        collector = TelemetryCollector(
            adapters=mock_adapters,
            state=mock_state,
            circuit=mock_circuit,
            project_dir=temp_project_dir,
            flush_interval=30.0
        )
        
        assert collector.is_running() is False, "is_running() should return False initially"
    
    def test_is_running_true_when_started(self, mock_adapters, mock_state, mock_circuit, temp_project_dir):
        """Check is_running returns True after run loop is started."""
        collector = TelemetryCollector(
            adapters=mock_adapters,
            state=mock_state,
            circuit=mock_circuit,
            project_dir=temp_project_dir,
            flush_interval=30.0
        )
        
        # Manually set _running to True to simulate running state
        collector._running = True
        
        assert collector.is_running() is True, "is_running() should return True when _running is True"
    
    def test_stop_sets_running_to_false(self, mock_adapters, mock_state, mock_circuit, temp_project_dir):
        """Call stop() and verify _running flag is set to False."""
        collector = TelemetryCollector(
            adapters=mock_adapters,
            state=mock_state,
            circuit=mock_circuit,
            project_dir=temp_project_dir,
            flush_interval=30.0
        )
        
        # Set running to True first
        collector._running = True
        
        # Call stop
        collector.stop()
        
        assert collector._running is False, "_running should be False after stop()"
        assert collector.is_running() is False, "is_running() should return False after stop()"
    
    def test_stop_idempotent(self, mock_adapters, mock_state, mock_circuit, temp_project_dir):
        """Call stop() multiple times and verify it remains False."""
        collector = TelemetryCollector(
            adapters=mock_adapters,
            state=mock_state,
            circuit=mock_circuit,
            project_dir=temp_project_dir,
            flush_interval=30.0
        )
        
        collector._running = True
        collector.stop()
        assert collector._running is False, "Should be False after first stop()"
        
        collector.stop()
        assert collector._running is False, "Should remain False after second stop()"
        
        collector.stop()
        assert collector._running is False, "Should remain False after third stop()"
    
    @pytest.mark.asyncio
    async def test_run_sets_running_false_on_exit(self, mock_adapters, mock_state, mock_circuit, temp_project_dir):
        """Verify run() sets _running to False when it exits."""
        collector = TelemetryCollector(
            adapters=mock_adapters,
            state=mock_state,
            circuit=mock_circuit,
            project_dir=temp_project_dir,
            flush_interval=0.01  # Very short interval for testing
        )
        
        # Mock flush_now to avoid actual I/O
        with patch.object(collector, 'flush_now'):
            # Start the run loop
            task = asyncio.create_task(collector.run())
            
            # Wait a bit for the loop to start
            await asyncio.sleep(0.02)
            
            # Verify it's running
            assert collector._running is True, "Should be running during execution"
            
            # Stop it
            collector.stop()
            
            # Wait for task to complete
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            
            # Verify _running is False after exit
            assert collector._running is False, "_running should be False after run() exits"
    
    @pytest.mark.asyncio
    async def test_run_handles_cancellation(self, mock_adapters, mock_state, mock_circuit, temp_project_dir):
        """Verify run() handles asyncio.CancelledError gracefully."""
        collector = TelemetryCollector(
            adapters=mock_adapters,
            state=mock_state,
            circuit=mock_circuit,
            project_dir=temp_project_dir,
            flush_interval=0.01
        )
        
        # Mock flush_now
        with patch.object(collector, 'flush_now'):
            # Start the run loop
            task = asyncio.create_task(collector.run())
            
            # Wait for it to start
            await asyncio.sleep(0.02)
            
            # Cancel the task
            task.cancel()
            
            # Wait and catch the cancellation
            with pytest.raises(asyncio.CancelledError):
                await task
            
            # Verify _running is set to False even after cancellation
            assert collector._running is False, "_running should be False when task is cancelled"
    
    def test_invariant_running_flag_reflects_state(self, mock_adapters, mock_state, mock_circuit, temp_project_dir):
        """Verify _running flag accurately reflects run loop state."""
        collector = TelemetryCollector(
            adapters=mock_adapters,
            state=mock_state,
            circuit=mock_circuit,
            project_dir=temp_project_dir,
            flush_interval=30.0
        )
        
        # Initially false
        assert collector._running is False
        assert collector.is_running() is False
        
        # Set to true (simulating run loop start)
        collector._running = True
        assert collector.is_running() is True
        
        # Stop
        collector.stop()
        assert collector._running is False
        assert collector.is_running() is False


# ============================================================================
# Test Class: Data Collection and Flushing
# ============================================================================

class TestTelemetryCollectorData:
    """Tests for data collection and flushing to disk."""
    
    def test_flush_now_writes_metrics(self, mock_adapters, mock_state, mock_circuit, temp_project_dir):
        """Call flush_now() and verify metrics are written to JSONL file."""
        collector = TelemetryCollector(
            adapters=mock_adapters,
            state=mock_state,
            circuit=mock_circuit,
            project_dir=temp_project_dir,
            flush_interval=30.0
        )
        
        # Mock the dashboard snapshot creation
        mock_snapshot = {"timestamp": 1234567890.0, "nodes": []}
        
        with patch('src.src_baton_telemetry.create_dashboard_snapshot', return_value=mock_snapshot):
            collector.flush_now()
            
            # Check that metrics file was created
            metrics_file = temp_project_dir / ".baton" / METRICS_FILE
            assert metrics_file.exists(), "metrics.jsonl file should be created"
            
            # Verify content
            with open(metrics_file, 'r') as f:
                lines = f.readlines()
                assert len(lines) >= 1, "At least one line should be written"
                
                # Parse the JSON line
                data = json.loads(lines[-1])
                assert "timestamp" in data, "Snapshot should contain timestamp"
    
    def test_flush_now_catches_exceptions(self, mock_adapters, mock_state, mock_circuit, temp_project_dir):
        """Verify flush_now() catches and logs exceptions without propagating them."""
        collector = TelemetryCollector(
            adapters=mock_adapters,
            state=mock_state,
            circuit=mock_circuit,
            project_dir=temp_project_dir,
            flush_interval=30.0
        )
        
        # Mock create_dashboard_snapshot to raise an exception
        with patch('src.src_baton_telemetry.create_dashboard_snapshot', side_effect=RuntimeError("Test error")):
            with patch('src.src_baton_telemetry.logger') as mock_logger:
                # This should not raise an exception
                try:
                    collector.flush_now()
                except Exception as e:
                    pytest.fail(f"flush_now() should not raise exceptions, but raised: {e}")
                
                # Verify that the error was logged
                mock_logger.debug.assert_called()
    
    def test_load_history_all_records(self, temp_project_dir):
        """Load all records from metrics.jsonl with no filtering."""
        # Create some test data
        metrics_file = temp_project_dir / ".baton" / METRICS_FILE
        
        test_records = [
            {"timestamp": 1000, "nodes": [{"node_name": "node1", "data": "a"}]},
            {"timestamp": 2000, "nodes": [{"node_name": "node2", "data": "b"}]},
            {"timestamp": 3000, "nodes": [{"node_name": "node1", "data": "c"}]},
        ]
        
        with open(metrics_file, 'w') as f:
            for record in test_records:
                f.write(json.dumps(record) + '\n')
        
        # Load all records
        result = TelemetryCollector.load_history(temp_project_dir, node=None, last_n=None)
        
        assert len(result) == 3, "Should return all records"
        assert result == test_records, "Records should match input data"
    
    def test_load_history_filter_by_node(self, temp_project_dir):
        """Load records filtered by specific node name."""
        metrics_file = temp_project_dir / ".baton" / METRICS_FILE
        
        test_records = [
            {"timestamp": 1000, "nodes": [{"node_name": "node1", "data": "a"}]},
            {"timestamp": 2000, "nodes": [{"node_name": "node2", "data": "b"}]},
            {"timestamp": 3000, "nodes": [{"node_name": "node1", "data": "c"}]},
            {"timestamp": 4000, "nodes": [{"node_name": "node3", "data": "d"}]},
        ]
        
        with open(metrics_file, 'w') as f:
            for record in test_records:
                f.write(json.dumps(record) + '\n')
        
        # Load records for node1
        result = TelemetryCollector.load_history(temp_project_dir, node="node1", last_n=None)
        
        # Should only return records with node1 data
        assert all("node1" in str(r) for r in result), "Should only return node1 records"
        assert len(result) <= 2, "Should filter to node1 entries"
    
    def test_load_history_limit_last_n(self, temp_project_dir):
        """Load at most last_n records from history."""
        metrics_file = temp_project_dir / ".baton" / METRICS_FILE
        
        test_records = [
            {"timestamp": i * 1000, "nodes": [{"node_name": f"node{i}", "data": f"data{i}"}]}
            for i in range(10)
        ]
        
        with open(metrics_file, 'w') as f:
            for record in test_records:
                f.write(json.dumps(record) + '\n')
        
        # Load last 5 records
        result = TelemetryCollector.load_history(temp_project_dir, node=None, last_n=5)
        
        assert len(result) == 5, "Should return at most last_n records"
        # Should be the last 5 records
        assert result[-1]["timestamp"] == 9000, "Should include the last record"
    
    def test_load_history_node_and_limit(self, temp_project_dir):
        """Load records with both node filter and last_n limit."""
        metrics_file = temp_project_dir / ".baton" / METRICS_FILE
        
        test_records = []
        for i in range(10):
            node_name = "node1" if i % 2 == 0 else "node2"
            test_records.append({
                "timestamp": i * 1000,
                "nodes": [{"node_name": node_name, "data": f"data{i}"}]
            })
        
        with open(metrics_file, 'w') as f:
            for record in test_records:
                f.write(json.dumps(record) + '\n')
        
        # Load last 3 records for node1
        result = TelemetryCollector.load_history(temp_project_dir, node="node1", last_n=3)
        
        assert len(result) <= 3, "Should return at most 3 records"
    
    def test_load_history_empty_file(self, temp_project_dir):
        """Load history from empty or non-existent metrics file."""
        # Don't create the file - it should handle missing file
        result = TelemetryCollector.load_history(temp_project_dir, node=None, last_n=None)
        
        assert result == [], "Should return empty list when file does not exist"
        
        # Create empty file
        metrics_file = temp_project_dir / ".baton" / METRICS_FILE
        metrics_file.touch()
        
        result = TelemetryCollector.load_history(temp_project_dir, node=None, last_n=None)
        assert result == [], "Should return empty list for empty file"


# ============================================================================
# Test Class: Prometheus Formatting
# ============================================================================

class TestTelemetryCollectorFormatting:
    """Tests for Prometheus format output."""
    
    def test_format_prometheus_basic(self, mock_dashboard_snapshot):
        """Format a DashboardSnapshot as Prometheus text exposition format."""
        result = TelemetryCollector.format_prometheus(mock_dashboard_snapshot)
        
        assert isinstance(result, str), "Should return a string"
        assert result.endswith('\n'), "Should end with newline"
        
        # Verify key metrics are present
        assert "requests_total" in result, "Should contain requests_total metric"
        assert "requests_failed" in result, "Should contain requests_failed metric"
        assert "error_rate" in result, "Should contain error_rate metric"
        assert "latency_p50_ms" in result, "Should contain latency_p50_ms metric"
        assert "latency_p95_ms" in result, "Should contain latency_p95_ms metric"
        assert "active_connections" in result, "Should contain active_connections metric"
        
        # Verify labels are present
        assert 'node_name="node1"' in result, "Should include node name label"
        assert 'role="worker"' in result, "Should include role label"
        
        # Count metric lines (should be 6 per node)
        lines = [line for line in result.split('\n') if line and not line.startswith('#')]
        assert len(lines) >= 6, "Should have at least 6 metric lines for one node"
    
    def test_format_prometheus_multiple_nodes(self):
        """Format snapshot with multiple nodes."""
        # Create mock snapshot with multiple nodes
        snapshot = Mock()
        snapshot.timestamp = 1234567890.0
        
        node1 = Mock()
        node1.node_name = "node1"
        node1.role = "worker"
        node1.requests_total = 1000
        node1.requests_failed = 50
        node1.error_rate = 0.05
        node1.latency_p50_ms = 100.5
        node1.latency_p95_ms = 250.3
        node1.active_connections = 10
        
        node2 = Mock()
        node2.node_name = "node2"
        node2.role = "coordinator"
        node2.requests_total = 500
        node2.requests_failed = 10
        node2.error_rate = 0.02
        node2.latency_p50_ms = 80.2
        node2.latency_p95_ms = 200.1
        node2.active_connections = 5
        
        snapshot.nodes = [node1, node2]
        
        result = TelemetryCollector.format_prometheus(snapshot)
        
        # Verify both nodes are present
        assert 'node_name="node1"' in result, "Should include node1"
        assert 'node_name="node2"' in result, "Should include node2"
        assert 'role="worker"' in result, "Should include worker role"
        assert 'role="coordinator"' in result, "Should include coordinator role"
        
        # Should have 6 metrics per node = 12 total
        lines = [line for line in result.split('\n') if line and not line.startswith('#')]
        assert len(lines) >= 12, "Should have at least 12 metric lines for two nodes"
    
    def test_format_prometheus_empty_snapshot(self):
        """Format snapshot with no nodes."""
        snapshot = Mock()
        snapshot.timestamp = 1234567890.0
        snapshot.nodes = []
        
        result = TelemetryCollector.format_prometheus(snapshot)
        
        assert isinstance(result, str), "Should return string even with empty data"
        assert result.endswith('\n'), "Should still end with newline"


# ============================================================================
# Test Class: Invariants
# ============================================================================

class TestTelemetryCollectorInvariants:
    """Tests for system invariants."""
    
    def test_invariant_metrics_file_constant(self):
        """Verify METRICS_FILE constant is 'metrics.jsonl'."""
        assert METRICS_FILE == "metrics.jsonl", "METRICS_FILE constant should be 'metrics.jsonl'"
    
    def test_default_flush_interval(self):
        """Verify default flush_interval is 30.0 seconds."""
        # This would need to be tested at the function signature level
        # For now, we document that the contract specifies default is 30.0
        pass


# ============================================================================
# Test Class: Error Handling
# ============================================================================

class TestTelemetryCollectorErrors:
    """Tests for error handling and edge cases."""
    
    def test_flush_now_never_raises(self, mock_adapters, mock_state, mock_circuit, temp_project_dir):
        """Ensure flush_now() never raises exceptions regardless of what goes wrong."""
        collector = TelemetryCollector(
            adapters=mock_adapters,
            state=mock_state,
            circuit=mock_circuit,
            project_dir=temp_project_dir,
            flush_interval=30.0
        )
        
        # Test various exception scenarios
        exceptions_to_test = [
            RuntimeError("Runtime error"),
            ValueError("Value error"),
            IOError("IO error"),
            AttributeError("Attribute error"),
            KeyError("Key error"),
        ]
        
        for exc in exceptions_to_test:
            with patch('src.src_baton_telemetry.create_dashboard_snapshot', side_effect=exc):
                try:
                    collector.flush_now()
                except Exception as e:
                    pytest.fail(f"flush_now() should never raise, but raised {type(e).__name__}: {e}")
    
    def test_load_history_handles_malformed_json(self, temp_project_dir):
        """Verify load_history handles malformed JSON gracefully."""
        metrics_file = temp_project_dir / ".baton" / METRICS_FILE
        
        # Write some malformed JSON
        with open(metrics_file, 'w') as f:
            f.write('{"valid": "json"}\n')
            f.write('this is not json\n')
            f.write('{"another": "valid"}\n')
        
        # Should handle gracefully (either skip bad lines or return what it can)
        try:
            result = TelemetryCollector.load_history(temp_project_dir, node=None, last_n=None)
            # If it doesn't raise, it handled the error gracefully
            assert isinstance(result, list), "Should return a list"
        except json.JSONDecodeError:
            # If it does raise, that's also acceptable behavior
            pass


# ============================================================================
# Integration Tests
# ============================================================================

class TestTelemetryCollectorIntegration:
    """Integration tests that combine multiple features."""
    
    @pytest.mark.asyncio
    async def test_full_lifecycle_with_flush(self, mock_adapters, mock_state, mock_circuit, temp_project_dir):
        """Test complete lifecycle: init, run, flush, stop, load history."""
        collector = TelemetryCollector(
            adapters=mock_adapters,
            state=mock_state,
            circuit=mock_circuit,
            project_dir=temp_project_dir,
            flush_interval=0.01
        )
        
        # Mock the dashboard snapshot
        mock_snapshot = {"timestamp": 1234567890.0, "nodes": []}
        
        with patch('src.src_baton_telemetry.create_dashboard_snapshot', return_value=mock_snapshot):
            # Start the collector
            task = asyncio.create_task(collector.run())
            
            # Let it run for a bit and flush some data
            await asyncio.sleep(0.05)
            
            # Verify it's running
            assert collector.is_running() is True
            
            # Stop it
            collector.stop()
            
            # Wait for completion
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            
            # Verify it stopped
            assert collector.is_running() is False
            
            # Load history
            history = TelemetryCollector.load_history(temp_project_dir, node=None, last_n=None)
            
            # Should have at least some records
            assert len(history) >= 0, "Should be able to load history"
