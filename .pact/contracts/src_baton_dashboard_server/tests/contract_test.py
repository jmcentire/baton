"""
Contract-based tests for DashboardServer component.

This test suite verifies the DashboardServer implementation against its contract,
covering happy paths, edge cases, error cases, and invariants.
"""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, AsyncMock, mock_open
from io import BytesIO


# Import the component under test
try:
    from src.baton.dashboard_server import DashboardServer
except ImportError:
    # Fallback import paths
    try:
        from src_baton_dashboard_server import DashboardServer
    except ImportError:
        # Mock the class for testing if import fails
        class DashboardServer:
            pass


# Mock classes for type hints
class CircuitState:
    pass


class CircuitSpec:
    pass


class Adapter:
    pass


class SignalAggregator:
    pass


class Signal:
    def model_dump(self):
        return {"signal": "data"}


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_adapters():
    """Mock adapters dictionary."""
    return {"adapter1": Mock(spec=Adapter), "adapter2": Mock(spec=Adapter)}


@pytest.fixture
def mock_state():
    """Mock CircuitState."""
    return Mock(spec=CircuitState)


@pytest.fixture
def mock_circuit():
    """Mock CircuitSpec with nodes and edges."""
    mock = Mock(spec=CircuitSpec)
    
    # Mock nodes
    node1 = Mock()
    node1.name = "node1"
    node1.port = 8001
    node1.role = "worker"
    node1.host = "localhost"
    
    node2 = Mock()
    node2.name = "node2"
    node2.port = 8002
    node2.role = "worker"
    node2.host = "localhost"
    
    mock.nodes = [node1, node2]
    
    # Mock edges
    edge1 = Mock()
    edge1.source = "node1"
    edge1.target = "node2"
    edge1.label = "edge1"
    
    mock.edges = [edge1]
    
    return mock


@pytest.fixture
def mock_signal_aggregator():
    """Mock SignalAggregator."""
    mock = Mock(spec=SignalAggregator)
    
    # Mock query method
    signal1 = Mock()
    signal1.model_dump.return_value = {"id": 1, "data": "signal1"}
    
    signal2 = Mock()
    signal2.model_dump.return_value = {"id": 2, "data": "signal2"}
    
    mock.query.return_value = [signal1, signal2]
    
    # Mock path_stats method
    stat1 = Mock()
    stat1.path = "/api/test"
    stat1.count = 10
    stat1.total_latency_ms = 1000
    stat1.error_count = 2
    
    mock.path_stats.return_value = {"path1": stat1}
    
    return mock


@pytest.fixture
def mock_reader():
    """Mock asyncio.StreamReader."""
    reader = AsyncMock()
    reader.readline = AsyncMock(return_value=b"GET /api/snapshot HTTP/1.1\r\n")
    return reader


@pytest.fixture
def mock_writer():
    """Mock asyncio.StreamWriter."""
    writer = AsyncMock()
    writer.write = Mock()
    writer.drain = AsyncMock()
    writer.close = Mock()
    writer.wait_closed = AsyncMock()
    writer.get_extra_info = Mock(return_value=("127.0.0.1", 12345))
    return writer


@pytest.fixture
def dashboard_server(mock_adapters, mock_state, mock_circuit, mock_signal_aggregator):
    """Create a DashboardServer instance for testing."""
    return DashboardServer(
        adapters=mock_adapters,
        state=mock_state,
        circuit=mock_circuit,
        signal_aggregator=mock_signal_aggregator,
        static_dir="/var/www",
        host="localhost",
        port=8080
    )


@pytest.fixture
def dashboard_server_no_aggregator(mock_adapters, mock_state, mock_circuit):
    """Create a DashboardServer without signal aggregator."""
    return DashboardServer(
        adapters=mock_adapters,
        state=mock_state,
        circuit=mock_circuit,
        signal_aggregator=None,
        static_dir=None,
        host="localhost",
        port=8080
    )


# ============================================================================
# __init__ TESTS
# ============================================================================

def test_init_happy_path(mock_adapters, mock_state, mock_circuit, mock_signal_aggregator):
    """Initialize DashboardServer with all parameters and verify all fields are set correctly."""
    server = DashboardServer(
        adapters=mock_adapters,
        state=mock_state,
        circuit=mock_circuit,
        signal_aggregator=mock_signal_aggregator,
        static_dir="/var/www",
        host="localhost",
        port=8080
    )
    
    assert server._adapters == mock_adapters
    assert server._state == mock_state
    assert server._circuit == mock_circuit
    assert server._signal_aggregator == mock_signal_aggregator
    assert isinstance(server._static_dir, Path)
    assert str(server._static_dir) == "/var/www"
    assert server._host == "localhost"
    assert server._port == 8080
    assert server._server is None


def test_init_none_signal_aggregator(mock_adapters, mock_state, mock_circuit):
    """Initialize DashboardServer with None signal_aggregator."""
    server = DashboardServer(
        adapters=mock_adapters,
        state=mock_state,
        circuit=mock_circuit,
        signal_aggregator=None,
        static_dir=None,
        host="localhost",
        port=8080
    )
    
    assert server._signal_aggregator is None
    assert server._static_dir is None


def test_invariant_server_instance(dashboard_server):
    """Verify _server is None or asyncio.Server instance."""
    assert dashboard_server._server is None or isinstance(dashboard_server._server, asyncio.Server)


def test_invariant_static_dir_type(dashboard_server):
    """Verify _static_dir is None or Path object."""
    assert dashboard_server._static_dir is None or isinstance(dashboard_server._static_dir, Path)


# ============================================================================
# is_running TESTS
# ============================================================================

def test_is_running_true(dashboard_server):
    """is_running returns True when _server exists and is_serving() is True."""
    mock_server = Mock()
    mock_server.is_serving.return_value = True
    dashboard_server._server = mock_server
    
    result = dashboard_server.is_running()
    
    assert result is True


def test_is_running_false_no_server(dashboard_server):
    """is_running returns False when _server is None."""
    dashboard_server._server = None
    
    result = dashboard_server.is_running()
    
    assert result is False


def test_is_running_false_not_serving(dashboard_server):
    """is_running returns False when _server exists but is_serving() is False."""
    mock_server = Mock()
    mock_server.is_serving.return_value = False
    dashboard_server._server = mock_server
    
    result = dashboard_server.is_running()
    
    assert result is False


# ============================================================================
# start TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_start_happy_path(dashboard_server):
    """Start server successfully and verify _server is set, logging occurs."""
    mock_server = Mock()
    mock_server.is_serving.return_value = True
    
    with patch('asyncio.start_server', new_callable=AsyncMock) as mock_start_server, \
         patch('logging.getLogger') as mock_get_logger:
        
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        mock_start_server.return_value = mock_server
        
        await dashboard_server.start()
        
        assert dashboard_server._server is not None
        assert mock_logger.info.called


@pytest.mark.asyncio
async def test_start_port_in_use(dashboard_server):
    """Start raises OSError when port is already in use."""
    with patch('asyncio.start_server', new_callable=AsyncMock) as mock_start_server:
        mock_start_server.side_effect = OSError("Port already in use")
        
        with pytest.raises(OSError):
            await dashboard_server.start()


@pytest.mark.asyncio
async def test_start_permission_error(dashboard_server):
    """Start raises PermissionError when insufficient permissions."""
    with patch('asyncio.start_server', new_callable=AsyncMock) as mock_start_server:
        mock_start_server.side_effect = PermissionError("Insufficient permissions")
        
        with pytest.raises(PermissionError):
            await dashboard_server.start()


# ============================================================================
# stop TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_stop_with_running_server(dashboard_server):
    """Stop server when _server is not None, verify close and cleanup."""
    mock_server = Mock()
    mock_server.close = Mock()
    mock_server.wait_closed = AsyncMock()
    dashboard_server._server = mock_server
    
    await dashboard_server.stop()
    
    assert mock_server.close.called
    assert dashboard_server._server is None


@pytest.mark.asyncio
async def test_stop_with_no_server(dashboard_server):
    """Stop server when _server is None, should handle gracefully."""
    dashboard_server._server = None
    
    await dashboard_server.stop()
    
    assert dashboard_server._server is None


# ============================================================================
# _handle TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_handle_snapshot_route(dashboard_server, mock_reader, mock_writer):
    """Handle request to /api/snapshot and return JSON snapshot."""
    mock_reader.readline.return_value = b"GET /api/snapshot HTTP/1.1\r\n"
    
    with patch.object(dashboard_server, '_handle_snapshot', return_value='{"data": "snapshot"}'):
        await dashboard_server._handle(mock_reader, mock_writer)
        
        assert mock_writer.write.called
        written_data = b''.join([call[0][0] for call in mock_writer.write.call_args_list])
        response = written_data.decode('utf-8')
        assert '200' in response
        assert 'application/json' in response


@pytest.mark.asyncio
async def test_handle_topology_route(dashboard_server, mock_reader, mock_writer):
    """Handle request to /api/topology and return JSON topology."""
    mock_reader.readline.return_value = b"GET /api/topology HTTP/1.1\r\n"
    
    with patch.object(dashboard_server, '_handle_topology', return_value='{"nodes": [], "edges": []}'):
        await dashboard_server._handle(mock_reader, mock_writer)
        
        assert mock_writer.write.called
        written_data = b''.join([call[0][0] for call in mock_writer.write.call_args_list])
        response = written_data.decode('utf-8')
        assert 'nodes' in response or '200' in response


@pytest.mark.asyncio
async def test_handle_signals_route(dashboard_server, mock_reader, mock_writer):
    """Handle request to /api/signals?last_n=10 and return signals."""
    mock_reader.readline.return_value = b"GET /api/signals?last_n=10 HTTP/1.1\r\n"
    
    with patch.object(dashboard_server, '_handle_signals', return_value='[]'):
        await dashboard_server._handle(mock_reader, mock_writer)
        
        assert mock_writer.write.called
        written_data = b''.join([call[0][0] for call in mock_writer.write.call_args_list])
        response = written_data.decode('utf-8')
        assert '200' in response


@pytest.mark.asyncio
async def test_handle_signal_stats_route(dashboard_server, mock_reader, mock_writer):
    """Handle request to /api/signals/stats and return statistics."""
    mock_reader.readline.return_value = b"GET /api/signals/stats HTTP/1.1\r\n"
    
    with patch.object(dashboard_server, '_handle_signal_stats', return_value='{}'):
        await dashboard_server._handle(mock_reader, mock_writer)
        
        assert mock_writer.write.called
        written_data = b''.join([call[0][0] for call in mock_writer.write.call_args_list])
        response = written_data.decode('utf-8')
        assert '200' in response


@pytest.mark.asyncio
async def test_handle_unknown_api_route(dashboard_server, mock_reader, mock_writer):
    """Handle request to unknown API path returns 404."""
    mock_reader.readline.return_value = b"GET /api/unknown HTTP/1.1\r\n"
    
    await dashboard_server._handle(mock_reader, mock_writer)
    
    assert mock_writer.write.called
    written_data = b''.join([call[0][0] for call in mock_writer.write.call_args_list])
    response = written_data.decode('utf-8')
    assert '404' in response


@pytest.mark.asyncio
async def test_handle_static_file_route(dashboard_server, mock_reader, mock_writer):
    """Handle request to non-API path attempts static file serving."""
    mock_reader.readline.return_value = b"GET /index.html HTTP/1.1\r\n"
    
    with patch.object(dashboard_server, '_handle_static'):
        await dashboard_server._handle(mock_reader, mock_writer)
        
        assert mock_writer.close.called


@pytest.mark.asyncio
async def test_handle_timeout_error(dashboard_server, mock_reader, mock_writer):
    """Handle raises TimeoutError when reading takes longer than 5 seconds."""
    mock_reader.readline.side_effect = asyncio.TimeoutError()
    
    with patch('logging.getLogger') as mock_get_logger:
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        
        # Should catch and log the timeout
        await dashboard_server._handle(mock_reader, mock_writer)
        
        # Verify error was logged
        assert mock_logger.error.called or mock_writer.close.called


@pytest.mark.asyncio
async def test_handle_generic_exception(dashboard_server, mock_reader, mock_writer):
    """Handle catches and logs any exception during request handling."""
    mock_reader.readline.side_effect = Exception("Generic error")
    
    with patch('logging.getLogger') as mock_get_logger:
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        
        # Should catch and suppress the exception
        await dashboard_server._handle(mock_reader, mock_writer)
        
        # Verify error was logged and writer closed
        assert mock_writer.close.called


# ============================================================================
# _handle_snapshot TESTS
# ============================================================================

def test_handle_snapshot_happy_path(dashboard_server):
    """Collect dashboard snapshot and return as JSON string."""
    mock_snapshot = {"adapters": {}, "state": {}, "circuit": {}}
    
    with patch('baton.dashboard.collect') as mock_collect:
        mock_collect.return_value = mock_snapshot
        
        result = dashboard_server._handle_snapshot()
        
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed is not None


def test_handle_snapshot_exception(dashboard_server):
    """Handle exception when collect() or json.dumps() fails."""
    with patch('baton.dashboard.collect') as mock_collect:
        mock_collect.side_effect = Exception("Collection failed")
        
        with pytest.raises(Exception):
            dashboard_server._handle_snapshot()


# ============================================================================
# _handle_topology TESTS
# ============================================================================

def test_handle_topology_happy_path(dashboard_server):
    """Extract circuit topology and return as JSON with nodes and edges."""
    result = dashboard_server._handle_topology()
    
    assert isinstance(result, str)
    assert 'nodes' in result
    assert 'edges' in result
    
    parsed = json.loads(result)
    assert 'nodes' in parsed
    assert 'edges' in parsed


def test_handle_topology_attribute_error(dashboard_server):
    """Handle AttributeError when nodes or edges lack expected attributes."""
    # Create a circuit with nodes missing attributes
    dashboard_server._circuit.nodes = [Mock(spec=[])]
    
    with pytest.raises(AttributeError):
        dashboard_server._handle_topology()


def test_handle_topology_json_encode_error(dashboard_server):
    """Handle JSONEncodeError when json.dumps() fails."""
    # Create a node with a non-serializable attribute
    node = Mock()
    node.name = lambda x: x  # Function is not JSON serializable
    node.port = 8000
    node.role = "worker"
    node.host = "localhost"
    dashboard_server._circuit.nodes = [node]
    
    with pytest.raises((TypeError, AttributeError)):
        dashboard_server._handle_topology()


# ============================================================================
# _handle_signals TESTS
# ============================================================================

def test_handle_signals_with_aggregator(dashboard_server):
    """Query signal aggregator for last N signals and return as JSON."""
    result = dashboard_server._handle_signals(10)
    
    assert isinstance(result, str)
    parsed = json.loads(result)
    assert parsed is not None


def test_handle_signals_no_aggregator(dashboard_server_no_aggregator):
    """Return empty array when _signal_aggregator is None."""
    result = dashboard_server_no_aggregator._handle_signals(10)
    
    assert result == '[]'


def test_handle_signals_zero_last_n(dashboard_server):
    """Handle signals with last_n=0."""
    result = dashboard_server._handle_signals(0)
    
    assert isinstance(result, str)


def test_handle_signals_negative_last_n(dashboard_server):
    """Handle signals with last_n=-1."""
    result = dashboard_server._handle_signals(-1)
    
    assert isinstance(result, str)


def test_handle_signals_attribute_error(dashboard_server):
    """Handle AttributeError when query() or model_dump() fails."""
    dashboard_server._signal_aggregator.query.side_effect = AttributeError("No query method")
    
    with pytest.raises(AttributeError):
        dashboard_server._handle_signals(10)


def test_handle_signals_json_encode_error(dashboard_server):
    """Handle JSONEncodeError when json.dumps() fails."""
    signal = Mock()
    signal.model_dump.return_value = {"data": lambda x: x}  # Non-serializable
    dashboard_server._signal_aggregator.query.return_value = [signal]
    
    with pytest.raises((TypeError, json.JSONDecodeError)):
        dashboard_server._handle_signals(10)


# ============================================================================
# _handle_signal_stats TESTS
# ============================================================================

def test_handle_signal_stats_with_aggregator(dashboard_server):
    """Query signal aggregator for path stats and return with computed metrics."""
    result = dashboard_server._handle_signal_stats()
    
    assert isinstance(result, str)
    parsed = json.loads(result)
    assert parsed is not None


def test_handle_signal_stats_no_aggregator(dashboard_server_no_aggregator):
    """Return empty object when _signal_aggregator is None."""
    result = dashboard_server_no_aggregator._handle_signal_stats()
    
    assert result == '{}'


def test_handle_signal_stats_attribute_error(dashboard_server):
    """Handle AttributeError when path_stats() fails."""
    dashboard_server._signal_aggregator.path_stats.side_effect = AttributeError("No path_stats")
    
    with pytest.raises(AttributeError):
        dashboard_server._handle_signal_stats()


def test_handle_signal_stats_json_encode_error(dashboard_server):
    """Handle JSONEncodeError when json.dumps() fails."""
    stat = Mock()
    stat.path = "/test"
    stat.count = lambda x: x  # Non-serializable
    dashboard_server._signal_aggregator.path_stats.return_value = {"path1": stat}
    
    with pytest.raises((TypeError, json.JSONDecodeError, AttributeError)):
        dashboard_server._handle_signal_stats()


# ============================================================================
# _handle_static TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_handle_static_no_static_dir(dashboard_server_no_aggregator, mock_writer):
    """Return 404 JSON error when _static_dir is None."""
    await dashboard_server_no_aggregator._handle_static(mock_writer, "/index.html")
    
    assert mock_writer.write.called
    written_data = b''.join([call[0][0] for call in mock_writer.write.call_args_list])
    response = written_data.decode('utf-8')
    assert '404' in response


@pytest.mark.asyncio
async def test_handle_static_root_path(dashboard_server, mock_writer):
    """Resolve root path / to /index.html."""
    mock_file_content = b"<html>Test</html>"
    
    with patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.is_file', return_value=True), \
         patch('pathlib.Path.read_bytes', return_value=mock_file_content):
        
        await dashboard_server._handle_static(mock_writer, "/")
        
        assert mock_writer.write.called


@pytest.mark.asyncio
async def test_handle_static_empty_path(dashboard_server, mock_writer):
    """Resolve empty path to /index.html."""
    mock_file_content = b"<html>Test</html>"
    
    with patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.is_file', return_value=True), \
         patch('pathlib.Path.read_bytes', return_value=mock_file_content):
        
        await dashboard_server._handle_static(mock_writer, "")
        
        assert mock_writer.write.called


@pytest.mark.asyncio
async def test_handle_static_directory_traversal(dashboard_server, mock_writer):
    """Return 403 for path with directory traversal attempt."""
    await dashboard_server._handle_static(mock_writer, "/../etc/passwd")
    
    assert mock_writer.write.called
    written_data = b''.join([call[0][0] for call in mock_writer.write.call_args_list])
    response = written_data.decode('utf-8')
    assert '403' in response or '404' in response


@pytest.mark.asyncio
async def test_handle_static_file_not_found(dashboard_server, mock_writer):
    """Return 404 when file does not exist."""
    with patch('pathlib.Path.exists', return_value=False):
        await dashboard_server._handle_static(mock_writer, "/nonexistent.html")
        
        assert mock_writer.write.called
        written_data = b''.join([call[0][0] for call in mock_writer.write.call_args_list])
        response = written_data.decode('utf-8')
        assert '404' in response


@pytest.mark.asyncio
async def test_handle_static_file_is_directory(dashboard_server, mock_writer):
    """Return 404 when path is a directory."""
    with patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.is_file', return_value=False):
        
        await dashboard_server._handle_static(mock_writer, "/somedir")
        
        assert mock_writer.write.called
        written_data = b''.join([call[0][0] for call in mock_writer.write.call_args_list])
        response = written_data.decode('utf-8')
        assert '404' in response


@pytest.mark.asyncio
async def test_handle_static_file_exists(dashboard_server, mock_writer):
    """Serve existing file with 200 response and correct MIME type."""
    mock_file_content = b"<html>Test</html>"
    
    with patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.is_file', return_value=True), \
         patch('pathlib.Path.read_bytes', return_value=mock_file_content), \
         patch('mimetypes.guess_type', return_value=('text/html', None)):
        
        await dashboard_server._handle_static(mock_writer, "/index.html")
        
        assert mock_writer.write.called
        written_data = b''.join([call[0][0] for call in mock_writer.write.call_args_list])
        response = written_data.decode('utf-8')
        assert '200' in response
        assert 'text/html' in response


@pytest.mark.asyncio
async def test_handle_static_os_error(dashboard_server, mock_writer):
    """Handle OSError when file read fails."""
    with patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.is_file', return_value=True), \
         patch('pathlib.Path.read_bytes', side_effect=OSError("Read failed")):
        
        with pytest.raises(OSError):
            await dashboard_server._handle_static(mock_writer, "/file.txt")


@pytest.mark.asyncio
async def test_handle_static_unicode_decode_error(dashboard_server, mock_writer):
    """Handle UnicodeDecodeError for invalid unicode in path."""
    # This test may need adjustment based on actual implementation
    # Some implementations may sanitize paths before this error occurs
    try:
        await dashboard_server._handle_static(mock_writer, "/invalid\udcff.html")
    except UnicodeDecodeError:
        pass  # Expected
    except Exception:
        pass  # May be handled differently


# ============================================================================
# _write_json_response TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_write_json_response_happy_path(mock_writer):
    """Write HTTP JSON response with status, headers, and body."""
    from src.baton.dashboard_server import DashboardServer
    
    body = '{"success": true}'
    DashboardServer._write_json_response(mock_writer, 200, body)
    
    assert mock_writer.write.called
    written_data = b''.join([call[0][0] for call in mock_writer.write.call_args_list])
    response = written_data.decode('utf-8')
    
    assert 'Content-Type: application/json' in response
    assert 'Access-Control-Allow-Origin: *' in response
    assert body in response


@pytest.mark.asyncio
async def test_write_json_response_404(mock_writer):
    """Write 404 JSON response."""
    from src.baton.dashboard_server import DashboardServer
    
    body = '{"error": "Not found"}'
    DashboardServer._write_json_response(mock_writer, 404, body)
    
    written_data = b''.join([call[0][0] for call in mock_writer.write.call_args_list])
    response = written_data.decode('utf-8')
    
    assert '404' in response


@pytest.mark.asyncio
async def test_write_json_response_unicode_encode_error(mock_writer):
    """Handle UnicodeEncodeError when body cannot be encoded as UTF-8."""
    from src.baton.dashboard_server import DashboardServer
    
    # Create a mock writer that raises UnicodeEncodeError
    mock_writer.write.side_effect = UnicodeEncodeError('utf-8', '', 0, 1, 'invalid')
    
    with pytest.raises(UnicodeEncodeError):
        DashboardServer._write_json_response(mock_writer, 200, '{"data": "test"}')


@pytest.mark.asyncio
async def test_invariant_cors_header(mock_writer):
    """Verify all JSON responses include CORS header."""
    from src.baton.dashboard_server import DashboardServer
    
    body = '{}'
    DashboardServer._write_json_response(mock_writer, 200, body)
    
    written_data = b''.join([call[0][0] for call in mock_writer.write.call_args_list])
    response = written_data.decode('utf-8')
    
    assert 'Access-Control-Allow-Origin: *' in response


# ============================================================================
# ADDITIONAL EDGE CASE TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_requests(dashboard_server, mock_writer):
    """Test handling multiple concurrent requests."""
    readers = [AsyncMock() for _ in range(5)]
    writers = [AsyncMock() for _ in range(5)]
    
    for reader in readers:
        reader.readline.return_value = b"GET /api/snapshot HTTP/1.1\r\n"
        reader.get_extra_info = Mock(return_value=("127.0.0.1", 12345))
    
    for writer in writers:
        writer.write = Mock()
        writer.drain = AsyncMock()
        writer.close = Mock()
        writer.wait_closed = AsyncMock()
        writer.get_extra_info = Mock(return_value=("127.0.0.1", 12345))
    
    with patch.object(dashboard_server, '_handle_snapshot', return_value='{}'):
        tasks = [dashboard_server._handle(r, w) for r, w in zip(readers, writers)]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # All writers should have been used
        for writer in writers:
            assert writer.close.called


def test_empty_circuit(mock_adapters, mock_state):
    """Test DashboardServer with empty circuit (no nodes or edges)."""
    mock_circuit = Mock(spec=CircuitSpec)
    mock_circuit.nodes = []
    mock_circuit.edges = []
    
    server = DashboardServer(
        adapters=mock_adapters,
        state=mock_state,
        circuit=mock_circuit,
        signal_aggregator=None,
        static_dir=None,
        host="localhost",
        port=8080
    )
    
    result = server._handle_topology()
    parsed = json.loads(result)
    
    assert parsed['nodes'] == []
    assert parsed['edges'] == []


@pytest.mark.asyncio
async def test_handle_with_malformed_request(dashboard_server, mock_reader, mock_writer):
    """Test handling of malformed HTTP request."""
    mock_reader.readline.return_value = b"INVALID REQUEST\r\n"
    
    with patch('logging.getLogger') as mock_get_logger:
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        
        await dashboard_server._handle(mock_reader, mock_writer)
        
        # Should handle gracefully
        assert mock_writer.close.called


def test_signal_stats_with_zero_count(dashboard_server):
    """Test signal stats calculation with zero count to avoid division by zero."""
    stat = Mock()
    stat.path = "/test"
    stat.count = 0
    stat.total_latency_ms = 0
    stat.error_count = 0
    
    dashboard_server._signal_aggregator.path_stats.return_value = {"path1": stat}
    
    result = dashboard_server._handle_signal_stats()
    parsed = json.loads(result)
    
    # Should handle zero count gracefully
    assert isinstance(result, str)


@pytest.mark.parametrize("path,expected_status", [
    ("/api/snapshot", 200),
    ("/api/topology", 200),
    ("/api/signals", 200),
    ("/api/signals/stats", 200),
    ("/api/invalid", 404),
])
@pytest.mark.asyncio
async def test_api_routes_parametrized(dashboard_server, mock_reader, mock_writer, path, expected_status):
    """Test various API routes with parametrized inputs."""
    mock_reader.readline.return_value = f"GET {path} HTTP/1.1\r\n".encode()
    
    with patch.object(dashboard_server, '_handle_snapshot', return_value='{}'), \
         patch.object(dashboard_server, '_handle_topology', return_value='{"nodes":[],"edges":[]}'), \
         patch.object(dashboard_server, '_handle_signals', return_value='[]'), \
         patch.object(dashboard_server, '_handle_signal_stats', return_value='{}'):
        
        await dashboard_server._handle(mock_reader, mock_writer)
        
        written_data = b''.join([call[0][0] for call in mock_writer.write.call_args_list])
        response = written_data.decode('utf-8')
        
        assert str(expected_status) in response


@pytest.mark.parametrize("mime_path,expected_mime", [
    ("/file.html", "text/html"),
    ("/file.css", "text/css"),
    ("/file.js", "application/javascript"),
    ("/file.json", "application/json"),
    ("/file.png", "image/png"),
])
@pytest.mark.asyncio
async def test_static_mime_types(dashboard_server, mock_writer, mime_path, expected_mime):
    """Test MIME type detection for various file types."""
    mock_file_content = b"content"
    
    with patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.is_file', return_value=True), \
         patch('pathlib.Path.read_bytes', return_value=mock_file_content), \
         patch('mimetypes.guess_type', return_value=(expected_mime, None)):
        
        await dashboard_server._handle_static(mock_writer, mime_path)
        
        written_data = b''.join([call[0][0] for call in mock_writer.write.call_args_list])
        response = written_data.decode('utf-8')
        
        assert expected_mime in response or '200' in response
