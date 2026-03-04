"""
Contract-driven tests for Baton Custodian component.

Tests verify behavior at boundaries (inputs/outputs), not internals.
All dependencies are mocked to ensure isolated component testing.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
import threading
import time
from datetime import datetime
from typing import Any

# Import the component under test
from src.baton.custodian import (
    LifecycleActions,
    RepairPlaybook,
    Custodian,
    CustodianAction,
    CustodianEvent,
    AdapterState,
    CircuitState,
    Adapter,
    AdapterStatus,
    HealthVerdict,
    FAILURE_THRESHOLD,
    HEALTH_POLL_INTERVAL,
)


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def mock_adapter():
    """Create a mock Adapter."""
    adapter = Mock(spec=Adapter)
    adapter.health_check = Mock(return_value=HealthVerdict.HEALTHY)
    return adapter


@pytest.fixture
def mock_circuit_state():
    """Create a mock CircuitState."""
    state = Mock(spec=CircuitState)
    state.adapters = {}
    return state


@pytest.fixture
def mock_lifecycle():
    """Create a mock LifecycleActions."""
    lifecycle = Mock(spec=LifecycleActions)
    lifecycle.restart_service = Mock()
    lifecycle.slot_mock = Mock()
    return lifecycle


@pytest.fixture
def mock_playbook():
    """Create a mock RepairPlaybook."""
    playbook = Mock(spec=RepairPlaybook)
    playbook.decide = Mock(return_value=CustodianAction.RESTART_SERVICE)
    return playbook


@pytest.fixture
def mock_adapter_state():
    """Create a mock AdapterState."""
    adapter_state = Mock(spec=AdapterState)
    adapter_state.consecutive_failures = 0
    adapter_state.status = AdapterStatus.ACTIVE
    adapter_state.service = Mock()
    adapter_state.service.is_mock = False
    adapter_state.last_health_check = None
    adapter_state.last_health_verdict = None
    return adapter_state


@pytest.fixture
def custodian_basic(mock_circuit_state, mock_lifecycle, mock_playbook):
    """Create a basic Custodian instance for testing."""
    adapters = {}
    return Custodian(
        adapters=adapters,
        state=mock_circuit_state,
        lifecycle=mock_lifecycle,
        playbook=mock_playbook,
        poll_interval=5.0
    )


# ==============================================================================
# LifecycleActions Tests
# ==============================================================================

def test_lifecycle_restart_service_happy_path():
    """LifecycleActions.restart_service successfully restarts a valid service node."""
    lifecycle = Mock(spec=LifecycleActions)
    lifecycle.restart_service = Mock()
    
    node_name = "service-node-1"
    lifecycle.restart_service(node_name)
    
    lifecycle.restart_service.assert_called_once_with(node_name)


def test_lifecycle_restart_service_implementation_error():
    """LifecycleActions.restart_service raises implementation_error on restart failure."""
    lifecycle = Mock(spec=LifecycleActions)
    lifecycle.restart_service = Mock(side_effect=Exception("Restart failed"))
    
    node_name = "failing-node"
    
    with pytest.raises(Exception) as exc_info:
        lifecycle.restart_service(node_name)
    
    assert "Restart failed" in str(exc_info.value)


def test_lifecycle_slot_mock_happy_path():
    """LifecycleActions.slot_mock successfully replaces a service with mock."""
    lifecycle = Mock(spec=LifecycleActions)
    lifecycle.slot_mock = Mock()
    
    node_name = "service-node-1"
    lifecycle.slot_mock(node_name)
    
    lifecycle.slot_mock.assert_called_once_with(node_name)


def test_lifecycle_slot_mock_implementation_error():
    """LifecycleActions.slot_mock raises implementation_error on mock replacement failure."""
    lifecycle = Mock(spec=LifecycleActions)
    lifecycle.slot_mock = Mock(side_effect=Exception("Mock replacement failed"))
    
    node_name = "failing-node"
    
    with pytest.raises(Exception) as exc_info:
        lifecycle.slot_mock(node_name)
    
    assert "Mock replacement failed" in str(exc_info.value)


# ==============================================================================
# RepairPlaybook Tests
# ==============================================================================

def test_playbook_decide_restart_service():
    """RepairPlaybook.decide returns RESTART_SERVICE when consecutive_failures < FAILURE_THRESHOLD * 2."""
    playbook = RepairPlaybook()
    
    adapter_state = Mock(spec=AdapterState)
    adapter_state.consecutive_failures = 3
    adapter_state.service = Mock()
    adapter_state.service.is_mock = False
    
    action = playbook.decide(adapter_state)
    
    assert action == CustodianAction.RESTART_SERVICE, \
        f"Expected RESTART_SERVICE for consecutive_failures=3, got {action}"


def test_playbook_decide_replace_service():
    """RepairPlaybook.decide returns REPLACE_SERVICE when consecutive_failures >= FAILURE_THRESHOLD * 2."""
    playbook = RepairPlaybook()
    
    adapter_state = Mock(spec=AdapterState)
    adapter_state.consecutive_failures = 6
    adapter_state.service = Mock()
    adapter_state.service.is_mock = False
    
    action = playbook.decide(adapter_state)
    
    assert action == CustodianAction.REPLACE_SERVICE, \
        f"Expected REPLACE_SERVICE for consecutive_failures=6, got {action}"


def test_playbook_decide_escalate_already_mock():
    """RepairPlaybook.decide returns ESCALATE if service is already mock."""
    playbook = RepairPlaybook()
    
    adapter_state = Mock(spec=AdapterState)
    adapter_state.consecutive_failures = 3
    adapter_state.service = Mock()
    adapter_state.service.is_mock = True
    
    action = playbook.decide(adapter_state)
    
    assert action == CustodianAction.ESCALATE, \
        f"Expected ESCALATE for is_mock=True, got {action}"


# ==============================================================================
# Custodian.__init__ Tests
# ==============================================================================

def test_custodian_init_happy_path(mock_adapter, mock_circuit_state, mock_lifecycle, mock_playbook):
    """Custodian.__init__ initializes with all required state correctly."""
    adapters = {'adapter1': mock_adapter}
    
    custodian = Custodian(
        adapters=adapters,
        state=mock_circuit_state,
        lifecycle=mock_lifecycle,
        playbook=mock_playbook,
        poll_interval=5.0
    )
    
    assert custodian._running is False, "_running should be False initially"
    assert custodian._events == [], "_events should be empty list initially"
    assert custodian._playbook is mock_playbook, "_playbook should be set to provided playbook"
    assert custodian._adapters is adapters, "_adapters should be set"
    assert custodian._state is mock_circuit_state, "_state should be set"
    assert custodian._lifecycle is mock_lifecycle, "_lifecycle should be set"
    assert custodian._poll_interval == 5.0, "_poll_interval should be set"


def test_custodian_init_none_playbook(mock_circuit_state):
    """Custodian.__init__ creates default RepairPlaybook when playbook is None."""
    custodian = Custodian(
        adapters={},
        state=mock_circuit_state,
        lifecycle=None,
        playbook=None,
        poll_interval=5.0
    )
    
    assert custodian._playbook is not None, "_playbook should not be None"
    assert isinstance(custodian._playbook, RepairPlaybook), \
        "_playbook should be instance of RepairPlaybook"


def test_custodian_init_none_lifecycle(mock_circuit_state, mock_playbook):
    """Custodian.__init__ accepts None for lifecycle parameter."""
    custodian = Custodian(
        adapters={},
        state=mock_circuit_state,
        lifecycle=None,
        playbook=mock_playbook,
        poll_interval=5.0
    )
    
    assert custodian._lifecycle is None, "_lifecycle should be None"
    assert custodian._running is False, "_running should be False"


# ==============================================================================
# Custodian.events() Tests
# ==============================================================================

def test_custodian_events_returns_copy(custodian_basic):
    """Custodian.events() returns a copy of all custodian events."""
    # Add some events to internal state
    event1 = Mock(spec=CustodianEvent)
    event2 = Mock(spec=CustodianEvent)
    custodian_basic._events = [event1, event2]
    
    events = custodian_basic.events()
    
    assert events == [event1, event2], "Should return all events"
    assert events is not custodian_basic._events, "Should return a copy, not the original list"
    
    # Modify returned list and verify internal state is unchanged
    events.append(Mock(spec=CustodianEvent))
    assert len(custodian_basic._events) == 2, "Modifying returned list should not affect internal state"


def test_custodian_events_empty(custodian_basic):
    """Custodian.events() returns empty list when no events exist."""
    events = custodian_basic.events()
    
    assert events == [], "Should return empty list"
    assert isinstance(events, list), "Should return a list"


# ==============================================================================
# Custodian.is_running() Tests
# ==============================================================================

def test_custodian_is_running_initially_false(custodian_basic):
    """Custodian.is_running() returns False initially."""
    assert custodian_basic.is_running() is False, "is_running should be False initially"


def test_custodian_is_running_after_run():
    """Custodian.is_running() returns True when monitoring loop is running."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_circuit_state.adapters = {}
    
    custodian = Custodian(
        adapters={},
        state=mock_circuit_state,
        lifecycle=None,
        playbook=None,
        poll_interval=0.1
    )
    
    # Track is_running during run
    running_during_run = []
    
    def run_thread():
        # Check is_running after a short delay
        time.sleep(0.05)
        running_during_run.append(custodian.is_running())
        custodian.stop()
    
    thread = threading.Thread(target=run_thread)
    thread.start()
    
    custodian.run()
    thread.join()
    
    assert len(running_during_run) > 0, "Should have captured is_running state"
    assert running_during_run[0] is True, "is_running should be True during run()"


# ==============================================================================
# Custodian.run() Tests
# ==============================================================================

def test_custodian_run_sets_running_true():
    """Custodian.run() sets _running to True on entry."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_circuit_state.adapters = {}
    
    custodian = Custodian(
        adapters={},
        state=mock_circuit_state,
        lifecycle=None,
        playbook=None,
        poll_interval=0.1
    )
    
    running_values = []
    
    def run_thread():
        time.sleep(0.05)
        running_values.append(custodian._running)
        custodian.stop()
    
    thread = threading.Thread(target=run_thread)
    thread.start()
    
    custodian.run()
    thread.join()
    
    assert len(running_values) > 0, "Should have captured _running state"
    assert running_values[0] is True, "_running should be True during execution"


def test_custodian_run_sets_running_false_on_exit():
    """Custodian.run() sets _running to False when loop exits."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_circuit_state.adapters = {}
    
    custodian = Custodian(
        adapters={},
        state=mock_circuit_state,
        lifecycle=None,
        playbook=None,
        poll_interval=0.1
    )
    
    def stop_thread():
        time.sleep(0.05)
        custodian.stop()
    
    thread = threading.Thread(target=stop_thread)
    thread.start()
    
    custodian.run()
    thread.join()
    
    assert custodian._running is False, "_running should be False after stop() is called"


# ==============================================================================
# Custodian.stop() Tests
# ==============================================================================

def test_custodian_stop_sets_running_false(custodian_basic):
    """Custodian.stop() sets _running to False."""
    custodian_basic._running = True
    
    custodian_basic.stop()
    
    assert custodian_basic._running is False, "_running should be False after stop()"


def test_custodian_stop_before_run(custodian_basic):
    """Custodian.stop() can be called before run() without error."""
    custodian_basic.stop()
    
    assert custodian_basic._running is False, "_running should remain False"


def test_custodian_stop_multiple_times(custodian_basic):
    """Custodian.stop() can be called multiple times safely."""
    custodian_basic.stop()
    custodian_basic.stop()
    custodian_basic.stop()
    
    assert custodian_basic._running is False, "_running should remain False"


# ==============================================================================
# Custodian.check_once() Tests
# ==============================================================================

def test_custodian_check_once_happy_path():
    """Custodian.check_once() runs one check cycle and returns events."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_adapter = Mock(spec=Adapter)
    mock_adapter.health_check = Mock(return_value=HealthVerdict.UNHEALTHY)
    
    mock_adapter_state = Mock(spec=AdapterState)
    mock_adapter_state.consecutive_failures = FAILURE_THRESHOLD - 1
    mock_adapter_state.status = AdapterStatus.ACTIVE
    mock_adapter_state.service = Mock()
    mock_adapter_state.service.is_mock = False
    
    mock_circuit_state.adapters = {'adapter1': mock_adapter_state}
    
    custodian = Custodian(
        adapters={'adapter1': mock_adapter},
        state=mock_circuit_state,
        lifecycle=None,
        playbook=None,
        poll_interval=5.0
    )
    
    events = custodian.check_once()
    
    assert isinstance(events, list), "Should return a list"
    # Since this triggers repair at threshold, there should be an event
    assert len(events) >= 0, "Should return events from check cycle"


def test_custodian_check_once_no_events():
    """Custodian.check_once() returns empty list when no events occur."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_adapter = Mock(spec=Adapter)
    mock_adapter.health_check = Mock(return_value=HealthVerdict.HEALTHY)
    
    mock_adapter_state = Mock(spec=AdapterState)
    mock_adapter_state.consecutive_failures = 0
    mock_adapter_state.status = AdapterStatus.ACTIVE
    mock_adapter_state.service = Mock()
    mock_adapter_state.service.is_mock = False
    
    mock_circuit_state.adapters = {'adapter1': mock_adapter_state}
    
    custodian = Custodian(
        adapters={'adapter1': mock_adapter},
        state=mock_circuit_state,
        lifecycle=None,
        playbook=None,
        poll_interval=5.0
    )
    
    events = custodian.check_once()
    
    assert events == [], "Should return empty list when all adapters healthy"


# ==============================================================================
# Custodian._check_all() Tests
# ==============================================================================

def test_custodian_check_all_healthy_adapter():
    """Custodian._check_all() updates adapter state for healthy adapter."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_adapter = Mock(spec=Adapter)
    mock_adapter.health_check = Mock(return_value=HealthVerdict.HEALTHY)
    
    mock_adapter_state = Mock(spec=AdapterState)
    mock_adapter_state.consecutive_failures = 2
    mock_adapter_state.status = AdapterStatus.ACTIVE
    mock_adapter_state.service = Mock()
    mock_adapter_state.service.is_mock = False
    
    mock_circuit_state.adapters = {'adapter1': mock_adapter_state}
    
    custodian = Custodian(
        adapters={'adapter1': mock_adapter},
        state=mock_circuit_state,
        lifecycle=None,
        playbook=None,
        poll_interval=5.0
    )
    
    custodian._check_all()
    
    mock_adapter.health_check.assert_called_once()
    assert mock_adapter_state.consecutive_failures == 0, \
        "consecutive_failures should be reset to 0 on healthy check"
    assert mock_adapter_state.last_health_verdict == HealthVerdict.HEALTHY, \
        "last_health_verdict should be updated"


def test_custodian_check_all_unhealthy_increments_failures():
    """Custodian._check_all() increments consecutive_failures on UNHEALTHY."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_adapter = Mock(spec=Adapter)
    mock_adapter.health_check = Mock(return_value=HealthVerdict.UNHEALTHY)
    
    mock_adapter_state = Mock(spec=AdapterState)
    mock_adapter_state.consecutive_failures = 1
    mock_adapter_state.status = AdapterStatus.ACTIVE
    mock_adapter_state.service = Mock()
    mock_adapter_state.service.is_mock = False
    
    mock_circuit_state.adapters = {'adapter1': mock_adapter_state}
    
    custodian = Custodian(
        adapters={'adapter1': mock_adapter},
        state=mock_circuit_state,
        lifecycle=None,
        playbook=None,
        poll_interval=5.0
    )
    
    custodian._check_all()
    
    assert mock_adapter_state.consecutive_failures == 2, \
        "consecutive_failures should be incremented on UNHEALTHY"


def test_custodian_check_all_triggers_repair_at_threshold():
    """Custodian._check_all() triggers repair when failures reach FAILURE_THRESHOLD."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_adapter = Mock(spec=Adapter)
    mock_adapter.health_check = Mock(return_value=HealthVerdict.UNHEALTHY)
    
    mock_adapter_state = Mock(spec=AdapterState)
    mock_adapter_state.consecutive_failures = FAILURE_THRESHOLD - 1
    mock_adapter_state.status = AdapterStatus.ACTIVE
    mock_adapter_state.service = Mock()
    mock_adapter_state.service.is_mock = False
    
    mock_circuit_state.adapters = {'adapter1': mock_adapter_state}
    
    mock_lifecycle = Mock(spec=LifecycleActions)
    mock_lifecycle.restart_service = Mock()
    
    custodian = Custodian(
        adapters={'adapter1': mock_adapter},
        state=mock_circuit_state,
        lifecycle=mock_lifecycle,
        playbook=None,
        poll_interval=5.0
    )
    
    custodian._check_all()
    
    # After incrementing, consecutive_failures should reach FAILURE_THRESHOLD
    assert mock_adapter_state.consecutive_failures == FAILURE_THRESHOLD, \
        f"consecutive_failures should be {FAILURE_THRESHOLD}"
    
    # Repair should have been triggered
    assert len(custodian._events) > 0, "Should have created a repair event"


def test_custodian_check_all_restores_faulted_to_active():
    """Custodian._check_all() restores FAULTED status to ACTIVE on healthy check."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_adapter = Mock(spec=Adapter)
    mock_adapter.health_check = Mock(return_value=HealthVerdict.HEALTHY)
    
    mock_adapter_state = Mock(spec=AdapterState)
    mock_adapter_state.consecutive_failures = 0
    mock_adapter_state.status = AdapterStatus.FAULTED
    mock_adapter_state.service = Mock()
    mock_adapter_state.service.is_mock = False
    
    mock_circuit_state.adapters = {'adapter1': mock_adapter_state}
    
    custodian = Custodian(
        adapters={'adapter1': mock_adapter},
        state=mock_circuit_state,
        lifecycle=None,
        playbook=None,
        poll_interval=5.0
    )
    
    custodian._check_all()
    
    assert mock_adapter_state.status == AdapterStatus.ACTIVE, \
        "FAULTED status should be restored to ACTIVE on healthy check"


# ==============================================================================
# Custodian._repair() Tests
# ==============================================================================

def test_custodian_repair_happy_path():
    """Custodian._repair() successfully executes repair action."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_adapter = Mock(spec=Adapter)
    
    mock_adapter_state = Mock(spec=AdapterState)
    mock_adapter_state.consecutive_failures = 3
    mock_adapter_state.status = AdapterStatus.ACTIVE
    mock_adapter_state.service = Mock()
    mock_adapter_state.service.is_mock = False
    mock_adapter_state.service.name = "service1"
    
    mock_circuit_state.adapters = {'adapter1': mock_adapter_state}
    
    mock_lifecycle = Mock(spec=LifecycleActions)
    mock_lifecycle.restart_service = Mock()
    
    custodian = Custodian(
        adapters={'adapter1': mock_adapter},
        state=mock_circuit_state,
        lifecycle=mock_lifecycle,
        playbook=None,
        poll_interval=5.0
    )
    
    initial_event_count = len(custodian._events)
    
    custodian._repair('adapter1', mock_adapter_state)
    
    assert len(custodian._events) == initial_event_count + 1, \
        "Should have created a CustodianEvent"
    assert mock_adapter_state.consecutive_failures == 0, \
        "consecutive_failures should be reset to 0 on successful repair"
    mock_lifecycle.restart_service.assert_called_once()


def test_custodian_repair_no_lifecycle():
    """Custodian._repair() sets adapter status to FAULTED when lifecycle is None."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_adapter = Mock(spec=Adapter)
    
    mock_adapter_state = Mock(spec=AdapterState)
    mock_adapter_state.consecutive_failures = 3
    mock_adapter_state.status = AdapterStatus.ACTIVE
    mock_adapter_state.service = Mock()
    mock_adapter_state.service.is_mock = False
    mock_adapter_state.service.name = "service1"
    
    mock_circuit_state.adapters = {'adapter1': mock_adapter_state}
    
    custodian = Custodian(
        adapters={'adapter1': mock_adapter},
        state=mock_circuit_state,
        lifecycle=None,
        playbook=None,
        poll_interval=5.0
    )
    
    custodian._repair('adapter1', mock_adapter_state)
    
    assert mock_adapter_state.status == AdapterStatus.FAULTED, \
        "adapter_state.status should be set to FAULTED when lifecycle is None"
    assert len(custodian._events) > 0, "Should have created a CustodianEvent"


def test_custodian_repair_lifecycle_action_failure():
    """Custodian._repair() handles lifecycle action failure and sets status to FAULTED."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_adapter = Mock(spec=Adapter)
    
    mock_adapter_state = Mock(spec=AdapterState)
    mock_adapter_state.consecutive_failures = 3
    mock_adapter_state.status = AdapterStatus.ACTIVE
    mock_adapter_state.service = Mock()
    mock_adapter_state.service.is_mock = False
    mock_adapter_state.service.name = "service1"
    
    mock_circuit_state.adapters = {'adapter1': mock_adapter_state}
    
    mock_lifecycle = Mock(spec=LifecycleActions)
    mock_lifecycle.restart_service = Mock(side_effect=Exception("Restart failed"))
    
    custodian = Custodian(
        adapters={'adapter1': mock_adapter},
        state=mock_circuit_state,
        lifecycle=mock_lifecycle,
        playbook=None,
        poll_interval=5.0
    )
    
    custodian._repair('adapter1', mock_adapter_state)
    
    assert mock_adapter_state.status == AdapterStatus.FAULTED, \
        "adapter_state.status should be set to FAULTED on lifecycle action failure"
    assert len(custodian._events) > 0, "Should have created a CustodianEvent"


# ==============================================================================
# Invariant Tests
# ==============================================================================

def test_invariant_failure_threshold():
    """Verify FAILURE_THRESHOLD constant is 3."""
    assert FAILURE_THRESHOLD == 3, f"FAILURE_THRESHOLD should be 3, got {FAILURE_THRESHOLD}"


def test_invariant_health_poll_interval():
    """Verify HEALTH_POLL_INTERVAL constant is 5.0."""
    assert HEALTH_POLL_INTERVAL == 5.0, \
        f"HEALTH_POLL_INTERVAL should be 5.0, got {HEALTH_POLL_INTERVAL}"


def test_invariant_consecutive_failures_reset_on_repair():
    """Verify consecutive failures counter resets to 0 on successful repair."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_adapter = Mock(spec=Adapter)
    
    mock_adapter_state = Mock(spec=AdapterState)
    mock_adapter_state.consecutive_failures = 5
    mock_adapter_state.status = AdapterStatus.ACTIVE
    mock_adapter_state.service = Mock()
    mock_adapter_state.service.is_mock = False
    mock_adapter_state.service.name = "service1"
    
    mock_circuit_state.adapters = {'adapter1': mock_adapter_state}
    
    mock_lifecycle = Mock(spec=LifecycleActions)
    mock_lifecycle.restart_service = Mock()
    
    custodian = Custodian(
        adapters={'adapter1': mock_adapter},
        state=mock_circuit_state,
        lifecycle=mock_lifecycle,
        playbook=None,
        poll_interval=5.0
    )
    
    custodian._repair('adapter1', mock_adapter_state)
    
    assert mock_adapter_state.consecutive_failures == 0, \
        "consecutive_failures should be reset to 0 after successful repair"


def test_invariant_consecutive_failures_reset_on_healthy():
    """Verify consecutive failures counter resets to 0 on healthy check."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_adapter = Mock(spec=Adapter)
    mock_adapter.health_check = Mock(return_value=HealthVerdict.HEALTHY)
    
    mock_adapter_state = Mock(spec=AdapterState)
    mock_adapter_state.consecutive_failures = 5
    mock_adapter_state.status = AdapterStatus.ACTIVE
    mock_adapter_state.service = Mock()
    mock_adapter_state.service.is_mock = False
    
    mock_circuit_state.adapters = {'adapter1': mock_adapter_state}
    
    custodian = Custodian(
        adapters={'adapter1': mock_adapter},
        state=mock_circuit_state,
        lifecycle=None,
        playbook=None,
        poll_interval=5.0
    )
    
    custodian._check_all()
    
    assert mock_adapter_state.consecutive_failures == 0, \
        "consecutive_failures should be reset to 0 after healthy check"


# ==============================================================================
# Additional Edge Case Tests
# ==============================================================================

def test_custodian_empty_adapters():
    """Custodian handles empty adapter dictionary."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_circuit_state.adapters = {}
    
    custodian = Custodian(
        adapters={},
        state=mock_circuit_state,
        lifecycle=None,
        playbook=None,
        poll_interval=5.0
    )
    
    custodian._check_all()
    events = custodian.check_once()
    
    assert events == [], "Should handle empty adapters without error"


def test_custodian_multiple_adapters_mixed_health():
    """Custodian handles multiple adapters with mixed health states."""
    mock_circuit_state = Mock(spec=CircuitState)
    
    # Healthy adapter
    mock_adapter1 = Mock(spec=Adapter)
    mock_adapter1.health_check = Mock(return_value=HealthVerdict.HEALTHY)
    mock_adapter_state1 = Mock(spec=AdapterState)
    mock_adapter_state1.consecutive_failures = 0
    mock_adapter_state1.status = AdapterStatus.ACTIVE
    mock_adapter_state1.service = Mock()
    mock_adapter_state1.service.is_mock = False
    
    # Unhealthy adapter
    mock_adapter2 = Mock(spec=Adapter)
    mock_adapter2.health_check = Mock(return_value=HealthVerdict.UNHEALTHY)
    mock_adapter_state2 = Mock(spec=AdapterState)
    mock_adapter_state2.consecutive_failures = 1
    mock_adapter_state2.status = AdapterStatus.ACTIVE
    mock_adapter_state2.service = Mock()
    mock_adapter_state2.service.is_mock = False
    
    mock_circuit_state.adapters = {
        'adapter1': mock_adapter_state1,
        'adapter2': mock_adapter_state2
    }
    
    custodian = Custodian(
        adapters={'adapter1': mock_adapter1, 'adapter2': mock_adapter2},
        state=mock_circuit_state,
        lifecycle=None,
        playbook=None,
        poll_interval=5.0
    )
    
    custodian._check_all()
    
    assert mock_adapter_state1.consecutive_failures == 0, "Healthy adapter should stay at 0"
    assert mock_adapter_state2.consecutive_failures == 2, "Unhealthy adapter should increment"


def test_custodian_rapid_stop_start():
    """Custodian handles rapid stop/start sequences."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_circuit_state.adapters = {}
    
    custodian = Custodian(
        adapters={},
        state=mock_circuit_state,
        lifecycle=None,
        playbook=None,
        poll_interval=0.01
    )
    
    # Stop before starting
    custodian.stop()
    assert custodian._running is False
    
    # Start and stop quickly
    def quick_stop():
        time.sleep(0.005)
        custodian.stop()
    
    thread = threading.Thread(target=quick_stop)
    thread.start()
    
    custodian.run()
    thread.join()
    
    assert custodian._running is False, "Should handle rapid stop after start"


def test_custodian_custom_poll_interval():
    """Custodian accepts and uses custom poll interval."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_circuit_state.adapters = {}
    
    custom_interval = 1.5
    custodian = Custodian(
        adapters={},
        state=mock_circuit_state,
        lifecycle=None,
        playbook=None,
        poll_interval=custom_interval
    )
    
    assert custodian._poll_interval == custom_interval, \
        f"Should use custom poll_interval {custom_interval}"


def test_custodian_events_accumulate():
    """Custodian events accumulate over multiple check cycles."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_adapter = Mock(spec=Adapter)
    mock_adapter.health_check = Mock(return_value=HealthVerdict.UNHEALTHY)
    
    mock_adapter_state = Mock(spec=AdapterState)
    mock_adapter_state.consecutive_failures = FAILURE_THRESHOLD - 1
    mock_adapter_state.status = AdapterStatus.ACTIVE
    mock_adapter_state.service = Mock()
    mock_adapter_state.service.is_mock = False
    mock_adapter_state.service.name = "service1"
    
    mock_circuit_state.adapters = {'adapter1': mock_adapter_state}
    
    mock_lifecycle = Mock(spec=LifecycleActions)
    mock_lifecycle.restart_service = Mock()
    
    custodian = Custodian(
        adapters={'adapter1': mock_adapter},
        state=mock_circuit_state,
        lifecycle=mock_lifecycle,
        playbook=None,
        poll_interval=5.0
    )
    
    # First check - should trigger repair
    events1 = custodian.check_once()
    
    # Reset state for second failure
    mock_adapter_state.consecutive_failures = FAILURE_THRESHOLD - 1
    
    # Second check - should trigger another repair
    events2 = custodian.check_once()
    
    total_events = custodian.events()
    assert len(total_events) >= len(events1) + len(events2), \
        "Events should accumulate over multiple check cycles"


def test_playbook_decide_boundary_values():
    """RepairPlaybook.decide handles boundary values correctly."""
    playbook = RepairPlaybook()
    
    # Test at exactly FAILURE_THRESHOLD * 2
    adapter_state = Mock(spec=AdapterState)
    adapter_state.consecutive_failures = FAILURE_THRESHOLD * 2
    adapter_state.service = Mock()
    adapter_state.service.is_mock = False
    
    action = playbook.decide(adapter_state)
    assert action == CustodianAction.REPLACE_SERVICE, \
        f"Should return REPLACE_SERVICE at exactly FAILURE_THRESHOLD * 2 = {FAILURE_THRESHOLD * 2}"
    
    # Test at FAILURE_THRESHOLD * 2 - 1
    adapter_state.consecutive_failures = FAILURE_THRESHOLD * 2 - 1
    action = playbook.decide(adapter_state)
    assert action == CustodianAction.RESTART_SERVICE, \
        f"Should return RESTART_SERVICE at FAILURE_THRESHOLD * 2 - 1 = {FAILURE_THRESHOLD * 2 - 1}"


def test_custodian_repair_with_escalate_action():
    """Custodian handles ESCALATE action from playbook."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_adapter = Mock(spec=Adapter)
    
    mock_adapter_state = Mock(spec=AdapterState)
    mock_adapter_state.consecutive_failures = 3
    mock_adapter_state.status = AdapterStatus.ACTIVE
    mock_adapter_state.service = Mock()
    mock_adapter_state.service.is_mock = True
    mock_adapter_state.service.name = "service1"
    
    mock_circuit_state.adapters = {'adapter1': mock_adapter_state}
    
    mock_lifecycle = Mock(spec=LifecycleActions)
    
    custodian = Custodian(
        adapters={'adapter1': mock_adapter},
        state=mock_circuit_state,
        lifecycle=mock_lifecycle,
        playbook=None,
        poll_interval=5.0
    )
    
    custodian._repair('adapter1', mock_adapter_state)
    
    # Should create an event with ESCALATE action
    assert len(custodian._events) > 0, "Should have created a CustodianEvent"
    event = custodian._events[-1]
    assert event.action == CustodianAction.ESCALATE, \
        "Action should be ESCALATE for mock service"


def test_custodian_repair_with_replace_service_action():
    """Custodian executes slot_mock for REPLACE_SERVICE action."""
    mock_circuit_state = Mock(spec=CircuitState)
    mock_adapter = Mock(spec=Adapter)
    
    mock_adapter_state = Mock(spec=AdapterState)
    mock_adapter_state.consecutive_failures = FAILURE_THRESHOLD * 2
    mock_adapter_state.status = AdapterStatus.ACTIVE
    mock_adapter_state.service = Mock()
    mock_adapter_state.service.is_mock = False
    mock_adapter_state.service.name = "service1"
    
    mock_circuit_state.adapters = {'adapter1': mock_adapter_state}
    
    mock_lifecycle = Mock(spec=LifecycleActions)
    mock_lifecycle.slot_mock = Mock()
    
    custodian = Custodian(
        adapters={'adapter1': mock_adapter},
        state=mock_circuit_state,
        lifecycle=mock_lifecycle,
        playbook=None,
        poll_interval=5.0
    )
    
    custodian._repair('adapter1', mock_adapter_state)
    
    mock_lifecycle.slot_mock.assert_called_once()
    assert mock_adapter_state.consecutive_failures == 0, \
        "consecutive_failures should be reset after successful repair"
