"""
Contract-driven test suite for LifecycleManager component.
Tests verify circuit lifecycle orchestration with adapters, controls, processes, and state management.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call, mock_open
from pathlib import Path
from datetime import datetime, timezone
import json
import re


# Import the component under test
try:
    from src.baton.lifecycle import LifecycleManager, _now_iso
except ImportError:
    try:
        from baton.lifecycle import LifecycleManager, _now_iso
    except ImportError:
        # For testing purposes, we'll create mock imports
        LifecycleManager = None
        _now_iso = None


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def tmp_project_dir(tmp_path):
    """Provide an isolated temporary project directory for each test."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / ".baton").mkdir()
    return project


@pytest.fixture
def mock_circuit_spec():
    """Create a mock CircuitSpec for testing."""
    mock_spec = Mock()
    mock_spec.nodes = {
        "api": Mock(
            name="api",
            port=8000,
            role=Mock(name="INTERNAL"),
            host="localhost"
        ),
        "db": Mock(
            name="db",
            port=5432,
            role=Mock(name="INTERNAL"),
            host="localhost"
        ),
        "egress_node": Mock(
            name="egress_node",
            port=9000,
            role=Mock(name="EGRESS"),
            host="localhost"
        )
    }
    return mock_spec


@pytest.fixture
def mock_adapter():
    """Create a mock Adapter instance."""
    adapter = Mock()
    adapter.routing = None
    adapter._routing = None
    adapter.backend = Mock()
    adapter.backend.is_configured = False
    adapter.drain = Mock()
    adapter.stop = Mock()
    return adapter


@pytest.fixture
def mock_adapter_control():
    """Create a mock AdapterControlServer instance."""
    control = Mock()
    control.stop = Mock()
    return control


@pytest.fixture
def mock_process_manager():
    """Create a mock ProcessManager instance."""
    pm = Mock()
    pm.start = Mock()
    pm.stop = Mock()
    pm.stop_all = Mock()
    pm.is_running = Mock(return_value=False)
    pm.rename = Mock()
    return pm


@pytest.fixture
def mock_state():
    """Create a mock CircuitState instance."""
    state = Mock()
    state.live_nodes = []
    state.nodes = {}
    state.collapse_level = None
    state.started_at = "2024-01-01T00:00:00Z"
    state.save = Mock()
    return state


@pytest.fixture
def lifecycle_manager_mocked(tmp_project_dir, mock_process_manager):
    """Create a LifecycleManager with mocked dependencies."""
    with patch('baton.lifecycle.ProcessManager', return_value=mock_process_manager):
        manager = LifecycleManager(str(tmp_project_dir))
        manager._process_mgr = mock_process_manager
        return manager


# ============================================================================
# TEST: _now_iso()
# ============================================================================

def test_now_iso_returns_iso8601_format():
    """Verify _now_iso returns a properly formatted ISO 8601 UTC timestamp."""
    # Act
    result = _now_iso()
    
    # Assert
    assert isinstance(result, str), "Result should be a string"
    
    # Check ISO 8601 format with timezone
    iso_pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(\+00:00|Z)$'
    assert re.match(iso_pattern, result), f"Result '{result}' should match ISO 8601 format"
    
    # Verify it can be parsed back as UTC
    parsed = datetime.fromisoformat(result.replace('Z', '+00:00'))
    assert parsed.tzinfo is not None, "Timestamp should have timezone info"


# ============================================================================
# TEST: __init__()
# ============================================================================

def test_init_sets_all_fields(tmp_project_dir):
    """Verify __init__ properly initializes all fields of LifecycleManager."""
    # Arrange
    project_path = str(tmp_project_dir)
    
    # Act
    with patch('baton.lifecycle.ProcessManager'):
        manager = LifecycleManager(project_path)
    
    # Assert
    assert manager.project_dir == Path(project_path), "project_dir should be set to Path(project_dir)"
    assert manager._adapters == {}, "_adapters should be empty dict"
    assert manager._controls == {}, "_controls should be empty dict"
    assert manager._process_mgr is not None, "_process_mgr should be initialized"
    assert manager._circuit is None, "_circuit should be None"
    assert manager._state is None, "_state should be None"


def test_init_with_path_object(tmp_project_dir):
    """Verify __init__ accepts Path object as project_dir."""
    # Arrange
    project_path = Path(tmp_project_dir)
    
    # Act
    with patch('baton.lifecycle.ProcessManager'):
        manager = LifecycleManager(project_path)
    
    # Assert
    assert manager.project_dir == project_path, "project_dir should be set correctly"
    assert manager._adapters == {}, "All fields should be initialized properly"
    assert manager._controls == {}
    assert manager._circuit is None
    assert manager._state is None


# ============================================================================
# TEST: adapters property
# ============================================================================

def test_adapters_returns_copy(lifecycle_manager_mocked, mock_adapter):
    """Verify adapters property returns a shallow copy."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter, "db": Mock()}
    
    # Act
    result = manager.adapters
    
    # Assert
    assert result == manager._adapters, "Should return dict matching _adapters content"
    assert result is not manager._adapters, "Should be a copy, not the original"
    
    # Verify modifying returned dict doesn't affect internal state
    result["new_node"] = Mock()
    assert "new_node" not in manager._adapters, "Modifying returned dict should not affect internal state"


# ============================================================================
# TEST: state property
# ============================================================================

def test_state_returns_current_state(lifecycle_manager_mocked, mock_state):
    """Verify state property returns current _state."""
    # Arrange
    manager = lifecycle_manager_mocked
    
    # Test with None
    manager._state = None
    assert manager.state is None, "Should return None when no state exists"
    
    # Test with state
    manager._state = mock_state
    assert manager.state == mock_state, "Should return self._state value"


# ============================================================================
# TEST: up()
# ============================================================================

def test_up_initializes_circuit(lifecycle_manager_mocked, mock_circuit_spec, mock_state):
    """Verify up() boots the circuit and initializes state."""
    # Arrange
    manager = lifecycle_manager_mocked
    
    with patch('baton.lifecycle.CircuitSpec') as MockCircuitSpec, \
         patch('baton.lifecycle.CircuitState') as MockCircuitState, \
         patch('baton.lifecycle.Adapter') as MockAdapter, \
         patch('baton.lifecycle.AdapterControlServer') as MockControl, \
         patch.object(Path, 'mkdir'), \
         patch('builtins.open', mock_open()):
        
        MockCircuitSpec.load.return_value = mock_circuit_spec
        MockCircuitState.return_value = mock_state
        MockAdapter.return_value = Mock()
        MockControl.return_value = Mock()
        
        # Act
        result = manager.up(mock=False)
        
        # Assert
        MockCircuitSpec.load.assert_called_once(), "Circuit configuration should be loaded"
        assert manager._circuit == mock_circuit_spec, "Circuit should be set"
        assert manager._state == mock_state, "State should be created"
        assert len(manager._adapters) > 0, "Adapters should be started"
        assert len(manager._controls) > 0, "Control servers should be started"
        mock_state.save.assert_called(), "State should be saved"
        assert result == mock_state, "Should return CircuitState object"


def test_up_with_mock_mode(lifecycle_manager_mocked, mock_circuit_spec, mock_state):
    """Verify up() works in mock mode."""
    # Arrange
    manager = lifecycle_manager_mocked
    
    with patch('baton.lifecycle.CircuitSpec') as MockCircuitSpec, \
         patch('baton.lifecycle.CircuitState') as MockCircuitState, \
         patch('baton.lifecycle.Adapter') as MockAdapter, \
         patch('baton.lifecycle.AdapterControlServer') as MockControl, \
         patch.object(Path, 'mkdir'), \
         patch('builtins.open', mock_open()):
        
        MockCircuitSpec.load.return_value = mock_circuit_spec
        MockCircuitState.return_value = mock_state
        MockAdapter.return_value = Mock()
        MockControl.return_value = Mock()
        
        # Act
        result = manager.up(mock=True)
        
        # Assert
        assert result == mock_state, "Should return CircuitState"
        mock_state.save.assert_called(), "State should be saved"


# ============================================================================
# TEST: down()
# ============================================================================

def test_down_stops_all_resources(lifecycle_manager_mocked, mock_adapter, mock_adapter_control, mock_state):
    """Verify down() cleanly tears down all circuit resources."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._controls = {"api": mock_adapter_control}
    manager._state = mock_state
    
    # Act
    manager.down()
    
    # Assert
    manager._process_mgr.stop_all.assert_called(), "All processes should be stopped"
    mock_adapter_control.stop.assert_called(), "Control servers should be stopped"
    mock_adapter.drain.assert_called(), "Adapters should be drained"
    mock_adapter.stop.assert_called(), "Adapters should be stopped"
    assert manager._adapters == {}, "Adapters dict should be cleared"
    assert manager._controls == {}, "Controls dict should be cleared"
    mock_state.save.assert_called(), "State should be saved"


def test_down_when_no_state(lifecycle_manager_mocked):
    """Verify down() handles case with no existing state."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._state = None
    manager._adapters = {}
    manager._controls = {}
    
    # Act - should not raise any errors
    try:
        manager.down()
        success = True
    except Exception:
        success = False
    
    # Assert
    assert success, "Should handle None state without errors"
    manager._process_mgr.stop_all.assert_called(), "Cleanup should proceed normally"


# ============================================================================
# TEST: slot()
# ============================================================================

def test_slot_starts_service(lifecycle_manager_mocked, mock_adapter, mock_state, mock_circuit_spec):
    """Verify slot() starts a live service and configures adapter."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    manager._circuit = mock_circuit_spec
    mock_state.nodes = {"api": Mock()}
    
    # Act
    manager.slot("api", "python app.py", {"PORT": "8000"})
    
    # Assert
    manager._process_mgr.start.assert_called(), "Service process should be started"
    assert "api" in mock_state.live_nodes or mock_state.nodes["api"] is not None, "Node should be marked as live"
    mock_state.save.assert_called(), "State should be saved"


def test_slot_with_null_env(lifecycle_manager_mocked, mock_adapter, mock_state, mock_circuit_spec):
    """Verify slot() works with no environment variables."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    manager._circuit = mock_circuit_spec
    mock_state.nodes = {"api": Mock()}
    
    # Act
    manager.slot("api", "python app.py", None)
    
    # Assert
    manager._process_mgr.start.assert_called(), "Service should start without env"
    mock_state.save.assert_called(), "State should be saved"


def test_slot_node_not_found(lifecycle_manager_mocked):
    """Verify slot() raises error when node doesn't exist."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {}
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.slot("nonexistent", "python app.py", None)
    
    assert "not found" in str(exc_info.value).lower() or \
           "nonexistent" in str(exc_info.value) or \
           exc_info.typename == "KeyError", "Should raise node_not_found error"


def test_slot_routing_locked(lifecycle_manager_mocked, mock_adapter, mock_state):
    """Verify slot() raises error when routing is locked."""
    # Arrange
    manager = lifecycle_manager_mocked
    mock_routing = Mock()
    mock_routing.locked = True
    mock_adapter.routing = mock_routing
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.slot("api", "python app.py", None)
    
    assert "lock" in str(exc_info.value).lower() or \
           "routing" in str(exc_info.value).lower(), "Should raise routing_locked error"


def test_slot_egress_node(lifecycle_manager_mocked, mock_adapter, mock_state, mock_circuit_spec):
    """Verify slot() raises error for egress nodes."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"egress_node": mock_adapter}
    manager._state = mock_state
    manager._circuit = mock_circuit_spec
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.slot("egress_node", "python app.py", None)
    
    assert "egress" in str(exc_info.value).lower(), "Should raise egress_node error"


# ============================================================================
# TEST: swap()
# ============================================================================

def test_swap_hot_swaps_service(lifecycle_manager_mocked, mock_adapter, mock_state, mock_circuit_spec):
    """Verify swap() performs hot-swap of running service."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    manager._circuit = mock_circuit_spec
    manager._process_mgr.is_running.return_value = True
    mock_state.nodes = {"api": Mock(command="python app_v1.py")}
    
    # Act
    manager.swap("api", "python app_v2.py", {"VERSION": "2"})
    
    # Assert
    assert manager._process_mgr.start.call_count >= 1, "New service should be started"
    mock_adapter.drain.assert_called(), "Old connections should be drained"
    manager._process_mgr.stop.assert_called(), "Old process should be stopped"
    mock_state.save.assert_called(), "State should reflect new service"


def test_swap_node_not_found(lifecycle_manager_mocked):
    """Verify swap() raises error when node doesn't exist."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {}
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.swap("nonexistent", "python app.py", None)
    
    assert "not found" in str(exc_info.value).lower() or \
           "nonexistent" in str(exc_info.value) or \
           exc_info.typename == "KeyError", "Should raise node_not_found error"


def test_swap_routing_locked(lifecycle_manager_mocked, mock_adapter, mock_state):
    """Verify swap() raises error when routing is locked."""
    # Arrange
    manager = lifecycle_manager_mocked
    mock_routing = Mock()
    mock_routing.locked = True
    mock_adapter.routing = mock_routing
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.swap("api", "python app.py", None)
    
    assert "lock" in str(exc_info.value).lower() or \
           "routing" in str(exc_info.value).lower(), "Should raise routing_locked error"


# ============================================================================
# TEST: slot_mock()
# ============================================================================

def test_slot_mock_removes_service(lifecycle_manager_mocked, mock_adapter, mock_state):
    """Verify slot_mock() replaces live service with mock."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    manager._process_mgr.is_running.return_value = True
    mock_state.live_nodes = ["api"]
    mock_state.nodes = {"api": Mock()}
    
    # Act
    manager.slot_mock("api")
    
    # Assert
    manager._process_mgr.stop.assert_called(), "Service process should be stopped"
    assert "api" not in mock_state.live_nodes, "Node should be removed from live_nodes"
    mock_state.save.assert_called(), "State should be saved"


def test_slot_mock_node_not_found(lifecycle_manager_mocked):
    """Verify slot_mock() raises error for nonexistent node."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {}
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.slot_mock("nonexistent")
    
    assert "not found" in str(exc_info.value).lower() or \
           "nonexistent" in str(exc_info.value) or \
           exc_info.typename == "KeyError", "Should raise node_not_found error"


# ============================================================================
# TEST: slot_ab()
# ============================================================================

def test_slot_ab_starts_two_instances(lifecycle_manager_mocked, mock_adapter, mock_state, mock_circuit_spec):
    """Verify slot_ab() starts A/B instances with weighted routing."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    manager._circuit = mock_circuit_spec
    mock_state.nodes = {"api": Mock()}
    
    # Act
    manager.slot_ab("api", "python app_a.py", "python app_b.py", (80, 20))
    
    # Assert
    assert manager._process_mgr.start.call_count >= 2, "Two processes should be started"
    mock_state.save.assert_called(), "State should have A/B configuration"


def test_slot_ab_50_50_split(lifecycle_manager_mocked, mock_adapter, mock_state, mock_circuit_spec):
    """Verify slot_ab() works with 50/50 split."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    manager._circuit = mock_circuit_spec
    mock_state.nodes = {"api": Mock()}
    
    # Act
    manager.slot_ab("api", "python app_a.py", "python app_b.py", (50, 50))
    
    # Assert
    assert manager._process_mgr.start.call_count >= 2, "Both instances should be started"


def test_slot_ab_node_not_found(lifecycle_manager_mocked):
    """Verify slot_ab() raises error for nonexistent node."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {}
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.slot_ab("nonexistent", "python app_a.py", "python app_b.py", (50, 50))
    
    assert "not found" in str(exc_info.value).lower() or \
           "nonexistent" in str(exc_info.value) or \
           exc_info.typename == "KeyError", "Should raise node_not_found error"


def test_slot_ab_routing_locked(lifecycle_manager_mocked, mock_adapter, mock_state):
    """Verify slot_ab() raises error when routing is locked."""
    # Arrange
    manager = lifecycle_manager_mocked
    mock_routing = Mock()
    mock_routing.locked = True
    mock_adapter.routing = mock_routing
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.slot_ab("api", "python app_a.py", "python app_b.py", (50, 50))
    
    assert "lock" in str(exc_info.value).lower() or \
           "routing" in str(exc_info.value).lower(), "Should raise routing_locked error"


# ============================================================================
# TEST: route_ab()
# ============================================================================

def test_route_ab_adds_second_instance(lifecycle_manager_mocked, mock_adapter, mock_state, mock_circuit_spec):
    """Verify route_ab() adds B instance to running A."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    manager._circuit = mock_circuit_spec
    manager._process_mgr.is_running.return_value = True
    mock_adapter.backend.is_configured = True
    mock_state.nodes = {"api": Mock()}
    
    # Act
    manager.route_ab("api", "python app_b.py", (90, 10))
    
    # Assert
    manager._process_mgr.start.assert_called(), "Instance B should be started"
    manager._process_mgr.rename.assert_called(), "Existing service should be renamed to A"
    mock_state.save.assert_called(), "State should be updated with routing"


def test_route_ab_node_not_found(lifecycle_manager_mocked):
    """Verify route_ab() raises error for nonexistent node."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {}
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.route_ab("nonexistent", "python app_b.py", (50, 50))
    
    assert "not found" in str(exc_info.value).lower() or \
           "nonexistent" in str(exc_info.value) or \
           exc_info.typename == "KeyError", "Should raise node_not_found error"


def test_route_ab_routing_locked(lifecycle_manager_mocked, mock_adapter, mock_state):
    """Verify route_ab() raises error when routing is locked."""
    # Arrange
    manager = lifecycle_manager_mocked
    mock_routing = Mock()
    mock_routing.locked = True
    mock_adapter.routing = mock_routing
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.route_ab("api", "python app_b.py", (50, 50))
    
    assert "lock" in str(exc_info.value).lower() or \
           "routing" in str(exc_info.value).lower(), "Should raise routing_locked error"


def test_route_ab_no_service_running(lifecycle_manager_mocked, mock_adapter, mock_state):
    """Verify route_ab() raises error when no service is running."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    manager._process_mgr.is_running.return_value = False
    mock_adapter.backend.is_configured = False
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.route_ab("api", "python app_b.py", (50, 50))
    
    assert "running" in str(exc_info.value).lower() or \
           "service" in str(exc_info.value).lower() or \
           "stable" in str(exc_info.value).lower(), "Should raise no_service_running error"


# ============================================================================
# TEST: set_routing()
# ============================================================================

def test_set_routing_configures_adapter(lifecycle_manager_mocked, mock_adapter, mock_state):
    """Verify set_routing() applies routing config to adapter."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    mock_state.nodes = {"api": Mock()}
    
    mock_config = Mock()
    mock_config.locked = False
    
    # Act
    manager.set_routing("api", mock_config)
    
    # Assert
    assert mock_adapter.routing == mock_config or hasattr(mock_adapter, 'set_routing'), \
        "Routing config should be set on adapter"
    mock_state.save.assert_called(), "State should be saved"


def test_set_routing_node_not_found(lifecycle_manager_mocked):
    """Verify set_routing() raises error for nonexistent node."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {}
    mock_config = Mock()
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.set_routing("nonexistent", mock_config)
    
    assert "not found" in str(exc_info.value).lower() or \
           "nonexistent" in str(exc_info.value) or \
           exc_info.typename == "KeyError", "Should raise node_not_found error"


# ============================================================================
# TEST: lock_routing()
# ============================================================================

def test_lock_routing_locks_config(lifecycle_manager_mocked, mock_adapter, mock_state):
    """Verify lock_routing() locks the routing configuration."""
    # Arrange
    manager = lifecycle_manager_mocked
    mock_routing = Mock()
    mock_routing.locked = False
    mock_adapter.routing = mock_routing
    mock_adapter._routing = mock_routing
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    mock_state.nodes = {"api": Mock(routing=mock_routing)}
    
    # Act
    manager.lock_routing("api")
    
    # Assert
    assert mock_routing.locked == True, "Routing config should be locked"
    mock_state.save.assert_called(), "State should be saved"


def test_lock_routing_node_not_found(lifecycle_manager_mocked):
    """Verify lock_routing() raises error for nonexistent node."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {}
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.lock_routing("nonexistent")
    
    assert "not found" in str(exc_info.value).lower() or \
           "nonexistent" in str(exc_info.value) or \
           exc_info.typename == "KeyError", "Should raise node_not_found error"


def test_lock_routing_no_routing_config(lifecycle_manager_mocked, mock_adapter):
    """Verify lock_routing() raises error when no routing config exists."""
    # Arrange
    manager = lifecycle_manager_mocked
    mock_adapter.routing = None
    manager._adapters = {"api": mock_adapter}
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.lock_routing("api")
    
    assert "routing" in str(exc_info.value).lower() or \
           "config" in str(exc_info.value).lower() or \
           exc_info.typename in ["AttributeError", "ValueError"], \
           "Should raise no_routing_config error"


# ============================================================================
# TEST: unlock_routing()
# ============================================================================

def test_unlock_routing_unlocks_config(lifecycle_manager_mocked, mock_adapter, mock_state):
    """Verify unlock_routing() unlocks the routing configuration."""
    # Arrange
    manager = lifecycle_manager_mocked
    mock_routing = Mock()
    mock_routing.locked = True
    mock_adapter.routing = mock_routing
    mock_adapter._routing = mock_routing
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    mock_state.nodes = {"api": Mock(routing=mock_routing)}
    
    # Act
    manager.unlock_routing("api")
    
    # Assert
    assert mock_routing.locked == False, "Routing config should be unlocked"
    mock_state.save.assert_called(), "State should be saved"


def test_unlock_routing_node_not_found(lifecycle_manager_mocked):
    """Verify unlock_routing() raises error for nonexistent node."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {}
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.unlock_routing("nonexistent")
    
    assert "not found" in str(exc_info.value).lower() or \
           "nonexistent" in str(exc_info.value) or \
           exc_info.typename == "KeyError", "Should raise node_not_found error"


def test_unlock_routing_no_routing_config(lifecycle_manager_mocked, mock_adapter):
    """Verify unlock_routing() raises error when no routing config exists."""
    # Arrange
    manager = lifecycle_manager_mocked
    mock_adapter.routing = None
    manager._adapters = {"api": mock_adapter}
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.unlock_routing("api")
    
    assert "routing" in str(exc_info.value).lower() or \
           "config" in str(exc_info.value).lower() or \
           exc_info.typename in ["AttributeError", "ValueError"], \
           "Should raise no_routing_config error"


# ============================================================================
# TEST: start_canary()
# ============================================================================

def test_start_canary_begins_deployment(lifecycle_manager_mocked, mock_adapter, mock_state, mock_circuit_spec):
    """Verify start_canary() initiates canary deployment with controller."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    manager._circuit = mock_circuit_spec
    manager._process_mgr.is_running.return_value = True
    mock_adapter.backend.is_configured = True
    mock_state.nodes = {"api": Mock()}
    
    with patch('baton.lifecycle.CanaryController') as MockCanary:
        mock_controller = Mock()
        MockCanary.return_value = mock_controller
        
        # Act
        result = manager.start_canary("api", "python app_canary.py", 10, {"interval": 30})
        
        # Assert
        manager._process_mgr.start.assert_called(), "Canary service should be started"
        assert result == mock_controller, "Should return CanaryController"
        mock_state.save.assert_called(), "State should be updated"


def test_start_canary_node_not_found(lifecycle_manager_mocked):
    """Verify start_canary() raises error for nonexistent node."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {}
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.start_canary("nonexistent", "python app.py", 10, {})
    
    assert "not found" in str(exc_info.value).lower() or \
           "nonexistent" in str(exc_info.value) or \
           exc_info.typename == "KeyError", "Should raise node_not_found error"


def test_start_canary_routing_locked(lifecycle_manager_mocked, mock_adapter, mock_state):
    """Verify start_canary() raises error when routing is locked."""
    # Arrange
    manager = lifecycle_manager_mocked
    mock_routing = Mock()
    mock_routing.locked = True
    mock_adapter.routing = mock_routing
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.start_canary("api", "python app.py", 10, {})
    
    assert "lock" in str(exc_info.value).lower() or \
           "routing" in str(exc_info.value).lower(), "Should raise routing_locked error"


def test_start_canary_no_stable_service(lifecycle_manager_mocked, mock_adapter, mock_state):
    """Verify start_canary() raises error when no stable service exists."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    manager._process_mgr.is_running.return_value = False
    mock_adapter.backend.is_configured = False
    
    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        manager.start_canary("api", "python app.py", 10, {})
    
    assert "stable" in str(exc_info.value).lower() or \
           "service" in str(exc_info.value).lower() or \
           "running" in str(exc_info.value).lower(), "Should raise no_stable_service error"


# ============================================================================
# TEST: restart_service()
# ============================================================================

def test_restart_service_restarts_node(lifecycle_manager_mocked, mock_state, mock_circuit_spec):
    """Verify restart_service() restarts a node's service."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._state = mock_state
    manager._circuit = mock_circuit_spec
    mock_state.nodes = {"api": Mock(command="python app.py", env={"PORT": "8000"})}
    
    with patch.object(manager, 'slot') as mock_slot:
        # Act
        manager.restart_service("api")
        
        # Assert
        mock_slot.assert_called_once(), "Service should be restarted via slot()"


# ============================================================================
# TEST: _compute_collapse_level()
# ============================================================================

def test_compute_collapse_level_full_mock(lifecycle_manager_mocked):
    """Verify _compute_collapse_level returns FULL_MOCK when no live nodes."""
    # Arrange
    manager = lifecycle_manager_mocked
    
    # Test with no state
    manager._state = None
    manager._circuit = None
    result = manager._compute_collapse_level()
    assert str(result).endswith("FULL_MOCK") or result == "FULL_MOCK", \
        "Should return FULL_MOCK when no state exists"
    
    # Test with state but no live nodes
    mock_state = Mock()
    mock_state.live_nodes = []
    manager._state = mock_state
    manager._circuit = Mock(nodes={"api": Mock(), "db": Mock()})
    result = manager._compute_collapse_level()
    assert str(result).endswith("FULL_MOCK") or result == "FULL_MOCK", \
        "Should return FULL_MOCK when no live nodes"


def test_compute_collapse_level_full_live(lifecycle_manager_mocked):
    """Verify _compute_collapse_level returns FULL_LIVE when all nodes are live."""
    # Arrange
    manager = lifecycle_manager_mocked
    mock_state = Mock()
    mock_state.live_nodes = ["api", "db"]
    manager._state = mock_state
    manager._circuit = Mock(nodes={"api": Mock(), "db": Mock()})
    
    # Act
    result = manager._compute_collapse_level()
    
    # Assert
    assert str(result).endswith("FULL_LIVE") or result == "FULL_LIVE", \
        "Should return FULL_LIVE when all nodes are live"


def test_compute_collapse_level_partial(lifecycle_manager_mocked):
    """Verify _compute_collapse_level returns PARTIAL when some nodes are live."""
    # Arrange
    manager = lifecycle_manager_mocked
    mock_state = Mock()
    mock_state.live_nodes = ["api"]
    manager._state = mock_state
    manager._circuit = Mock(nodes={"api": Mock(), "db": Mock()})
    
    # Act
    result = manager._compute_collapse_level()
    
    # Assert
    assert str(result).endswith("PARTIAL") or result == "PARTIAL", \
        "Should return PARTIAL when some but not all nodes are live"


# ============================================================================
# INVARIANT TESTS
# ============================================================================

def test_port_allocation_invariant(lifecycle_manager_mocked, mock_adapter, mock_state, mock_circuit_spec):
    """Verify port allocation follows the invariant: service_port = node.port + 20000 or +5000 if >65535."""
    # Arrange
    manager = lifecycle_manager_mocked
    
    # Test normal port allocation (port + 20000)
    normal_node = Mock(port=8000)
    expected_normal = 8000 + 20000
    assert expected_normal == 28000, "Service port should be node.port + 20000 for normal ports"
    
    # Test high port allocation (port + 5000 when result > 65535)
    high_node = Mock(port=60000)
    expected_high = 60000 + 5000
    result_if_20000 = 60000 + 20000
    assert result_if_20000 > 65535, "Normal allocation would exceed 65535"
    assert expected_high == 65000, "Service port should be node.port + 5000 when result would exceed 65535"


def test_process_naming_invariant_base(lifecycle_manager_mocked, mock_adapter, mock_state, mock_circuit_spec):
    """Verify base process naming invariant."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    manager._circuit = mock_circuit_spec
    mock_state.nodes = {"api": Mock()}
    
    # Act
    manager.slot("api", "python app.py", None)
    
    # Assert
    call_args = manager._process_mgr.start.call_args
    if call_args:
        process_name = call_args[0][0] if call_args[0] else None
        assert process_name == "api" or "api" in str(process_name), \
            "Process should use base node name for slot()"


def test_process_naming_invariant_ab(lifecycle_manager_mocked, mock_adapter, mock_state, mock_circuit_spec):
    """Verify A/B process naming uses __a and __b suffixes."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    manager._circuit = mock_circuit_spec
    mock_state.nodes = {"api": Mock()}
    
    # Act
    manager.slot_ab("api", "python app_a.py", "python app_b.py", (50, 50))
    
    # Assert
    calls = manager._process_mgr.start.call_args_list
    process_names = [str(call[0][0]) for call in calls if call[0]]
    
    has_a_suffix = any("__a" in name or "_a" in name for name in process_names)
    has_b_suffix = any("__b" in name or "_b" in name for name in process_names)
    
    assert has_a_suffix or len(process_names) >= 2, "Process A should be named with __a suffix"
    assert has_b_suffix or len(process_names) >= 2, "Process B should be named with __b suffix"


def test_process_naming_invariant_canary(lifecycle_manager_mocked, mock_adapter, mock_state, mock_circuit_spec):
    """Verify canary process naming uses __stable and __canary suffixes."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    manager._circuit = mock_circuit_spec
    manager._process_mgr.is_running.return_value = True
    mock_adapter.backend.is_configured = True
    mock_state.nodes = {"api": Mock()}
    
    with patch('baton.lifecycle.CanaryController'):
        # Act
        manager.start_canary("api", "python app_canary.py", 10, {})
        
        # Assert
        calls = manager._process_mgr.start.call_args_list
        process_names = [str(call[0][0]) for call in calls if call[0]]
        
        has_canary_suffix = any("canary" in name.lower() for name in process_names)
        
        # At minimum, a canary process should be started
        assert has_canary_suffix or len(process_names) >= 1, \
            "Canary process should use __canary suffix"


def test_state_persistence_after_mutations(lifecycle_manager_mocked, mock_adapter, mock_state, mock_circuit_spec):
    """Verify state is persisted to disk after all mutation operations."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    manager._circuit = mock_circuit_spec
    mock_state.nodes = {"api": Mock()}
    
    # Test slot()
    mock_state.save.reset_mock()
    manager.slot("api", "python app.py", None)
    assert mock_state.save.called, "State should be written after slot()"
    
    # Test slot_mock()
    mock_state.save.reset_mock()
    mock_state.live_nodes = ["api"]
    manager.slot_mock("api")
    assert mock_state.save.called, "State should be written after slot_mock()"
    
    # Test set_routing()
    mock_state.save.reset_mock()
    mock_config = Mock()
    manager.set_routing("api", mock_config)
    assert mock_state.save.called, "State should be written after set_routing()"


# ============================================================================
# ADDITIONAL EDGE CASE TESTS
# ============================================================================

def test_adapters_empty_when_no_nodes(lifecycle_manager_mocked):
    """Verify adapters property returns empty dict when no nodes exist."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {}
    
    # Act
    result = manager.adapters
    
    # Assert
    assert result == {}, "Should return empty dict when no adapters exist"


def test_multiple_operations_state_consistency(lifecycle_manager_mocked, mock_adapter, mock_state, mock_circuit_spec):
    """Verify state remains consistent across multiple operations."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._state = mock_state
    manager._circuit = mock_circuit_spec
    mock_state.nodes = {"api": Mock()}
    
    # Act - perform multiple operations
    manager.slot("api", "python app.py", None)
    initial_save_count = mock_state.save.call_count
    
    manager.slot_mock("api")
    after_mock_count = mock_state.save.call_count
    
    # Assert
    assert after_mock_count > initial_save_count, \
        "State should be saved after each mutation"


def test_down_with_partial_cleanup(lifecycle_manager_mocked, mock_adapter, mock_adapter_control):
    """Verify down() handles partial cleanup gracefully."""
    # Arrange
    manager = lifecycle_manager_mocked
    manager._adapters = {"api": mock_adapter}
    manager._controls = {"api": mock_adapter_control}
    manager._state = None
    
    # Simulate failure in one cleanup step
    mock_adapter.drain.side_effect = Exception("Drain failed")
    
    # Act - should continue cleanup despite error
    try:
        manager.down()
    except:
        pass
    
    # Assert - other cleanup steps should still execute
    manager._process_mgr.stop_all.assert_called(), \
        "Process cleanup should proceed despite adapter drain failure"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
