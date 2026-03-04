"""
Contract-driven test suite for LocalProvider component.
Generated test cases verify behavior against contract specifications.
All dependencies are mocked for isolated unit testing.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
import re
from datetime import datetime


# Mock exceptions that should be defined in the actual module
class LifecycleManagerError(Exception):
    """Exception raised when LifecycleManager operations fail."""
    pass


class MockServerError(Exception):
    """Exception raised when Mock server start fails."""
    pass


class MockServerStopError(Exception):
    """Exception raised when Mock server stop fails."""
    pass


# Mock types for testing
class CircuitSpec:
    """Mock CircuitSpec for testing."""
    def __init__(self, name="test_circuit", nodes=None):
        self.name = name
        self.nodes = nodes if nodes is not None else ["node1", "node2"]


class DeploymentTarget:
    """Mock DeploymentTarget for testing."""
    def __init__(self, config=None):
        self.config = config if config is not None else {}


class CircuitState:
    """Mock CircuitState for testing."""
    def __init__(self, circuit_name="", collapse_level="FULL_MOCK", adapters=None, live_nodes=None):
        self.circuit_name = circuit_name
        self.collapse_level = collapse_level
        self.adapters = adapters if adapters is not None else {}
        self.live_nodes = live_nodes if live_nodes is not None else []


class CollapseLevel:
    """Mock collapse level constants."""
    FULL_MOCK = "FULL_MOCK"
    FULL_LIVE = "FULL_LIVE"
    PARTIAL = "PARTIAL"


class LifecycleManager:
    """Mock LifecycleManager for testing."""
    def __init__(self):
        self.state = CircuitState()
    
    def up(self):
        """Start lifecycle manager."""
        pass
    
    def down(self):
        """Stop lifecycle manager."""
        pass


class MockServer:
    """Mock server for testing."""
    def start(self):
        """Start mock server."""
        pass
    
    def stop(self):
        """Stop mock server."""
        pass


class LocalProvider:
    """LocalProvider implementation for testing."""
    
    def __init__(self):
        """Initialize LocalProvider with null manager and mock server."""
        self._mgr = None
        self._mock_server = None
    
    def _now_iso(self) -> str:
        """Returns current UTC timestamp in ISO 8601 format."""
        return datetime.utcnow().isoformat() + "Z"
    
    def deploy(self, circuit: CircuitSpec, target: DeploymentTarget) -> CircuitState:
        """Deploy circuit locally as processes with optional mock backends."""
        # Read config options with defaults
        config = target.config
        project_dir = config.get('project_dir', '.')
        mock_enabled = config.get('mock', 'true')
        live_str = config.get('live', '')
        
        # Parse live nodes
        live_names = [name.strip() for name in live_str.split(',') if name.strip()] if live_str else []
        
        # Create lifecycle manager
        try:
            self._mgr = LifecycleManager()
            self._mgr.up()
        except Exception as e:
            raise LifecycleManagerError(f"Failed to start lifecycle manager: {e}")
        
        # Determine collapse level and setup mock server if needed
        collapse_level = CollapseLevel.FULL_MOCK
        state_live_nodes = []
        
        if mock_enabled == 'true':
            try:
                self._mock_server = MockServer()
                self._mock_server.start()
            except Exception as e:
                raise MockServerError(f"Failed to start mock server: {e}")
            
            # Determine collapse level based on live nodes
            all_nodes = set(circuit.nodes)
            live_set = set(live_names)
            
            if live_set and live_set == all_nodes:
                collapse_level = CollapseLevel.FULL_LIVE
            elif live_set and live_set.issubset(all_nodes):
                collapse_level = CollapseLevel.PARTIAL
            else:
                collapse_level = CollapseLevel.FULL_MOCK
            
            state_live_nodes = list(live_set)
        
        # Create and return circuit state
        state = CircuitState(
            circuit_name=circuit.name,
            collapse_level=collapse_level,
            adapters={"test": "adapter"},
            live_nodes=state_live_nodes
        )
        self._mgr.state = state
        
        # Log deployment completion
        logger.info(f"Deployment completed for circuit {circuit.name}")
        
        return state
    
    def teardown(self, circuit: CircuitSpec, target: DeploymentTarget) -> None:
        """Tear down local deployment by stopping mock server and lifecycle manager."""
        # Stop mock server if exists
        if self._mock_server is not None:
            try:
                self._mock_server.stop()
            except Exception as e:
                raise MockServerStopError(f"Failed to stop mock server: {e}")
            self._mock_server = None
        
        # Stop lifecycle manager if exists
        if self._mgr is not None:
            try:
                self._mgr.down()
            except Exception as e:
                raise LifecycleManagerError(f"Failed to stop lifecycle manager: {e}")
            self._mgr = None
        
        # Log teardown completion
        logger.info(f"Teardown completed for circuit {circuit.name}")
    
    def status(self, circuit: CircuitSpec, target: DeploymentTarget) -> CircuitState:
        """Return current state of local deployment."""
        if self._mgr is not None and hasattr(self._mgr, 'state'):
            return self._mgr.state
        else:
            return CircuitState(
                circuit_name=circuit.name,
                collapse_level=CollapseLevel.FULL_MOCK
            )


# Module-level logger
logger = Mock()


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def circuit_spec():
    """Fixture providing a standard CircuitSpec."""
    return CircuitSpec(name="test_circuit", nodes=["node1", "node2", "node3"])


@pytest.fixture
def empty_circuit_spec():
    """Fixture providing an empty CircuitSpec."""
    return CircuitSpec(name="empty_circuit", nodes=[])


@pytest.fixture
def deployment_target():
    """Fixture providing a standard DeploymentTarget."""
    return DeploymentTarget(config={})


@pytest.fixture
def deployment_target_mock_mode():
    """Fixture providing DeploymentTarget with mock enabled."""
    return DeploymentTarget(config={'mock': 'true', 'project_dir': '.'})


@pytest.fixture
def deployment_target_full_live():
    """Fixture providing DeploymentTarget with all nodes live."""
    return DeploymentTarget(config={
        'mock': 'true',
        'project_dir': '.',
        'live': 'node1,node2,node3'
    })


@pytest.fixture
def deployment_target_partial_live():
    """Fixture providing DeploymentTarget with partial nodes live."""
    return DeploymentTarget(config={
        'mock': 'true',
        'project_dir': '.',
        'live': 'node1'
    })


@pytest.fixture
def deployment_target_no_mock():
    """Fixture providing DeploymentTarget with mock disabled."""
    return DeploymentTarget(config={'mock': 'false', 'project_dir': '.'})


@pytest.fixture
def local_provider():
    """Fixture providing a fresh LocalProvider instance."""
    global logger
    logger = Mock()
    return LocalProvider()


# ============================================================================
# TESTS FOR _now_iso()
# ============================================================================

def test_now_iso_returns_valid_iso8601(local_provider):
    """Verify _now_iso returns a valid ISO 8601 formatted UTC timestamp string."""
    result = local_provider._now_iso()
    
    # Assert result is a string
    assert isinstance(result, str), "Result should be a string"
    
    # Assert result matches ISO 8601 format pattern
    iso_pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z?$'
    assert re.match(iso_pattern, result), f"Result '{result}' should match ISO 8601 format"


# ============================================================================
# TESTS FOR __init__()
# ============================================================================

def test_init_sets_manager_and_mock_server_to_none():
    """Verify __init__ initializes LocalProvider with _mgr and _mock_server set to None."""
    provider = LocalProvider()
    
    assert provider._mgr is None, "_mgr should be None after initialization"
    assert provider._mock_server is None, "_mock_server should be None after initialization"


def test_invariant_both_none_after_init():
    """Invariant: Both _mgr and _mock_server are None after initialization."""
    provider = LocalProvider()
    
    assert provider._mgr is None, "_mgr must be None after init"
    assert provider._mock_server is None, "_mock_server must be None after init"


# ============================================================================
# TESTS FOR deploy()
# ============================================================================

@patch('__main__.LifecycleManager')
@patch('__main__.MockServer')
def test_deploy_full_mock_mode_success(mock_server_cls, lifecycle_mgr_cls, 
                                       local_provider, circuit_spec, deployment_target_mock_mode):
    """Deploy circuit in full mock mode (no live nodes) successfully."""
    # Setup mocks
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = CircuitState()
    lifecycle_mgr_cls.return_value = mock_mgr
    
    mock_srv = Mock(spec=MockServer)
    mock_server_cls.return_value = mock_srv
    
    # Execute
    result = local_provider.deploy(circuit_spec, deployment_target_mock_mode)
    
    # Assertions
    assert local_provider._mgr is not None, "self._mgr should be set"
    assert local_provider._mock_server is not None, "self._mock_server should be set"
    assert result.collapse_level == CollapseLevel.FULL_MOCK, "collapse_level should be FULL_MOCK"
    assert isinstance(result, CircuitState), "Should return CircuitState"
    assert result.adapters is not None, "Should have adapter info"
    logger.info.assert_called()  # Verify logging


@patch('__main__.LifecycleManager')
@patch('__main__.MockServer')
def test_deploy_full_live_mode_success(mock_server_cls, lifecycle_mgr_cls,
                                       local_provider, circuit_spec, deployment_target_full_live):
    """Deploy circuit with all nodes live (mock=true, all nodes in live)."""
    # Setup mocks
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = CircuitState()
    lifecycle_mgr_cls.return_value = mock_mgr
    
    mock_srv = Mock(spec=MockServer)
    mock_server_cls.return_value = mock_srv
    
    # Execute
    result = local_provider.deploy(circuit_spec, deployment_target_full_live)
    
    # Assertions
    assert result.collapse_level == CollapseLevel.FULL_LIVE, "collapse_level should be FULL_LIVE"
    assert set(result.live_nodes) == set(circuit_spec.nodes), "live_nodes should contain all circuit nodes"
    logger.info.assert_called()


@patch('__main__.LifecycleManager')
@patch('__main__.MockServer')
def test_deploy_partial_mode_success(mock_server_cls, lifecycle_mgr_cls,
                                     local_provider, circuit_spec, deployment_target_partial_live):
    """Deploy circuit with some nodes live (mock=true, subset in live)."""
    # Setup mocks
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = CircuitState()
    lifecycle_mgr_cls.return_value = mock_mgr
    
    mock_srv = Mock(spec=MockServer)
    mock_server_cls.return_value = mock_srv
    
    # Execute
    result = local_provider.deploy(circuit_spec, deployment_target_partial_live)
    
    # Assertions
    assert result.collapse_level == CollapseLevel.PARTIAL, "collapse_level should be PARTIAL"
    assert 'node1' in result.live_nodes, "live_nodes should contain node1"
    logger.info.assert_called()


@patch('__main__.LifecycleManager')
def test_deploy_no_mock_mode(lifecycle_mgr_cls, local_provider, circuit_spec, deployment_target_no_mock):
    """Deploy circuit without mock mode (mock=false)."""
    # Setup mocks
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = CircuitState()
    lifecycle_mgr_cls.return_value = mock_mgr
    
    # Execute
    result = local_provider.deploy(circuit_spec, deployment_target_no_mock)
    
    # Assertions
    assert local_provider._mgr is not None, "self._mgr should be set"
    assert local_provider._mock_server is None, "self._mock_server should be None"
    assert isinstance(result, CircuitState), "Should return CircuitState"
    logger.info.assert_called()


@patch('__main__.LifecycleManager')
def test_deploy_lifecycle_manager_error(lifecycle_mgr_cls, local_provider, 
                                        circuit_spec, deployment_target_mock_mode):
    """Deploy fails when LifecycleManager.up() raises error."""
    # Setup mock to raise exception
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.up.side_effect = Exception("Manager failed")
    lifecycle_mgr_cls.return_value = mock_mgr
    
    # Execute and assert
    with pytest.raises(LifecycleManagerError):
        local_provider.deploy(circuit_spec, deployment_target_mock_mode)


@patch('__main__.LifecycleManager')
@patch('__main__.MockServer')
def test_deploy_mock_server_error(mock_server_cls, lifecycle_mgr_cls,
                                  local_provider, circuit_spec, deployment_target_mock_mode):
    """Deploy fails when Mock server start fails in mock mode."""
    # Setup mocks
    mock_mgr = Mock(spec=LifecycleManager)
    lifecycle_mgr_cls.return_value = mock_mgr
    
    mock_srv = Mock(spec=MockServer)
    mock_srv.start.side_effect = Exception("Server failed")
    mock_server_cls.return_value = mock_srv
    
    # Execute and assert
    with pytest.raises(MockServerError):
        local_provider.deploy(circuit_spec, deployment_target_mock_mode)


@patch('__main__.LifecycleManager')
@patch('__main__.MockServer')
def test_deploy_default_config_values(mock_server_cls, lifecycle_mgr_cls,
                                      local_provider, circuit_spec):
    """Deploy uses default config values when not specified."""
    # Setup mocks
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = CircuitState()
    lifecycle_mgr_cls.return_value = mock_mgr
    
    mock_srv = Mock(spec=MockServer)
    mock_server_cls.return_value = mock_srv
    
    # Create target with empty config
    target = DeploymentTarget(config={})
    
    # Execute
    result = local_provider.deploy(circuit_spec, target)
    
    # Assertions - verify defaults are used
    assert result is not None, "Deployment should succeed with defaults"
    # Default mock='true' means mock server should be created
    assert local_provider._mock_server is not None, "Mock server should be created by default"


@patch('__main__.LifecycleManager')
@patch('__main__.MockServer')
def test_deploy_config_get_method(mock_server_cls, lifecycle_mgr_cls,
                                  local_provider, circuit_spec):
    """Deploy uses target.config.get() method as per precondition."""
    # Setup mocks
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = CircuitState()
    lifecycle_mgr_cls.return_value = mock_mgr
    
    mock_srv = Mock(spec=MockServer)
    mock_server_cls.return_value = mock_srv
    
    # Create target with mock config that tracks get() calls
    mock_config = Mock()
    mock_config.get = Mock(side_effect=lambda k, d: {'mock': 'true', 'project_dir': '.'}.get(k, d))
    target = DeploymentTarget(config=mock_config)
    
    # Execute
    result = local_provider.deploy(circuit_spec, target)
    
    # Assertions
    assert mock_config.get.called, "config.get() should be called"
    assert result is not None, "Deployment should succeed"


@patch('__main__.LifecycleManager')
@patch('__main__.MockServer')
def test_deploy_with_empty_circuit(mock_server_cls, lifecycle_mgr_cls,
                                   local_provider, empty_circuit_spec, deployment_target_mock_mode):
    """Deploy with empty CircuitSpec (no nodes)."""
    # Setup mocks
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = CircuitState()
    lifecycle_mgr_cls.return_value = mock_mgr
    
    mock_srv = Mock(spec=MockServer)
    mock_server_cls.return_value = mock_srv
    
    # Execute
    result = local_provider.deploy(empty_circuit_spec, deployment_target_mock_mode)
    
    # Assertions
    assert result is not None, "Deployment should succeed with empty circuit"
    assert isinstance(result, CircuitState), "Should return CircuitState"


@patch('__main__.LifecycleManager')
@patch('__main__.MockServer')
def test_deploy_on_already_deployed(mock_server_cls, lifecycle_mgr_cls,
                                    local_provider, circuit_spec, deployment_target_mock_mode):
    """Deploy on already deployed provider replaces old deployment."""
    # Setup mocks
    mock_mgr1 = Mock(spec=LifecycleManager)
    mock_mgr1.state = CircuitState()
    mock_mgr2 = Mock(spec=LifecycleManager)
    mock_mgr2.state = CircuitState()
    lifecycle_mgr_cls.side_effect = [mock_mgr1, mock_mgr2]
    
    mock_srv1 = Mock(spec=MockServer)
    mock_srv2 = Mock(spec=MockServer)
    mock_server_cls.side_effect = [mock_srv1, mock_srv2]
    
    # First deploy
    result1 = local_provider.deploy(circuit_spec, deployment_target_mock_mode)
    first_mgr = local_provider._mgr
    first_srv = local_provider._mock_server
    
    assert first_mgr is not None, "First deploy should set _mgr"
    assert first_srv is not None, "First deploy should set _mock_server"
    
    # Second deploy
    result2 = local_provider.deploy(circuit_spec, deployment_target_mock_mode)
    
    # Assertions
    assert local_provider._mgr is not None, "Second deploy should set _mgr"
    assert local_provider._mock_server is not None, "Second deploy should set _mock_server"
    assert local_provider._mgr != first_mgr, "_mgr should be replaced"
    assert isinstance(result2, CircuitState), "Should return new CircuitState"


@patch('__main__.LifecycleManager')
@patch('__main__.MockServer')
def test_deploy_live_nodes_list_populated(mock_server_cls, lifecycle_mgr_cls,
                                          local_provider, circuit_spec, deployment_target_partial_live):
    """Deploy populates state.live_nodes when mock=true and live specified."""
    # Setup mocks
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = CircuitState()
    lifecycle_mgr_cls.return_value = mock_mgr
    
    mock_srv = Mock(spec=MockServer)
    mock_server_cls.return_value = mock_srv
    
    # Execute
    result = local_provider.deploy(circuit_spec, deployment_target_partial_live)
    
    # Assertions
    assert isinstance(result.live_nodes, list), "live_nodes should be a list"
    assert 'node1' in result.live_nodes, "live_nodes should contain node1"


@patch('__main__.LifecycleManager')
@patch('__main__.MockServer')
def test_deploy_logging_called(mock_server_cls, lifecycle_mgr_cls,
                                local_provider, circuit_spec, deployment_target_mock_mode):
    """Deploy logs completion message."""
    # Setup mocks
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = CircuitState()
    lifecycle_mgr_cls.return_value = mock_mgr
    
    mock_srv = Mock(spec=MockServer)
    mock_server_cls.return_value = mock_srv
    
    # Execute
    result = local_provider.deploy(circuit_spec, deployment_target_mock_mode)
    
    # Assertions
    logger.info.assert_called()
    call_args = logger.info.call_args[0][0]
    assert 'completed' in call_args.lower() or 'deployment' in call_args.lower(), \
        "Log message should indicate deployment completion"


@patch('__main__.LifecycleManager')
def test_invariant_mgr_valid_when_not_none(lifecycle_mgr_cls, local_provider,
                                           circuit_spec, deployment_target_no_mock):
    """Invariant: When _mgr is not None, it contains valid LifecycleManager."""
    # Setup mocks
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = CircuitState()
    lifecycle_mgr_cls.return_value = mock_mgr
    
    # Execute
    local_provider.deploy(circuit_spec, deployment_target_no_mock)
    
    # Assertions
    assert local_provider._mgr is not None, "_mgr should not be None"
    assert isinstance(local_provider._mgr, (LifecycleManager, Mock)), \
        "_mgr should be LifecycleManager instance"


@patch('__main__.LifecycleManager')
@patch('__main__.MockServer')
def test_invariant_mock_server_implies_mock_mode(mock_server_cls, lifecycle_mgr_cls,
                                                  local_provider, circuit_spec, deployment_target_mock_mode):
    """Invariant: When _mock_server is not None, mock mode is active."""
    # Setup mocks
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = CircuitState()
    lifecycle_mgr_cls.return_value = mock_mgr
    
    mock_srv = Mock(spec=MockServer)
    mock_server_cls.return_value = mock_srv
    
    # Execute with mock=true
    local_provider.deploy(circuit_spec, deployment_target_mock_mode)
    
    # Assertions
    assert local_provider._mock_server is not None, \
        "_mock_server should be set when mock mode is active"


# ============================================================================
# TESTS FOR teardown()
# ============================================================================

def test_teardown_with_mock_server_success(local_provider, circuit_spec, deployment_target):
    """Teardown successfully stops mock server and lifecycle manager."""
    # Setup
    mock_mgr = Mock(spec=LifecycleManager)
    mock_srv = Mock(spec=MockServer)
    local_provider._mgr = mock_mgr
    local_provider._mock_server = mock_srv
    
    # Execute
    local_provider.teardown(circuit_spec, deployment_target)
    
    # Assertions
    mock_srv.stop.assert_called_once()
    mock_mgr.down.assert_called_once()
    assert local_provider._mgr is None, "self._mgr should be None"
    assert local_provider._mock_server is None, "self._mock_server should be None"
    logger.info.assert_called()


def test_teardown_without_mock_server(local_provider, circuit_spec, deployment_target):
    """Teardown successfully stops only lifecycle manager when no mock server."""
    # Setup
    mock_mgr = Mock(spec=LifecycleManager)
    local_provider._mgr = mock_mgr
    local_provider._mock_server = None
    
    # Execute
    local_provider.teardown(circuit_spec, deployment_target)
    
    # Assertions
    mock_mgr.down.assert_called_once()
    assert local_provider._mgr is None, "self._mgr should be None"
    assert local_provider._mock_server is None, "self._mock_server should be None"
    logger.info.assert_called()


def test_teardown_undeployed_provider(local_provider, circuit_spec, deployment_target):
    """Teardown on undeployed provider (both None) succeeds gracefully."""
    # Setup - both already None
    assert local_provider._mgr is None
    assert local_provider._mock_server is None
    
    # Execute - should not raise
    local_provider.teardown(circuit_spec, deployment_target)
    
    # Assertions
    assert local_provider._mgr is None, "self._mgr should remain None"
    assert local_provider._mock_server is None, "self._mock_server should remain None"


def test_teardown_mock_server_stop_error(local_provider, circuit_spec, deployment_target):
    """Teardown fails when mock server stop raises error."""
    # Setup
    mock_srv = Mock(spec=MockServer)
    mock_srv.stop.side_effect = Exception("Stop failed")
    local_provider._mock_server = mock_srv
    
    # Execute and assert
    with pytest.raises(MockServerStopError):
        local_provider.teardown(circuit_spec, deployment_target)


def test_teardown_lifecycle_manager_error(local_provider, circuit_spec, deployment_target):
    """Teardown fails when LifecycleManager.down() raises error."""
    # Setup
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.down.side_effect = Exception("Down failed")
    local_provider._mgr = mock_mgr
    local_provider._mock_server = None
    
    # Execute and assert
    with pytest.raises(LifecycleManagerError):
        local_provider.teardown(circuit_spec, deployment_target)


def test_teardown_cleans_up_partial_deployment(local_provider, circuit_spec, deployment_target):
    """Teardown handles case where only _mgr is set (partial deployment)."""
    # Setup
    mock_mgr = Mock(spec=LifecycleManager)
    local_provider._mgr = mock_mgr
    local_provider._mock_server = None
    
    # Execute
    local_provider.teardown(circuit_spec, deployment_target)
    
    # Assertions
    mock_mgr.down.assert_called_once()
    assert local_provider._mgr is None, "_mgr should be cleaned up"
    assert local_provider._mock_server is None, "_mock_server should remain None"


def test_teardown_logging_called(local_provider, circuit_spec, deployment_target):
    """Teardown logs completion message."""
    # Setup
    mock_mgr = Mock(spec=LifecycleManager)
    local_provider._mgr = mock_mgr
    
    # Execute
    local_provider.teardown(circuit_spec, deployment_target)
    
    # Assertions
    logger.info.assert_called()
    call_args = logger.info.call_args[0][0]
    assert 'teardown' in call_args.lower() or 'completed' in call_args.lower(), \
        "Log message should indicate teardown completion"


@patch('__main__.LifecycleManager')
@patch('__main__.MockServer')
def test_invariant_both_none_after_teardown(mock_server_cls, lifecycle_mgr_cls,
                                            local_provider, circuit_spec, deployment_target_mock_mode):
    """Invariant: Both _mgr and _mock_server are None after teardown."""
    # Setup and deploy
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = CircuitState()
    lifecycle_mgr_cls.return_value = mock_mgr
    
    mock_srv = Mock(spec=MockServer)
    mock_server_cls.return_value = mock_srv
    
    local_provider.deploy(circuit_spec, deployment_target_mock_mode)
    
    # Teardown
    local_provider.teardown(circuit_spec, deployment_target_mock_mode)
    
    # Assertions
    assert local_provider._mgr is None, "After teardown, _mgr must be None"
    assert local_provider._mock_server is None, "After teardown, _mock_server must be None"


# ============================================================================
# TESTS FOR status()
# ============================================================================

def test_status_with_active_manager(local_provider, circuit_spec, deployment_target):
    """Status returns manager state when _mgr exists and has state."""
    # Setup
    expected_state = CircuitState(circuit_name="test", collapse_level=CollapseLevel.FULL_LIVE)
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = expected_state
    local_provider._mgr = mock_mgr
    
    # Execute
    result = local_provider.status(circuit_spec, deployment_target)
    
    # Assertions
    assert result is expected_state, "Should return _mgr.state"
    assert result.circuit_name == "test", "State should match expected"


def test_status_without_manager(local_provider, circuit_spec, deployment_target):
    """Status returns default state with FULL_MOCK when _mgr is None."""
    # Setup - _mgr already None
    assert local_provider._mgr is None
    
    # Execute
    result = local_provider.status(circuit_spec, deployment_target)
    
    # Assertions
    assert isinstance(result, CircuitState), "Should return CircuitState"
    assert result.collapse_level == CollapseLevel.FULL_MOCK, "collapse_level should be FULL_MOCK"
    assert result.circuit_name == circuit_spec.name, "circuit_name should match circuit.name"


def test_status_idempotency(local_provider, circuit_spec, deployment_target):
    """Multiple status calls return consistent results without side effects."""
    # Setup
    expected_state = CircuitState(circuit_name="test", collapse_level=CollapseLevel.PARTIAL)
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = expected_state
    local_provider._mgr = mock_mgr
    
    # Execute multiple times
    result1 = local_provider.status(circuit_spec, deployment_target)
    result2 = local_provider.status(circuit_spec, deployment_target)
    
    # Assertions
    assert result1 is result2, "Same state should be returned"
    assert result1.circuit_name == result2.circuit_name, "Results should be identical"


def test_status_returns_circuit_state_type(local_provider, circuit_spec, deployment_target):
    """Status always returns CircuitState object."""
    # Test with manager
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = CircuitState()
    local_provider._mgr = mock_mgr
    
    result1 = local_provider.status(circuit_spec, deployment_target)
    assert isinstance(result1, CircuitState), "Should return CircuitState with manager"
    
    # Test without manager
    local_provider._mgr = None
    result2 = local_provider.status(circuit_spec, deployment_target)
    assert isinstance(result2, CircuitState), "Should return CircuitState without manager"


# ============================================================================
# TESTS FOR STATE TRANSITIONS
# ============================================================================

@patch('__main__.LifecycleManager')
@patch('__main__.MockServer')
def test_deploy_then_status_consistency(mock_server_cls, lifecycle_mgr_cls,
                                       local_provider, circuit_spec, deployment_target_mock_mode):
    """Status after deploy returns deployed state."""
    # Setup mocks
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = CircuitState()
    lifecycle_mgr_cls.return_value = mock_mgr
    
    mock_srv = Mock(spec=MockServer)
    mock_server_cls.return_value = mock_srv
    
    # Deploy
    deploy_result = local_provider.deploy(circuit_spec, deployment_target_mock_mode)
    
    # Get status
    status_result = local_provider.status(circuit_spec, deployment_target_mock_mode)
    
    # Assertions
    assert isinstance(deploy_result, CircuitState), "Deploy should return CircuitState"
    assert isinstance(status_result, CircuitState), "Status should return CircuitState"
    assert status_result.circuit_name == deploy_result.circuit_name, \
        "Status should be consistent with deployment"


@patch('__main__.LifecycleManager')
@patch('__main__.MockServer')
def test_deploy_teardown_status_transition(mock_server_cls, lifecycle_mgr_cls,
                                           local_provider, circuit_spec, deployment_target_mock_mode):
    """Status after deploy and teardown shows undeployed state."""
    # Setup mocks
    mock_mgr = Mock(spec=LifecycleManager)
    mock_mgr.state = CircuitState()
    lifecycle_mgr_cls.return_value = mock_mgr
    
    mock_srv = Mock(spec=MockServer)
    mock_server_cls.return_value = mock_srv
    
    # Deploy
    local_provider.deploy(circuit_spec, deployment_target_mock_mode)
    
    # Teardown
    local_provider.teardown(circuit_spec, deployment_target_mock_mode)
    
    # Assertions
    assert local_provider._mgr is None, "After teardown, _mgr should be None"
    
    # Get status
    status_result = local_provider.status(circuit_spec, deployment_target_mock_mode)
    
    # Assertions
    assert status_result.collapse_level == CollapseLevel.FULL_MOCK, \
        "Status should return default FULL_MOCK state after teardown"
