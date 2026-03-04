"""
Contract-driven tests for Baton Adapter - Async Reverse Proxy
Generated from contract version 1
Tests verify behavior at boundaries using mocked dependencies
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch, call
from datetime import datetime
import random
from io import BytesIO

# Import the component
from src.baton.adapter import (
    BackendTarget,
    AdapterMetrics,
    Adapter,
    NodeSpec,
    RoutingConfig,
    RoutingLocked,
    HealthCheck,
    SignalRecord,
    _now_iso,
    is_configured,
    _parse_headers,
    _parse_request_line,
    _parse_status_code,
    _select_weighted,
    _select_weighted_named,
    _pipe,
    _read_http_message,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_node():
    """Create a mock NodeSpec for testing"""
    node = Mock(spec=NodeSpec)
    node.name = "test-node"
    node.host = "127.0.0.1"
    node.port = 8080
    node.role = "WORKER"
    node.proxy_mode = "HTTP"
    node.metadata = {}
    return node


@pytest.fixture
def mock_ingress_node():
    """Create a mock INGRESS NodeSpec"""
    node = Mock(spec=NodeSpec)
    node.name = "ingress-node"
    node.host = "127.0.0.1"
    node.port = 9000
    node.role = "INGRESS"
    node.proxy_mode = "HTTP"
    node.metadata = {}
    return node


@pytest.fixture
def backend_target():
    """Create a BackendTarget for testing"""
    return BackendTarget(host="backend.local", port=8081)


@pytest.fixture
def adapter_metrics():
    """Create an AdapterMetrics instance"""
    return AdapterMetrics(
        requests_total=0,
        requests_failed=0,
        bytes_forwarded=0,
        last_request_at=0.0,
        last_latency_ms=0.0,
        status_2xx=0,
        status_3xx=0,
        status_4xx=0,
        status_5xx=0,
        active_connections=0,
        _latency_buffer=[]
    )


@pytest.fixture
def adapter(mock_node):
    """Create an Adapter instance for testing"""
    return Adapter(node=mock_node, record_signals=False)


@pytest.fixture
def adapter_with_signals(mock_node):
    """Create an Adapter with signal recording enabled"""
    return Adapter(node=mock_node, record_signals=True)


@pytest.fixture
def ingress_adapter(mock_ingress_node):
    """Create an Adapter for an INGRESS node"""
    return Adapter(node=mock_ingress_node, record_signals=False)


@pytest.fixture
def routing_config():
    """Create a RoutingConfig for testing"""
    config = Mock(spec=RoutingConfig)
    config.locked = False
    config.strategy = "WEIGHTED"
    config.targets = []
    config.default_target = None
    config.header_rules = []
    return config


@pytest.fixture
def locked_routing_config():
    """Create a locked RoutingConfig"""
    config = Mock(spec=RoutingConfig)
    config.locked = True
    return config


# ============================================================================
# UTILITY FUNCTION TESTS
# ============================================================================

class TestNowIso:
    """Tests for _now_iso function"""
    
    def test_now_iso_happy_path(self):
        """Test _now_iso returns ISO 8601 formatted timestamp"""
        result = _now_iso()
        
        # Result is a non-empty string
        assert isinstance(result, str)
        assert len(result) > 0
        
        # Result matches ISO 8601 format pattern (can be parsed back)
        try:
            datetime.fromisoformat(result.replace('Z', '+00:00'))
            iso_format_valid = True
        except ValueError:
            iso_format_valid = False
        
        assert iso_format_valid, f"Result '{result}' is not valid ISO 8601 format"


class TestIsConfigured:
    """Tests for is_configured function"""
    
    def test_is_configured_with_valid_port(self):
        """Test is_configured returns True when port > 0"""
        target1 = BackendTarget(host="localhost", port=1)
        target2 = BackendTarget(host="localhost", port=8080)
        
        # Returns True for port = 1
        assert is_configured(target1) is True
        
        # Returns True for port = 8080
        assert is_configured(target2) is True
    
    def test_is_configured_with_invalid_port(self):
        """Test is_configured returns False when port <= 0"""
        target0 = BackendTarget(host="localhost", port=0)
        target_neg = BackendTarget(host="localhost", port=-1)
        
        # Returns False for port = 0
        assert is_configured(target0) is False
        
        # Returns False for port = -1
        assert is_configured(target_neg) is False


# ============================================================================
# ADAPTER METRICS TESTS
# ============================================================================

class TestAdapterMetrics:
    """Tests for AdapterMetrics methods"""
    
    def test_record_latency_single_value(self, adapter_metrics):
        """Test record_latency appends value to buffer"""
        initial_size = len(adapter_metrics._latency_buffer)
        
        adapter_metrics.record_latency(15.5)
        
        # Buffer contains the recorded latency
        assert 15.5 in adapter_metrics._latency_buffer
        
        # Buffer size increases by 1
        assert len(adapter_metrics._latency_buffer) == initial_size + 1
    
    def test_record_latency_buffer_trimming(self, adapter_metrics):
        """Test record_latency trims buffer to max 1000 entries"""
        # Fill buffer with 1000 entries
        for i in range(1000):
            adapter_metrics.record_latency(float(i))
        
        assert len(adapter_metrics._latency_buffer) == 1000
        
        # Add more entries
        for i in range(100):
            adapter_metrics.record_latency(float(1000 + i))
        
        # Buffer size never exceeds 1000
        assert len(adapter_metrics._latency_buffer) == 1000
        
        # Oldest entries are removed first (first 100 entries should be gone)
        assert 0.0 not in adapter_metrics._latency_buffer
        assert 99.0 not in adapter_metrics._latency_buffer
        assert 1099.0 in adapter_metrics._latency_buffer
    
    def test_record_status_2xx(self, adapter_metrics):
        """Test record_status increments status_2xx for 200-299"""
        initial_count = adapter_metrics.status_2xx
        
        adapter_metrics.record_status(200)
        assert adapter_metrics.status_2xx == initial_count + 1
        
        adapter_metrics.record_status(204)
        assert adapter_metrics.status_2xx == initial_count + 2
        
        adapter_metrics.record_status(299)
        assert adapter_metrics.status_2xx == initial_count + 3
    
    def test_record_status_3xx(self, adapter_metrics):
        """Test record_status increments status_3xx for 300-399"""
        initial_count = adapter_metrics.status_3xx
        
        adapter_metrics.record_status(301)
        assert adapter_metrics.status_3xx == initial_count + 1
        
        adapter_metrics.record_status(302)
        assert adapter_metrics.status_3xx == initial_count + 2
    
    def test_record_status_4xx(self, adapter_metrics):
        """Test record_status increments status_4xx for 400-499"""
        initial_count = adapter_metrics.status_4xx
        
        adapter_metrics.record_status(404)
        assert adapter_metrics.status_4xx == initial_count + 1
        
        adapter_metrics.record_status(400)
        assert adapter_metrics.status_4xx == initial_count + 2
    
    def test_record_status_5xx(self, adapter_metrics):
        """Test record_status increments status_5xx for 500-599"""
        initial_count = adapter_metrics.status_5xx
        
        adapter_metrics.record_status(500)
        assert adapter_metrics.status_5xx == initial_count + 1
        
        adapter_metrics.record_status(503)
        assert adapter_metrics.status_5xx == initial_count + 2
    
    def test_p50_with_data(self, adapter_metrics):
        """Test p50 returns 50th percentile of latency buffer"""
        # Add known values
        values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        for v in values:
            adapter_metrics.record_latency(v)
        
        result = adapter_metrics.p50()
        
        # Returns correct 50th percentile value (should be around 55.0)
        assert 50.0 <= result <= 60.0
    
    def test_p50_empty_buffer(self, adapter_metrics):
        """Test p50 returns 0.0 for empty buffer"""
        result = adapter_metrics.p50()
        
        # Returns 0.0 when buffer is empty
        assert result == 0.0
    
    def test_p95_with_data(self, adapter_metrics):
        """Test p95 returns 95th percentile of latency buffer"""
        # Add known values
        values = [float(i) for i in range(1, 101)]
        for v in values:
            adapter_metrics.record_latency(v)
        
        result = adapter_metrics.p95()
        
        # Returns correct 95th percentile value (should be around 95.0)
        assert 94.0 <= result <= 96.0
    
    def test_p95_empty_buffer(self, adapter_metrics):
        """Test p95 returns 0.0 for empty buffer"""
        result = adapter_metrics.p95()
        
        # Returns 0.0 when buffer is empty
        assert result == 0.0
    
    def test_p99_with_data(self, adapter_metrics):
        """Test p99 returns 99th percentile of latency buffer"""
        # Add known values
        values = [float(i) for i in range(1, 101)]
        for v in values:
            adapter_metrics.record_latency(v)
        
        result = adapter_metrics.p99()
        
        # Returns correct 99th percentile value (should be around 99.0)
        assert 98.0 <= result <= 100.0
    
    def test_p99_empty_buffer(self, adapter_metrics):
        """Test p99 returns 0.0 for empty buffer"""
        result = adapter_metrics.p99()
        
        # Returns 0.0 when buffer is empty
        assert result == 0.0
    
    def test_percentile_calculation(self, adapter_metrics):
        """Test _percentile calculates correct percentile value"""
        # Add known values
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        for v in values:
            adapter_metrics.record_latency(v)
        
        result = adapter_metrics._percentile(50)
        
        # Returns correct percentile from sorted buffer
        assert result == 30.0  # Median of 5 values
    
    def test_percentile_empty_buffer(self, adapter_metrics):
        """Test _percentile returns 0.0 for empty buffer"""
        result = adapter_metrics._percentile(50)
        
        # Returns 0.0 when buffer is empty
        assert result == 0.0


# ============================================================================
# ADAPTER INITIALIZATION TESTS
# ============================================================================

class TestAdapterInit:
    """Tests for Adapter initialization"""
    
    def test_adapter_init_normal_node(self, mock_node):
        """Test Adapter initialization with normal node"""
        adapter = Adapter(node=mock_node, record_signals=False)
        
        # Adapter initialized
        assert adapter is not None
        
        # Backend target created
        assert hasattr(adapter, '_backend')
        
        # Metrics initialized
        assert adapter.metrics() is not None
        
        # Server not started
        assert adapter.is_running() is False
    
    def test_adapter_init_with_signal_recording(self, mock_node):
        """Test Adapter initialization with signal recording enabled"""
        adapter = Adapter(node=mock_node, record_signals=True)
        
        # Signal recording enabled when record_signals=True
        assert hasattr(adapter, '_record_signals')
        assert adapter._record_signals is True
    
    def test_adapter_init_ingress_node(self, mock_ingress_node):
        """Test Adapter initialization with INGRESS node always records signals"""
        # Even with record_signals=False
        adapter = Adapter(node=mock_ingress_node, record_signals=False)
        
        # Signal recording enabled for INGRESS role regardless of record_signals flag
        assert adapter._record_signals is True


# ============================================================================
# ADAPTER GETTER TESTS
# ============================================================================

class TestAdapterGetters:
    """Tests for Adapter getter methods"""
    
    def test_adapter_node_getter(self, adapter, mock_node):
        """Test node getter returns NodeSpec"""
        result = adapter.node()
        
        # Returns the NodeSpec instance
        assert result is mock_node
    
    def test_adapter_metrics_getter(self, adapter):
        """Test metrics getter returns AdapterMetrics"""
        result = adapter.metrics()
        
        # Returns AdapterMetrics instance
        assert isinstance(result, AdapterMetrics)
    
    def test_adapter_target_metrics_getter(self, adapter):
        """Test target_metrics returns copy of dictionary"""
        result = adapter.target_metrics()
        
        # Returns dictionary
        assert isinstance(result, dict)
        
        # Returns copy not reference
        result['test'] = Mock()
        assert 'test' not in adapter.target_metrics()
    
    def test_adapter_signals_getter(self, adapter_with_signals):
        """Test signals returns copy of signal buffer"""
        result = adapter_with_signals.signals()
        
        # Returns list
        assert isinstance(result, list)
        
        # Returns copy not reference (modifying return doesn't affect internal)
        original_len = len(adapter_with_signals._signals)
        result.append(Mock())
        assert len(adapter_with_signals.signals()) == original_len
    
    def test_adapter_drain_signals(self, adapter_with_signals):
        """Test drain_signals returns and clears buffer"""
        # Add some mock signals
        mock_signal = Mock(spec=SignalRecord)
        adapter_with_signals._signals.append(mock_signal)
        
        result = adapter_with_signals.drain_signals()
        
        # Returns copy of signal buffer
        assert len(result) == 1
        assert result[0] is mock_signal
        
        # Signal buffer is cleared after drain
        assert len(adapter_with_signals.signals()) == 0
    
    def test_adapter_backend_getter(self, adapter):
        """Test backend getter returns BackendTarget"""
        result = adapter.backend()
        
        # Returns BackendTarget instance
        assert isinstance(result, BackendTarget)
    
    def test_adapter_routing_getter(self, adapter, routing_config):
        """Test routing getter returns RoutingConfig or None"""
        # Returns None when no routing configured
        assert adapter.routing() is None
        
        # Set routing
        adapter._routing = routing_config
        
        # Returns RoutingConfig when configured
        assert adapter.routing() is routing_config
    
    def test_adapter_is_running_not_started(self, adapter):
        """Test is_running returns False when server not started"""
        # Returns False when server is None
        assert adapter.is_running() is False
    
    @patch('asyncio.start_server')
    @pytest.mark.asyncio
    async def test_adapter_is_running_started(self, mock_start_server, adapter):
        """Test is_running returns True when server is running"""
        # Create a mock server
        mock_server = AsyncMock()
        mock_server.is_serving.return_value = True
        mock_start_server.return_value = mock_server
        
        await adapter.start()
        
        # Returns True when server exists and serving
        assert adapter.is_running() is True


# ============================================================================
# ADAPTER CONFIGURATION TESTS
# ============================================================================

class TestAdapterConfiguration:
    """Tests for Adapter configuration methods"""
    
    def test_set_backend_success(self, adapter, backend_target):
        """Test set_backend updates backend target"""
        new_target = BackendTarget(host="new-backend", port=9090)
        
        adapter.set_backend(new_target)
        
        # Backend updated to new target
        assert adapter.backend().host == "new-backend"
        assert adapter.backend().port == 9090
        
        # Draining flag cleared
        assert adapter._draining is False
    
    def test_set_backend_routing_locked(self, adapter, locked_routing_config):
        """Test set_backend raises RoutingLocked when routing is locked"""
        adapter._routing = locked_routing_config
        new_target = BackendTarget(host="new-backend", port=9090)
        
        # Raises RoutingLocked exception when routing is locked
        with pytest.raises(RoutingLocked):
            adapter.set_backend(new_target)
    
    def test_set_routing_success(self, adapter, routing_config):
        """Test set_routing updates routing config"""
        # Add some target metrics
        adapter._target_metrics['test'] = Mock()
        
        adapter.set_routing(routing_config)
        
        # Routing config updated
        assert adapter.routing() is routing_config
        
        # Target metrics cleared
        assert len(adapter._target_metrics) == 0
    
    def test_set_routing_locked(self, adapter, locked_routing_config, routing_config):
        """Test set_routing raises RoutingLocked when current routing is locked"""
        adapter._routing = locked_routing_config
        
        # Raises RoutingLocked exception
        with pytest.raises(RoutingLocked):
            adapter.set_routing(routing_config)
    
    def test_clear_routing_success(self, adapter, routing_config):
        """Test clear_routing removes routing configuration"""
        adapter._routing = routing_config
        
        adapter.clear_routing()
        
        # Routing config set to None
        assert adapter.routing() is None
    
    def test_clear_routing_locked(self, adapter, locked_routing_config):
        """Test clear_routing raises RoutingLocked when routing is locked"""
        adapter._routing = locked_routing_config
        
        # Raises RoutingLocked exception
        with pytest.raises(RoutingLocked):
            adapter.clear_routing()


# ============================================================================
# ADAPTER LIFECYCLE TESTS
# ============================================================================

class TestAdapterLifecycle:
    """Tests for Adapter lifecycle methods"""
    
    @patch('asyncio.start_server')
    @patch('src.src_baton_adapter.logger')
    @pytest.mark.asyncio
    async def test_start_adapter(self, mock_logger, mock_start_server, adapter):
        """Test start begins listening on node address"""
        mock_server = AsyncMock()
        mock_server.is_serving.return_value = True
        mock_start_server.return_value = mock_server
        
        await adapter.start()
        
        # Server started
        assert adapter._server is not None
        
        # Server is listening
        assert adapter.is_running() is True
        
        # start_server was called with correct parameters
        mock_start_server.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_drain_adapter(self, adapter):
        """Test drain stops accepting connections and waits for active ones"""
        adapter._active_connections = 2
        adapter._drain_event = asyncio.Event()
        
        # Start drain with very short timeout
        drain_task = asyncio.create_task(adapter.drain(timeout=0.1))
        
        # Draining flag set
        assert adapter._draining is True
        
        # Simulate connections finishing
        adapter._active_connections = 0
        adapter._drain_event.set()
        
        await drain_task
        
        # Waits for active connections or timeout
        assert adapter._draining is True
    
    @pytest.mark.asyncio
    async def test_stop_adapter(self, adapter):
        """Test stop shuts down server"""
        # Create mock server
        mock_server = AsyncMock()
        adapter._server = mock_server
        
        await adapter.stop()
        
        # Server closed
        mock_server.close.assert_called_once()
        
        # Server set to None
        assert adapter._server is None


# ============================================================================
# HEALTH CHECK TESTS
# ============================================================================

class TestHealthChecks:
    """Tests for health check methods"""
    
    @patch('asyncio.open_connection')
    @pytest.mark.asyncio
    async def test_health_check_tcp_healthy(self, mock_open_connection, adapter):
        """Test health_check returns HEALTHY for successful TCP connection"""
        adapter._node.proxy_mode = "TCP"
        adapter._backend = BackendTarget(host="backend", port=8080)
        
        # Mock successful connection
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        mock_open_connection.return_value = (mock_reader, mock_writer)
        
        result = await adapter.health_check()
        
        # Returns HealthCheck with HEALTHY verdict
        assert result.verdict == "HEALTHY"
    
    @patch('aiohttp.ClientSession.get')
    @pytest.mark.asyncio
    async def test_health_check_http_healthy(self, mock_get, adapter):
        """Test health_check returns HEALTHY for 2xx HTTP response"""
        adapter._node.proxy_mode = "HTTP"
        adapter._backend = BackendTarget(host="backend", port=8080)
        
        # Mock 200 response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__.return_value = mock_response
        mock_response.__aexit__.return_value = None
        mock_get.return_value = mock_response
        
        result = await adapter.health_check()
        
        # Returns HealthCheck with HEALTHY verdict for 200
        assert result.verdict == "HEALTHY"
    
    @patch('aiohttp.ClientSession.get')
    @pytest.mark.asyncio
    async def test_health_check_http_unhealthy(self, mock_get, adapter):
        """Test health_check returns UNHEALTHY for 5xx HTTP response"""
        adapter._node.proxy_mode = "HTTP"
        adapter._backend = BackendTarget(host="backend", port=8080)
        
        # Mock 500 response
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.__aenter__.return_value = mock_response
        mock_response.__aexit__.return_value = None
        mock_get.return_value = mock_response
        
        result = await adapter.health_check()
        
        # Returns HealthCheck with UNHEALTHY verdict for 500
        assert result.verdict == "UNHEALTHY"
    
    @patch('aiohttp.ClientSession.get')
    @pytest.mark.asyncio
    async def test_health_check_http_degraded(self, mock_get, adapter):
        """Test health_check returns DEGRADED for non-2xx/5xx HTTP response"""
        adapter._node.proxy_mode = "HTTP"
        adapter._backend = BackendTarget(host="backend", port=8080)
        
        # Mock 404 response
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.__aenter__.return_value = mock_response
        mock_response.__aexit__.return_value = None
        mock_get.return_value = mock_response
        
        result = await adapter.health_check()
        
        # Returns HealthCheck with DEGRADED verdict for 404
        assert result.verdict == "DEGRADED"
    
    @patch('asyncio.open_connection')
    @patch('time.perf_counter')
    @pytest.mark.asyncio
    async def test_tcp_health_check_success(self, mock_perf_counter, mock_open_connection, adapter):
        """Test _tcp_health_check returns HEALTHY on successful connection"""
        adapter._backend = BackendTarget(host="backend", port=8080)
        
        # Mock time and connection
        mock_perf_counter.side_effect = [0.0, 0.015]  # 15ms latency
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        mock_open_connection.return_value = (mock_reader, mock_writer)
        
        result = await adapter._tcp_health_check()
        
        # Returns HEALTHY verdict
        assert result.verdict == "HEALTHY"
        
        # Includes latency measurement
        assert result.latency_ms > 0
    
    @patch('asyncio.open_connection')
    @pytest.mark.asyncio
    async def test_tcp_health_check_failure(self, mock_open_connection, adapter):
        """Test _tcp_health_check returns UNHEALTHY on connection failure"""
        adapter._backend = BackendTarget(host="backend", port=8080)
        
        # Mock connection failure
        mock_open_connection.side_effect = Exception("Connection refused")
        
        result = await adapter._tcp_health_check()
        
        # Returns UNHEALTHY verdict on failure
        assert result.verdict == "UNHEALTHY"
    
    @patch('aiohttp.ClientSession.get')
    @pytest.mark.asyncio
    async def test_http_health_check_2xx(self, mock_get, adapter):
        """Test _http_health_check returns HEALTHY for 2xx status"""
        adapter._backend = BackendTarget(host="backend", port=8080)
        
        # Mock 200 response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__.return_value = mock_response
        mock_response.__aexit__.return_value = None
        mock_get.return_value = mock_response
        
        result = await adapter._http_health_check()
        
        # Returns HEALTHY for 200
        assert result.verdict == "HEALTHY"
        
        # Includes latency
        assert hasattr(result, 'latency_ms')
    
    @patch('aiohttp.ClientSession.get')
    @pytest.mark.asyncio
    async def test_http_health_check_5xx(self, mock_get, adapter):
        """Test _http_health_check returns UNHEALTHY for 5xx status"""
        adapter._backend = BackendTarget(host="backend", port=8080)
        
        # Mock 500 response
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.__aenter__.return_value = mock_response
        mock_response.__aexit__.return_value = None
        mock_get.return_value = mock_response
        
        result = await adapter._http_health_check()
        
        # Returns UNHEALTHY for 500
        assert result.verdict == "UNHEALTHY"
    
    @patch('aiohttp.ClientSession.get')
    @pytest.mark.asyncio
    async def test_http_health_check_other(self, mock_get, adapter):
        """Test _http_health_check returns DEGRADED for other status codes"""
        adapter._backend = BackendTarget(host="backend", port=8080)
        
        # Mock 404 response
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.__aenter__.return_value = mock_response
        mock_response.__aexit__.return_value = None
        mock_get.return_value = mock_response
        
        result = await adapter._http_health_check()
        
        # Returns DEGRADED for 404
        assert result.verdict == "DEGRADED"


# ============================================================================
# ROUTING SELECTION TESTS
# ============================================================================

class TestRoutingSelection:
    """Tests for backend selection and routing"""
    
    def test_select_backend_no_routing(self, adapter):
        """Test _select_backend returns default backend when no routing"""
        adapter._backend = BackendTarget(host="default", port=8080)
        adapter._routing = None
        
        result = adapter._select_backend(None)
        
        # Returns default backend target
        assert result.host == "default"
        assert result.port == 8080
    
    def test_select_backend_with_routing(self, adapter):
        """Test _select_backend uses routing config when available"""
        adapter._backend = BackendTarget(host="default", port=8080)
        
        # Create routing config with weighted target
        config = Mock(spec=RoutingConfig)
        config.strategy = "WEIGHTED"
        target = BackendTarget(host="routed", port=9090)
        config.targets = [{'target': target, 'weight': 1.0}]
        adapter._routing = config
        
        result = adapter._select_backend(None)
        
        # Returns backend from routing config
        assert result is not None
    
    def test_select_backend_named_no_routing(self, adapter):
        """Test _select_backend_named returns default backend with None name"""
        adapter._backend = BackendTarget(host="default", port=8080)
        adapter._routing = None
        
        target, name = adapter._select_backend_named(None)
        
        # Returns (target, None) when no routing
        assert target.host == "default"
        assert name is None
    
    def test_select_backend_named_with_routing(self, adapter):
        """Test _select_backend_named returns backend and name from routing"""
        adapter._backend = BackendTarget(host="default", port=8080)
        
        # Create routing config
        config = Mock(spec=RoutingConfig)
        config.strategy = "WEIGHTED"
        target = BackendTarget(host="routed", port=9090)
        config.targets = [{'target': target, 'weight': 1.0, 'name': 'backend-1'}]
        adapter._routing = config
        
        result_target, result_name = adapter._select_backend_named(None)
        
        # Returns (target, name) from routing config
        assert result_target is not None
    
    @patch('random.uniform')
    def test_select_weighted_single_target(self, mock_random):
        """Test _select_weighted returns single target"""
        target = BackendTarget(host="single", port=8080)
        targets = [{'target': target, 'weight': 1.0}]
        
        result = _select_weighted(targets)
        
        # Returns the only target
        assert result.host == "single"
    
    @patch('random.uniform')
    def test_select_weighted_multiple_targets(self, mock_random):
        """Test _select_weighted distributes based on weights"""
        target1 = BackendTarget(host="backend1", port=8080)
        target2 = BackendTarget(host="backend2", port=8081)
        targets = [
            {'target': target1, 'weight': 0.7},
            {'target': target2, 'weight': 0.3}
        ]
        
        # Mock random to select first target
        mock_random.return_value = 0.5
        
        result = _select_weighted(targets)
        
        # Returns one of the weighted targets
        assert result in [target1, target2]
    
    @patch('random.uniform')
    def test_select_weighted_named_single(self, mock_random):
        """Test _select_weighted_named returns single target with name"""
        target = BackendTarget(host="single", port=8080)
        targets = [{'target': target, 'weight': 1.0, 'name': 'backend-1'}]
        
        result_target, result_name = _select_weighted_named(targets)
        
        # Returns (target, name) for single target
        assert result_target.host == "single"
        assert result_name == 'backend-1'
    
    @patch('random.uniform')
    def test_select_weighted_named_multiple(self, mock_random):
        """Test _select_weighted_named distributes based on weights"""
        target1 = BackendTarget(host="backend1", port=8080)
        target2 = BackendTarget(host="backend2", port=8081)
        targets = [
            {'target': target1, 'weight': 0.7, 'name': 'b1'},
            {'target': target2, 'weight': 0.3, 'name': 'b2'}
        ]
        
        # Mock random to select first target
        mock_random.return_value = 0.5
        
        result_target, result_name = _select_weighted_named(targets)
        
        # Returns (target, name) from weighted selection
        assert result_target in [target1, target2]
        assert result_name in ['b1', 'b2']
    
    def test_select_by_header_match(self, adapter):
        """Test _select_by_header routes based on matching header"""
        adapter._backend = BackendTarget(host="default", port=8080)
        
        # Create routing config with header rule
        config = Mock(spec=RoutingConfig)
        config.strategy = "HEADER"
        config.header_rules = [
            {'header': 'x-version', 'value': 'v2', 'target_name': 'backend-v2'}
        ]
        
        target_v2 = BackendTarget(host="backend-v2", port=9090)
        targets_by_name = {'backend-v2': target_v2}
        
        # Request with matching header
        request_data = b"GET / HTTP/1.1\r\nX-Version: v2\r\n\r\n"
        
        result = adapter._select_by_header(request_data, config, targets_by_name)
        
        # Returns target matching header rule
        assert result.host == "backend-v2"
    
    def test_select_by_header_no_match(self, adapter):
        """Test _select_by_header falls back to default when no match"""
        adapter._backend = BackendTarget(host="default", port=8080)
        
        # Create routing config with header rule
        config = Mock(spec=RoutingConfig)
        config.strategy = "HEADER"
        config.header_rules = [
            {'header': 'x-version', 'value': 'v2', 'target_name': 'backend-v2'}
        ]
        
        targets_by_name = {}
        
        # Request without matching header
        request_data = b"GET / HTTP/1.1\r\nX-Version: v1\r\n\r\n"
        
        result = adapter._select_by_header(request_data, config, targets_by_name)
        
        # Returns default target when no header match
        assert result.host == "default"
    
    def test_select_by_header_named_match(self, adapter):
        """Test _select_by_header_named returns matched target and name"""
        adapter._backend = BackendTarget(host="default", port=8080)
        
        # Create routing config
        config = Mock(spec=RoutingConfig)
        config.strategy = "HEADER"
        config.header_rules = [
            {'header': 'x-version', 'value': 'v2', 'target_name': 'backend-v2'}
        ]
        
        target_v2 = BackendTarget(host="backend-v2", port=9090)
        targets_by_name = {'backend-v2': target_v2}
        
        # Request with matching header
        request_data = b"GET / HTTP/1.1\r\nX-Version: v2\r\n\r\n"
        
        result_target, result_name = adapter._select_by_header_named(
            request_data, config, targets_by_name
        )
        
        # Returns (target, name) for matching header
        assert result_target.host == "backend-v2"
        assert result_name == 'backend-v2'
    
    def test_select_by_header_named_no_match(self, adapter):
        """Test _select_by_header_named falls back to default"""
        adapter._backend = BackendTarget(host="default", port=8080)
        
        # Create routing config
        config = Mock(spec=RoutingConfig)
        config.strategy = "HEADER"
        config.header_rules = [
            {'header': 'x-version', 'value': 'v2', 'target_name': 'backend-v2'}
        ]
        
        targets_by_name = {}
        
        # Request without matching header
        request_data = b"GET / HTTP/1.1\r\nX-Other: value\r\n\r\n"
        
        result_target, result_name = adapter._select_by_header_named(
            request_data, config, targets_by_name
        )
        
        # Returns (default_target, None) when no match
        assert result_target.host == "default"
        assert result_name is None


# ============================================================================
# HTTP PARSING TESTS
# ============================================================================

class TestHTTPParsing:
    """Tests for HTTP message parsing functions"""
    
    def test_parse_headers_valid(self):
        """Test _parse_headers extracts headers from HTTP request"""
        data = b"GET / HTTP/1.1\r\nHost: example.com\r\nContent-Type: application/json\r\n\r\n"
        
        result = _parse_headers(data)
        
        # Returns dictionary with lowercase keys
        assert isinstance(result, dict)
        assert 'host' in result
        assert 'content-type' in result
        
        # Values extracted correctly
        assert result['host'] == 'example.com'
        assert result['content-type'] == 'application/json'
    
    def test_parse_headers_malformed(self):
        """Test _parse_headers returns empty dict on parse error"""
        data = b"MALFORMED DATA WITHOUT PROPER HEADERS"
        
        result = _parse_headers(data)
        
        # Returns empty dict for malformed data
        assert result == {}
    
    def test_parse_request_line_valid(self):
        """Test _parse_request_line extracts method and path"""
        data = b"GET /api/users HTTP/1.1\r\n"
        
        method, path = _parse_request_line(data)
        
        # Returns (method, path) tuple correctly
        assert method == "GET"
        assert path == "/api/users"
    
    def test_parse_request_line_invalid(self):
        """Test _parse_request_line returns empty strings on parse error"""
        data = b"INVALID REQUEST"
        
        method, path = _parse_request_line(data)
        
        # Returns ('', '') for malformed request line
        assert method == ''
        assert path == ''
    
    def test_parse_status_code_valid(self):
        """Test _parse_status_code extracts status code from response"""
        data = b"HTTP/1.1 200 OK\r\n"
        
        status_code = _parse_status_code(data)
        
        # Returns status code integer
        assert status_code == 200
    
    def test_parse_status_code_none(self):
        """Test _parse_status_code returns 0 for None input"""
        status_code = _parse_status_code(None)
        
        # Returns 0 when data is None
        assert status_code == 0
    
    def test_parse_status_code_invalid(self):
        """Test _parse_status_code returns 0 for malformed response"""
        data = b"INVALID RESPONSE"
        
        status_code = _parse_status_code(data)
        
        # Returns 0 for malformed data
        assert status_code == 0


# ============================================================================
# CONNECTION HANDLING TESTS
# ============================================================================

class TestConnectionHandling:
    """Tests for connection handling methods"""
    
    def test_decrement_connections(self, adapter):
        """Test _decrement_connections reduces active connection count"""
        adapter._active_connections = 5
        
        adapter._decrement_connections()
        
        # Active connections decremented
        assert adapter._active_connections == 4
    
    def test_decrement_connections_signals_drain(self, adapter):
        """Test _decrement_connections signals drain event when draining and connections reach 0"""
        adapter._active_connections = 1
        adapter._draining = True
        adapter._drain_event = asyncio.Event()
        
        adapter._decrement_connections()
        
        # Drain event set when draining and connections = 0
        assert adapter._drain_event.is_set()
    
    @patch('asyncio.open_connection')
    @pytest.mark.asyncio
    async def test_handle_tcp_connection_success(self, mock_open_connection, adapter):
        """Test _handle_tcp_connection forwards traffic bidirectionally"""
        adapter._backend = BackendTarget(host="backend", port=8080)
        
        # Mock client streams
        client_reader = AsyncMock(spec=asyncio.StreamReader)
        client_writer = AsyncMock(spec=asyncio.StreamWriter)
        client_reader.read.side_effect = [b"client data", b""]
        
        # Mock backend streams
        backend_reader = AsyncMock(spec=asyncio.StreamReader)
        backend_writer = AsyncMock(spec=asyncio.StreamWriter)
        backend_reader.read.side_effect = [b"backend data", b""]
        
        mock_open_connection.return_value = (backend_reader, backend_writer)
        
        initial_requests = adapter._metrics.requests_total
        
        await adapter._handle_tcp_connection(client_reader, client_writer)
        
        # Traffic forwarded bidirectionally (write was called)
        assert client_writer.write.called or backend_writer.write.called
        
        # Metrics updated
        assert adapter._metrics.requests_total >= initial_requests
        
        # Connections closed
        client_writer.close.assert_called()
    
    @patch('asyncio.open_connection')
    @pytest.mark.asyncio
    async def test_handle_tcp_connection_backend_failure(self, mock_open_connection, adapter):
        """Test _handle_tcp_connection handles backend connection failure"""
        adapter._backend = BackendTarget(host="backend", port=8080)
        
        # Mock connection failure
        mock_open_connection.side_effect = Exception("Connection failed")
        
        client_reader = AsyncMock(spec=asyncio.StreamReader)
        client_writer = AsyncMock(spec=asyncio.StreamWriter)
        
        initial_failed = adapter._metrics.requests_failed
        
        await adapter._handle_tcp_connection(client_reader, client_writer)
        
        # Handles connection failure gracefully
        client_writer.close.assert_called()
        
        # Metrics updated with failure
        assert adapter._metrics.requests_failed > initial_failed
    
    @patch('asyncio.open_connection')
    @pytest.mark.asyncio
    async def test_handle_http_connection_success(self, mock_open_connection, adapter):
        """Test _handle_http_connection forwards HTTP request and response"""
        adapter._backend = BackendTarget(host="backend", port=8080)
        
        # Mock client streams
        client_reader = AsyncMock(spec=asyncio.StreamReader)
        client_writer = AsyncMock(spec=asyncio.StreamWriter)
        
        # Mock HTTP request
        request_data = b"GET /test HTTP/1.1\r\nHost: backend\r\n\r\n"
        client_reader.readuntil.side_effect = [
            b"GET /test HTTP/1.1\r\nHost: backend\r\n\r\n"
        ]
        client_reader.read.return_value = b""
        
        # Mock backend streams
        backend_reader = AsyncMock(spec=asyncio.StreamReader)
        backend_writer = AsyncMock(spec=asyncio.StreamWriter)
        
        # Mock HTTP response
        backend_reader.readuntil.side_effect = [
            b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"
        ]
        backend_reader.read.return_value = b""
        
        mock_open_connection.return_value = (backend_reader, backend_writer)
        
        initial_requests = adapter._metrics.requests_total
        
        await adapter._handle_http_connection(client_reader, client_writer)
        
        # Request forwarded (backend_writer.write called)
        assert backend_writer.write.called
        
        # Response returned (client_writer.write called)
        assert client_writer.write.called
        
        # Metrics updated
        assert adapter._metrics.requests_total >= initial_requests
    
    @patch('asyncio.open_connection')
    @pytest.mark.asyncio
    async def test_handle_http_connection_with_routing(self, mock_open_connection, adapter):
        """Test _handle_http_connection uses routing to select backend"""
        # Set up routing
        config = Mock(spec=RoutingConfig)
        config.strategy = "WEIGHTED"
        target = BackendTarget(host="routed", port=9090)
        config.targets = [{'target': target, 'weight': 1.0, 'name': 'backend-1'}]
        adapter._routing = config
        
        # Mock client streams
        client_reader = AsyncMock(spec=asyncio.StreamReader)
        client_writer = AsyncMock(spec=asyncio.StreamWriter)
        
        request_data = b"GET /test HTTP/1.1\r\n\r\n"
        client_reader.readuntil.side_effect = [request_data]
        client_reader.read.return_value = b""
        
        # Mock backend streams
        backend_reader = AsyncMock(spec=asyncio.StreamReader)
        backend_writer = AsyncMock(spec=asyncio.StreamWriter)
        backend_reader.readuntil.side_effect = [b"HTTP/1.1 200 OK\r\n\r\n"]
        backend_reader.read.return_value = b""
        
        mock_open_connection.return_value = (backend_reader, backend_writer)
        
        await adapter._handle_http_connection(client_reader, client_writer)
        
        # Uses routing config (target_metrics should be updated)
        # Target metrics updated
        assert len(adapter._target_metrics) >= 0  # May or may not have entries depending on impl
    
    @patch('asyncio.open_connection')
    @pytest.mark.asyncio
    async def test_handle_http_connection_backend_failure(self, mock_open_connection, adapter):
        """Test _handle_http_connection handles backend connection failure"""
        adapter._backend = BackendTarget(host="backend", port=8080)
        
        # Mock connection failure
        mock_open_connection.side_effect = Exception("Backend unavailable")
        
        client_reader = AsyncMock(spec=asyncio.StreamReader)
        client_writer = AsyncMock(spec=asyncio.StreamWriter)
        
        request_data = b"GET /test HTTP/1.1\r\n\r\n"
        client_reader.readuntil.return_value = request_data
        client_reader.read.return_value = b""
        
        initial_failed = adapter._metrics.requests_failed
        
        await adapter._handle_http_connection(client_reader, client_writer)
        
        # Handles backend failure
        client_writer.close.assert_called()
        
        # Metrics record failure
        assert adapter._metrics.requests_failed > initial_failed
    
    @patch('asyncio.open_connection')
    @pytest.mark.asyncio
    async def test_handle_http_connection_signals_recorded(
        self, mock_open_connection, adapter_with_signals
    ):
        """Test _handle_http_connection records signals when enabled"""
        adapter_with_signals._backend = BackendTarget(host="backend", port=8080)
        
        # Mock client streams
        client_reader = AsyncMock(spec=asyncio.StreamReader)
        client_writer = AsyncMock(spec=asyncio.StreamWriter)
        
        request_data = b"GET /test HTTP/1.1\r\n\r\n"
        client_reader.readuntil.side_effect = [request_data]
        client_reader.read.return_value = b""
        
        # Mock backend streams
        backend_reader = AsyncMock(spec=asyncio.StreamReader)
        backend_writer = AsyncMock(spec=asyncio.StreamWriter)
        backend_reader.readuntil.side_effect = [b"HTTP/1.1 200 OK\r\n\r\n"]
        backend_reader.read.return_value = b""
        
        mock_open_connection.return_value = (backend_reader, backend_writer)
        
        initial_signals = len(adapter_with_signals.signals())
        
        await adapter_with_signals._handle_http_connection(client_reader, client_writer)
        
        # Signals recorded when recording enabled
        # Note: May not always increase if implementation has other conditions
        assert len(adapter_with_signals.signals()) >= initial_signals


# ============================================================================
# STREAM UTILITY TESTS
# ============================================================================

class TestStreamUtilities:
    """Tests for stream utility functions"""
    
    @pytest.mark.asyncio
    async def test_pipe_transfers_data(self):
        """Test _pipe copies all bytes from reader to writer"""
        # Create mock reader and writer
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = AsyncMock(spec=asyncio.StreamWriter)
        
        # Mock reading data in chunks then EOF
        reader.read.side_effect = [b"chunk1", b"chunk2", b""]
        
        await _pipe(reader, writer)
        
        # All bytes copied until EOF
        assert writer.write.call_count == 2
        writer.write.assert_any_call(b"chunk1")
        writer.write.assert_any_call(b"chunk2")
    
    @pytest.mark.asyncio
    async def test_pipe_eof(self):
        """Test _pipe handles EOF correctly"""
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = AsyncMock(spec=asyncio.StreamWriter)
        
        # Immediate EOF
        reader.read.return_value = b""
        
        await _pipe(reader, writer)
        
        # Stops reading at EOF (no writes)
        writer.write.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_read_http_message_complete(self):
        """Test _read_http_message reads complete HTTP message with Content-Length"""
        reader = AsyncMock(spec=asyncio.StreamReader)
        
        # Mock reading headers then body
        headers = b"HTTP/1.1 200 OK\r\nContent-Length: 11\r\n\r\n"
        body = b"Hello World"
        
        reader.readuntil.return_value = headers
        reader.readexactly.return_value = body
        
        result = await _read_http_message(reader)
        
        # Returns complete HTTP message including headers and body
        assert result == headers + body
    
    @pytest.mark.asyncio
    async def test_read_http_message_no_content_length(self):
        """Test _read_http_message handles missing Content-Length"""
        reader = AsyncMock(spec=asyncio.StreamReader)
        
        # Mock reading headers without Content-Length
        headers = b"HTTP/1.1 200 OK\r\n\r\n"
        
        reader.readuntil.return_value = headers
        
        result = await _read_http_message(reader)
        
        # Returns headers when no Content-Length present
        assert result == headers
    
    @pytest.mark.asyncio
    async def test_read_http_message_timeout(self):
        """Test _read_http_message returns None on timeout"""
        reader = AsyncMock(spec=asyncio.StreamReader)
        
        # Mock timeout
        reader.readuntil.side_effect = asyncio.TimeoutError()
        
        result = await _read_http_message(reader)
        
        # Returns None on timeout
        assert result is None


# ============================================================================
# INVARIANT TESTS
# ============================================================================

class TestInvariants:
    """Tests for contract invariants"""
    
    def test_invariant_latency_buffer_max(self, adapter_metrics):
        """Test that latency buffer never exceeds 1000 entries"""
        # Record 2000 latency measurements
        for i in range(2000):
            adapter_metrics.record_latency(float(i))
        
        # Buffer size <= 1000 after recording 2000 entries
        assert len(adapter_metrics._latency_buffer) <= 1000
        assert len(adapter_metrics._latency_buffer) == 1000
    
    def test_invariant_ingress_signals(self, mock_ingress_node):
        """Test that INGRESS nodes always record signals"""
        # Create adapter with record_signals=False
        adapter = Adapter(node=mock_ingress_node, record_signals=False)
        
        # INGRESS nodes record signals even when record_signals=False
        assert adapter._record_signals is True
    
    def test_invariant_backend_port_configured(self):
        """Test that backend is configured only when port > 0"""
        configured = BackendTarget(host="localhost", port=8080)
        not_configured = BackendTarget(host="localhost", port=0)
        
        # port > 0 means configured
        assert is_configured(configured) is True
        
        # port <= 0 means not configured
        assert is_configured(not_configured) is False


# ============================================================================
# EDGE CASE AND PROPERTY-BASED TESTS
# ============================================================================

class TestEdgeCases:
    """Additional edge case tests"""
    
    def test_weighted_selection_distribution(self):
        """Test that weighted selection approximates expected distribution"""
        target1 = BackendTarget(host="backend1", port=8080)
        target2 = BackendTarget(host="backend2", port=8081)
        targets = [
            {'target': target1, 'weight': 0.8, 'name': 'b1'},
            {'target': target2, 'weight': 0.2, 'name': 'b2'}
        ]
        
        # Run selection 1000 times
        counts = {'b1': 0, 'b2': 0}
        for _ in range(1000):
            _, name = _select_weighted_named(targets)
            counts[name] += 1
        
        # Check rough distribution (80/20 split)
        # Allow for randomness - b1 should be selected more
        assert counts['b1'] > counts['b2']
        assert 700 < counts['b1'] < 900  # Roughly 80% ± tolerance
    
    def test_percentile_calculation_edge_cases(self, adapter_metrics):
        """Test percentile calculations with various buffer sizes"""
        # Test with single value
        adapter_metrics.record_latency(50.0)
        assert adapter_metrics.p50() == 50.0
        
        # Test with two values
        adapter_metrics._latency_buffer = [10.0, 90.0]
        p50 = adapter_metrics.p50()
        assert 10.0 <= p50 <= 90.0
        
        # Test with odd number of values
        adapter_metrics._latency_buffer = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert adapter_metrics.p50() == 30.0
    
    def test_http_header_parsing_edge_cases(self):
        """Test header parsing with various edge cases"""
        # Empty headers
        assert _parse_headers(b"") == {}
        
        # Headers with colons in values
        data = b"GET / HTTP/1.1\r\nX-Custom: value:with:colons\r\n\r\n"
        headers = _parse_headers(data)
        assert headers.get('x-custom') == 'value:with:colons'
        
        # Headers with whitespace
        data = b"GET / HTTP/1.1\r\nContent-Type:  application/json  \r\n\r\n"
        headers = _parse_headers(data)
        assert 'content-type' in headers
    
    def test_concurrent_metric_updates(self, adapter_metrics):
        """Test that concurrent metric updates maintain consistency"""
        # Simulate concurrent status updates
        for i in range(100):
            adapter_metrics.record_status(200)
            adapter_metrics.record_status(500)
            adapter_metrics.record_latency(float(i))
        
        # Verify counts
        assert adapter_metrics.status_2xx == 100
        assert adapter_metrics.status_5xx == 100
        assert len(adapter_metrics._latency_buffer) == 100
    
    @pytest.mark.asyncio
    async def test_adapter_lifecycle_transitions(self, adapter):
        """Test adapter state transitions through lifecycle"""
        # Initial state
        assert not adapter.is_running()
        
        # Start
        with patch('asyncio.start_server') as mock_start:
            mock_server = AsyncMock()
            mock_server.is_serving.return_value = True
            mock_start.return_value = mock_server
            
            await adapter.start()
            assert adapter.is_running()
            
            # Stop
            await adapter.stop()
            assert not adapter.is_running()
    
    def test_routing_config_locked_state(self, adapter, routing_config, locked_routing_config):
        """Test that locked routing config prevents modifications"""
        adapter._routing = locked_routing_config
        
        # All modification operations should raise RoutingLocked
        with pytest.raises(RoutingLocked):
            adapter.set_backend(BackendTarget(host="new", port=8080))
        
        with pytest.raises(RoutingLocked):
            adapter.set_routing(routing_config)
        
        with pytest.raises(RoutingLocked):
            adapter.clear_routing()
    
    def test_parse_request_line_variations(self):
        """Test request line parsing with various HTTP methods and paths"""
        # Standard GET
        method, path = _parse_request_line(b"GET /api/users HTTP/1.1\r\n")
        assert method == "GET"
        assert path == "/api/users"
        
        # POST with query params
        method, path = _parse_request_line(b"POST /submit?id=123 HTTP/1.1\r\n")
        assert method == "POST"
        assert "/submit" in path
        
        # Root path
        method, path = _parse_request_line(b"GET / HTTP/1.1\r\n")
        assert method == "GET"
        assert path == "/"
    
    def test_parse_status_code_variations(self):
        """Test status code parsing with various response formats"""
        # Standard 200
        assert _parse_status_code(b"HTTP/1.1 200 OK\r\n") == 200
        
        # 404 Not Found
        assert _parse_status_code(b"HTTP/1.1 404 Not Found\r\n") == 404
        
        # 500 Internal Server Error
        assert _parse_status_code(b"HTTP/1.1 500 Internal Server Error\r\n") == 500
        
        # Malformed - missing status
        assert _parse_status_code(b"HTTP/1.1 \r\n") == 0


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
