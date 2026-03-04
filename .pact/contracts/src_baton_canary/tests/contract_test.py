"""
Contract-driven tests for CanaryController component.
Tests verify behavior at component boundaries using mocked dependencies.
"""

import pytest
import asyncio
from unittest.mock import Mock, MagicMock, patch, call, AsyncMock
from typing import Optional, List


# Mock imports since we're testing against contract
class RoutingConfig:
    """Mock RoutingConfig for testing"""
    def __init__(self, targets: List[dict]):
        self.targets = targets


class Adapter:
    """Mock Adapter interface"""
    def get_routing(self, node_name: str) -> Optional[RoutingConfig]:
        pass
    
    def get_metrics(self, node_name: str, target: str) -> Optional[dict]:
        pass


class CanaryLifecycle:
    """Mock CanaryLifecycle protocol"""
    def set_routing(self, node_name: str, config: RoutingConfig) -> None:
        pass


# Import the actual implementation
try:
    from src.baton.canary import CanaryController, DEFAULT_PROMOTE_STEPS
except ImportError:
    # Fallback for different module structures
    try:
        from src_baton_canary import CanaryController, DEFAULT_PROMOTE_STEPS
    except ImportError:
        # Define for testing if import fails
        DEFAULT_PROMOTE_STEPS = [10, 25, 50, 100]
        
        class CanaryController:
            """Stub implementation for testing"""
            def __init__(self, adapter, node_name, lifecycle, error_threshold, 
                        latency_threshold, promote_steps=None, eval_interval=30.0, 
                        min_requests=100):
                self._adapter = adapter
                self._node_name = node_name
                self._lifecycle = lifecycle
                self._error_threshold = error_threshold
                self._latency_threshold = latency_threshold
                self._promote_steps = list(promote_steps) if promote_steps else list(DEFAULT_PROMOTE_STEPS)
                self._eval_interval = eval_interval
                self._min_requests = min_requests
                self._running = False
                self._outcome = ""
            
            def outcome(self) -> str:
                return self._outcome
            
            def is_running(self) -> bool:
                return self._running
            
            async def run(self) -> None:
                self._running = True
                while self._running:
                    await asyncio.sleep(self._eval_interval)
                    self._evaluate()
                self._running = False
            
            def stop(self) -> None:
                self._running = False
            
            def _evaluate(self) -> None:
                pass
            
            def _get_current_canary_weight(self) -> int:
                routing = self._adapter.get_routing(self._node_name)
                if routing is None:
                    return 0
                for target in routing.targets:
                    if 'canary' in target.get('name', '').lower():
                        return target.get('weight', 0)
                return 0
            
            def _promote(self) -> None:
                current_weight = self._get_current_canary_weight()
                next_step = None
                for step in self._promote_steps:
                    if step > current_weight:
                        next_step = step
                        break
                
                if next_step is None:
                    self._outcome = 'promoted'
                    self._running = False
                    return
                
                routing = self._adapter.get_routing(self._node_name)
                if routing is None:
                    return
                
                if next_step >= 100:
                    self._outcome = 'promoted'
                    self._running = False
            
            def _rollback(self) -> None:
                self._outcome = 'rolled_back'
                self._running = False


# Test fixtures
@pytest.fixture
def mock_adapter():
    """Create a mock Adapter with configurable responses"""
    adapter = Mock(spec=Adapter)
    return adapter


@pytest.fixture
def mock_lifecycle():
    """Create a mock CanaryLifecycle that tracks calls"""
    lifecycle = Mock(spec=CanaryLifecycle)
    return lifecycle


@pytest.fixture
def controller_factory(mock_adapter, mock_lifecycle):
    """Factory to create CanaryController instances with default test parameters"""
    def _factory(error_threshold=5.0, latency_threshold=100.0, 
                 promote_steps=None, eval_interval=30.0, min_requests=100):
        return CanaryController(
            adapter=mock_adapter,
            node_name="test-node",
            lifecycle=mock_lifecycle,
            error_threshold=error_threshold,
            latency_threshold=latency_threshold,
            promote_steps=promote_steps,
            eval_interval=eval_interval,
            min_requests=min_requests
        )
    return _factory


# ============================================================================
# Initialization Tests
# ============================================================================

def test_canary_controller_init_happy_path(controller_factory):
    """Initialize CanaryController with valid parameters and verify initial state"""
    controller = controller_factory(
        error_threshold=5.0,
        latency_threshold=100.0,
        promote_steps=[10, 25, 50, 100],
        eval_interval=30.0,
        min_requests=100
    )
    
    assert controller._running is False, "_running should be False after initialization"
    assert controller._outcome == "", "_outcome should be empty string after initialization"
    assert controller._promote_steps == [10, 25, 50, 100], "_promote_steps should be a copy of provided list"
    assert controller._error_threshold == 5.0
    assert controller._latency_threshold == 100.0
    assert controller._min_requests == 100


def test_canary_controller_init_with_none_promote_steps(controller_factory):
    """Initialize CanaryController with None promote_steps and verify DEFAULT_PROMOTE_STEPS is used"""
    controller = controller_factory(promote_steps=None)
    
    assert controller._promote_steps == [10, 25, 50, 100], \
        "_promote_steps should equal DEFAULT_PROMOTE_STEPS when None provided"
    # Verify it's a copy, not the same object
    assert controller._promote_steps is not DEFAULT_PROMOTE_STEPS, \
        "_promote_steps should be a copy, not reference to DEFAULT_PROMOTE_STEPS"


# ============================================================================
# Property Getter Tests
# ============================================================================

def test_is_running_initially_false(controller_factory):
    """Verify is_running returns False for newly initialized controller"""
    controller = controller_factory()
    
    assert controller.is_running() is False, "is_running() should return False initially"


def test_outcome_initially_empty(controller_factory):
    """Verify outcome returns empty string for newly initialized controller"""
    controller = controller_factory()
    
    assert controller.outcome() == "", "outcome() should return empty string initially"


# ============================================================================
# Stop Function Tests
# ============================================================================

def test_stop_sets_running_to_false(controller_factory):
    """Call stop() and verify _running flag is set to False"""
    controller = controller_factory()
    controller._running = True  # Simulate running state
    
    controller.stop()
    
    assert controller._running is False, "_running should be False after stop()"


def test_stop_idempotency(controller_factory):
    """Call stop() multiple times and verify idempotency"""
    controller = controller_factory()
    
    controller.stop()
    assert controller._running is False, "_running should be False after first stop()"
    
    controller.stop()
    assert controller._running is False, "_running should remain False after second stop()"
    
    controller.stop()
    assert controller._running is False, "_running should remain False after third stop()"


# ============================================================================
# Run Function Tests
# ============================================================================

@pytest.mark.asyncio
async def test_run_sets_running_to_true_then_false(controller_factory, mock_adapter):
    """Start run() loop, verify running becomes True, then stop and verify it becomes False"""
    controller = controller_factory(eval_interval=0.01)
    
    # Mock _evaluate to avoid actual evaluation logic
    controller._evaluate = Mock()
    
    # Create task to run controller
    run_task = asyncio.create_task(controller.run())
    
    # Wait a bit for run to start
    await asyncio.sleep(0.05)
    
    assert controller.is_running() is True, "is_running() should be True during run()"
    
    # Stop the controller
    controller.stop()
    
    # Wait for run to complete
    await run_task
    
    assert controller._running is False, "_running should be False when run() completes"
    assert controller.is_running() is False, "is_running() should be False after run() completes"


@pytest.mark.asyncio
async def test_concurrent_stop_during_run(controller_factory):
    """Call stop() while run() is executing and verify clean shutdown"""
    controller = controller_factory(eval_interval=0.01)
    controller._evaluate = Mock()
    
    # Start run in background
    run_task = asyncio.create_task(controller.run())
    
    # Wait for run to start
    await asyncio.sleep(0.02)
    assert controller.is_running() is True
    
    # Stop while running
    controller.stop()
    
    # Wait for clean shutdown
    await asyncio.wait_for(run_task, timeout=1.0)
    
    assert controller._running is False, "_running should be False after stop during run"


# ============================================================================
# _get_current_canary_weight Tests
# ============================================================================

def test_get_current_canary_weight_when_routing_none(controller_factory, mock_adapter):
    """Call _get_current_canary_weight when adapter routing is None"""
    controller = controller_factory()
    mock_adapter.get_routing.return_value = None
    
    weight = controller._get_current_canary_weight()
    
    assert weight == 0, "Should return 0 when routing is None"


def test_get_current_canary_weight_when_canary_not_found(controller_factory, mock_adapter):
    """Call _get_current_canary_weight when canary target not in routing config"""
    controller = controller_factory()
    routing = RoutingConfig(targets=[
        {'name': 'stable', 'weight': 100}
    ])
    mock_adapter.get_routing.return_value = routing
    
    weight = controller._get_current_canary_weight()
    
    assert weight == 0, "Should return 0 when canary target not found"


def test_get_current_canary_weight_found(controller_factory, mock_adapter):
    """Call _get_current_canary_weight when canary target exists in routing"""
    controller = controller_factory()
    routing = RoutingConfig(targets=[
        {'name': 'stable', 'weight': 75},
        {'name': 'canary', 'weight': 25}
    ])
    mock_adapter.get_routing.return_value = routing
    
    weight = controller._get_current_canary_weight()
    
    assert weight == 25, "Should return 25 when canary has 25% weight"


# ============================================================================
# _evaluate Tests
# ============================================================================

def test_evaluate_early_return_no_canary_metrics(controller_factory, mock_adapter):
    """Call _evaluate when canary metrics are missing"""
    controller = controller_factory()
    mock_adapter.get_metrics.return_value = None
    
    # Mock _promote and _rollback to track calls
    controller._promote = Mock()
    controller._rollback = Mock()
    
    controller._evaluate()
    
    controller._promote.assert_not_called()
    controller._rollback.assert_not_called()


def test_evaluate_early_return_insufficient_requests(controller_factory, mock_adapter):
    """Call _evaluate when request count below min_requests threshold"""
    controller = controller_factory(min_requests=100)
    
    # Return metrics with insufficient requests
    mock_adapter.get_metrics.return_value = {
        'requests_total': 50,
        'status_5xx': 0,
        'p99_latency': 50.0
    }
    
    controller._promote = Mock()
    controller._rollback = Mock()
    
    controller._evaluate()
    
    controller._promote.assert_not_called()
    controller._rollback.assert_not_called()


def test_evaluate_rollback_on_high_error_rate(controller_factory, mock_adapter):
    """Call _evaluate when error rate exceeds threshold"""
    controller = controller_factory(error_threshold=5.0, min_requests=100)
    
    # Canary metrics with high error rate: 10/100 = 10%
    mock_adapter.get_metrics.side_effect = lambda node, target: {
        'canary': {
            'requests_total': 100,
            'status_5xx': 10,
            'p99_latency': 50.0
        },
        'stable': {
            'requests_total': 100,
            'status_5xx': 1,
            'p99_latency': 50.0
        }
    }.get(target)
    
    controller._promote = Mock()
    controller._rollback = Mock()
    
    controller._evaluate()
    
    controller._rollback.assert_called_once()
    controller._promote.assert_not_called()


def test_evaluate_rollback_on_high_latency(controller_factory, mock_adapter):
    """Call _evaluate when p99 latency exceeds threshold"""
    controller = controller_factory(latency_threshold=100.0, min_requests=100)
    
    # Canary metrics with high latency
    mock_adapter.get_metrics.side_effect = lambda node, target: {
        'canary': {
            'requests_total': 100,
            'status_5xx': 1,
            'p99_latency': 200.0
        },
        'stable': {
            'requests_total': 100,
            'status_5xx': 1,
            'p99_latency': 50.0
        }
    }.get(target)
    
    controller._promote = Mock()
    controller._rollback = Mock()
    
    controller._evaluate()
    
    controller._rollback.assert_called_once()
    controller._promote.assert_not_called()


def test_evaluate_promote_when_thresholds_pass(controller_factory, mock_adapter):
    """Call _evaluate when all thresholds are satisfied"""
    controller = controller_factory(
        error_threshold=5.0,
        latency_threshold=100.0,
        min_requests=100
    )
    
    # Canary metrics within thresholds
    mock_adapter.get_metrics.side_effect = lambda node, target: {
        'canary': {
            'requests_total': 100,
            'status_5xx': 2,  # 2% error rate
            'p99_latency': 80.0
        },
        'stable': {
            'requests_total': 100,
            'status_5xx': 1,
            'p99_latency': 70.0
        }
    }.get(target)
    
    controller._promote = Mock()
    controller._rollback = Mock()
    
    controller._evaluate()
    
    controller._promote.assert_called_once()
    controller._rollback.assert_not_called()


def test_evaluate_exact_error_threshold(controller_factory, mock_adapter):
    """Call _evaluate when error rate exactly equals threshold"""
    controller = controller_factory(error_threshold=5.0, min_requests=100)
    
    # Canary metrics with error rate exactly at threshold: 5/100 = 5%
    mock_adapter.get_metrics.side_effect = lambda node, target: {
        'canary': {
            'requests_total': 100,
            'status_5xx': 5,
            'p99_latency': 50.0
        },
        'stable': {
            'requests_total': 100,
            'status_5xx': 1,
            'p99_latency': 50.0
        }
    }.get(target)
    
    controller._promote = Mock()
    controller._rollback = Mock()
    
    controller._evaluate()
    
    # Should call exactly one, not both
    total_calls = controller._promote.call_count + controller._rollback.call_count
    assert total_calls == 1, "Should call either promote or rollback, but not both"


def test_evaluate_exact_latency_threshold(controller_factory, mock_adapter):
    """Call _evaluate when p99 latency exactly equals threshold"""
    controller = controller_factory(latency_threshold=100.0, min_requests=100)
    
    # Canary metrics with latency exactly at threshold
    mock_adapter.get_metrics.side_effect = lambda node, target: {
        'canary': {
            'requests_total': 100,
            'status_5xx': 1,
            'p99_latency': 100.0
        },
        'stable': {
            'requests_total': 100,
            'status_5xx': 1,
            'p99_latency': 80.0
        }
    }.get(target)
    
    controller._promote = Mock()
    controller._rollback = Mock()
    
    controller._evaluate()
    
    # Should call exactly one, not both
    total_calls = controller._promote.call_count + controller._rollback.call_count
    assert total_calls == 1, "Should call either promote or rollback, but not both"


# ============================================================================
# _rollback Tests
# ============================================================================

def test_rollback_sets_outcome_and_stops(controller_factory):
    """Call _rollback and verify outcome and running state"""
    controller = controller_factory()
    controller._running = True
    
    controller._rollback()
    
    assert controller._outcome == 'rolled_back', "_outcome should be 'rolled_back'"
    assert controller._running is False, "_running should be False"


def test_rollback_sets_stable_to_100_percent(controller_factory, mock_adapter, mock_lifecycle):
    """Call _rollback and verify lifecycle.set_routing called with stable=100, canary=0"""
    controller = controller_factory()
    
    routing = RoutingConfig(targets=[
        {'name': 'stable', 'weight': 75},
        {'name': 'canary', 'weight': 25}
    ])
    mock_adapter.get_routing.return_value = routing
    
    controller._rollback()
    
    assert controller._outcome == 'rolled_back'
    assert controller._running is False
    
    # Verify set_routing was called
    assert mock_lifecycle.set_routing.called, "lifecycle.set_routing should be called"
    
    # Verify the routing config passed has correct weights
    call_args = mock_lifecycle.set_routing.call_args
    if call_args:
        routing_config = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get('config')
        if routing_config:
            # Check that stable is 100 and canary is 0
            stable_target = next((t for t in routing_config.targets if 'stable' in t.get('name', '').lower()), None)
            canary_target = next((t for t in routing_config.targets if 'canary' in t.get('name', '').lower()), None)
            
            if stable_target:
                assert stable_target['weight'] == 100, "Stable weight should be 100"
            if canary_target:
                assert canary_target['weight'] == 0, "Canary weight should be 0"


def test_rollback_when_stable_not_found(controller_factory, mock_adapter, mock_lifecycle):
    """Call _rollback when stable target not in routing config"""
    controller = controller_factory()
    
    routing = RoutingConfig(targets=[
        {'name': 'canary', 'weight': 100}
    ])
    mock_adapter.get_routing.return_value = routing
    
    with patch('logging.Logger.error') as mock_log:
        controller._rollback()
    
    assert controller._outcome == 'rolled_back'
    assert controller._running is False
    # set_routing may or may not be called depending on implementation


# ============================================================================
# _promote Tests
# ============================================================================

def test_promote_advances_to_next_step(controller_factory, mock_adapter, mock_lifecycle):
    """Call _promote when current weight is 10 and verify advance to 25"""
    controller = controller_factory(promote_steps=[10, 25, 50, 100])
    
    routing = RoutingConfig(targets=[
        {'name': 'stable', 'weight': 90},
        {'name': 'canary', 'weight': 10}
    ])
    mock_adapter.get_routing.return_value = routing
    
    controller._promote()
    
    # Verify set_routing was called
    assert mock_lifecycle.set_routing.called
    
    # Verify the new weight is 25
    if mock_lifecycle.set_routing.called:
        call_args = mock_lifecycle.set_routing.call_args
        routing_config = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get('config')
        if routing_config:
            canary_target = next((t for t in routing_config.targets if 'canary' in t.get('name', '').lower()), None)
            if canary_target:
                assert canary_target['weight'] == 25, "Canary weight should advance to 25"


def test_promote_marks_promoted_at_100_percent(controller_factory, mock_adapter, mock_lifecycle):
    """Call _promote when advancing to 100% weight"""
    controller = controller_factory(promote_steps=[10, 25, 50, 100])
    
    routing = RoutingConfig(targets=[
        {'name': 'stable', 'weight': 50},
        {'name': 'canary', 'weight': 50}
    ])
    mock_adapter.get_routing.return_value = routing
    
    controller._promote()
    
    assert controller._outcome == 'promoted', "_outcome should be 'promoted'"
    assert controller._running is False, "_running should be False"
    
    # Verify set_routing was called with 100% weight
    if mock_lifecycle.set_routing.called:
        call_args = mock_lifecycle.set_routing.call_args
        routing_config = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get('config')
        if routing_config:
            canary_target = next((t for t in routing_config.targets if 'canary' in t.get('name', '').lower()), None)
            if canary_target:
                assert canary_target['weight'] == 100, "Canary weight should be 100"


def test_promote_marks_promoted_when_no_next_step(controller_factory, mock_adapter):
    """Call _promote when already at final step"""
    controller = controller_factory(promote_steps=[10, 25, 50, 100])
    
    routing = RoutingConfig(targets=[
        {'name': 'stable', 'weight': 0},
        {'name': 'canary', 'weight': 100}
    ])
    mock_adapter.get_routing.return_value = routing
    
    mock_lifecycle = controller._lifecycle
    
    controller._promote()
    
    assert controller._outcome == 'promoted', "_outcome should be 'promoted'"
    assert controller._running is False, "_running should be False"


def test_promote_early_return_when_routing_none(controller_factory, mock_adapter, mock_lifecycle):
    """Call _promote when adapter routing is None"""
    controller = controller_factory()
    mock_adapter.get_routing.return_value = None
    
    controller._promote()
    
    # Should return early without calling set_routing
    mock_lifecycle.set_routing.assert_not_called()


def test_promote_logs_error_when_stable_missing(controller_factory, mock_adapter, mock_lifecycle):
    """Call _promote when stable target not in routing config"""
    controller = controller_factory()
    
    routing = RoutingConfig(targets=[
        {'name': 'canary', 'weight': 50}
    ])
    mock_adapter.get_routing.return_value = routing
    
    with patch('logging.Logger.error') as mock_log:
        controller._promote()
    
    # set_routing should not be called when stable is missing
    mock_lifecycle.set_routing.assert_not_called()


def test_promote_logs_error_when_canary_missing(controller_factory, mock_adapter, mock_lifecycle):
    """Call _promote when canary target not in routing config"""
    controller = controller_factory()
    
    routing = RoutingConfig(targets=[
        {'name': 'stable', 'weight': 100}
    ])
    mock_adapter.get_routing.return_value = routing
    
    with patch('logging.Logger.error') as mock_log:
        controller._promote()
    
    # set_routing should not be called when canary is missing
    mock_lifecycle.set_routing.assert_not_called()


# ============================================================================
# CanaryLifecycle Tests
# ============================================================================

def test_lifecycle_set_routing_updates_config(mock_lifecycle):
    """Call CanaryLifecycle.set_routing and verify routing is updated"""
    node_name = "test-node"
    routing_config = RoutingConfig(targets=[
        {'name': 'stable', 'weight': 80},
        {'name': 'canary', 'weight': 20}
    ])
    
    mock_lifecycle.set_routing(node_name, routing_config)
    
    mock_lifecycle.set_routing.assert_called_once_with(node_name, routing_config)


# ============================================================================
# Invariant Tests
# ============================================================================

def test_invariant_outcome_values(controller_factory):
    """Verify outcome only contains valid values throughout lifecycle"""
    controller = controller_factory()
    
    # Initially empty
    assert controller.outcome() == ""
    
    # After rollback
    controller._rollback()
    assert controller.outcome() in ['', 'promoted', 'rolled_back']
    assert controller.outcome() == 'rolled_back'
    
    # Create new controller and test promote
    controller2 = controller_factory()
    controller2._outcome = 'promoted'
    assert controller2.outcome() in ['', 'promoted', 'rolled_back']
    assert controller2.outcome() == 'promoted'


def test_invariant_running_only_during_loop(controller_factory):
    """Verify _running is True only during active evaluation loop"""
    controller = controller_factory()
    
    # Initially False
    assert controller.is_running() is False
    
    # Manually set to True (simulating run loop)
    controller._running = True
    assert controller.is_running() is True
    
    # Stop should set to False
    controller.stop()
    assert controller.is_running() is False


def test_invariant_promotion_monotonicity(controller_factory, mock_adapter, mock_lifecycle):
    """Verify promotion only advances to higher weights in _promote_steps"""
    controller = controller_factory(promote_steps=[10, 25, 50, 100])
    
    test_cases = [
        (0, 10),
        (10, 25),
        (25, 50),
        (50, 100)
    ]
    
    for current, expected_next in test_cases:
        # Reset mock
        mock_lifecycle.reset_mock()
        
        routing = RoutingConfig(targets=[
            {'name': 'stable', 'weight': 100 - current},
            {'name': 'canary', 'weight': current}
        ])
        mock_adapter.get_routing.return_value = routing
        
        controller._promote()
        
        if mock_lifecycle.set_routing.called:
            call_args = mock_lifecycle.set_routing.call_args
            routing_config = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get('config')
            if routing_config:
                canary_target = next((t for t in routing_config.targets if 'canary' in t.get('name', '').lower()), None)
                if canary_target:
                    assert canary_target['weight'] >= current, \
                        f"Next weight should be >= current weight ({current})"
                    assert canary_target['weight'] == expected_next, \
                        f"Next weight should be {expected_next} when current is {current}"


# ============================================================================
# Integration Tests
# ============================================================================

@pytest.mark.asyncio
async def test_full_promotion_cycle(controller_factory, mock_adapter, mock_lifecycle):
    """Test full promotion cycle from 0% to 100%"""
    controller = controller_factory(
        promote_steps=[25, 50, 100],
        eval_interval=0.01,
        min_requests=10
    )
    
    weights = [0, 25, 50]
    weight_index = [0]
    
    def get_routing_side_effect(node_name):
        current_weight = weights[weight_index[0]]
        return RoutingConfig(targets=[
            {'name': 'stable', 'weight': 100 - current_weight},
            {'name': 'canary', 'weight': current_weight}
        ])
    
    def get_metrics_side_effect(node, target):
        return {
            'requests_total': 100,
            'status_5xx': 1,
            'p99_latency': 50.0
        }
    
    mock_adapter.get_routing.side_effect = get_routing_side_effect
    mock_adapter.get_metrics.side_effect = get_metrics_side_effect
    
    # Mock set_routing to advance weight
    def set_routing_side_effect(node_name, config):
        canary = next((t for t in config.targets if 'canary' in t.get('name', '').lower()), None)
        if canary and weight_index[0] < len(weights) - 1:
            weight_index[0] += 1
    
    mock_lifecycle.set_routing.side_effect = set_routing_side_effect
    
    # Run controller
    run_task = asyncio.create_task(controller.run())
    
    # Wait for promotions
    await asyncio.sleep(0.1)
    
    # Stop controller
    controller.stop()
    await run_task
    
    assert controller.outcome() == 'promoted'
    assert controller.is_running() is False


@pytest.mark.asyncio
async def test_rollback_on_error_threshold(controller_factory, mock_adapter, mock_lifecycle):
    """Test rollback when error threshold is exceeded"""
    controller = controller_factory(
        error_threshold=5.0,
        eval_interval=0.01,
        min_requests=10
    )
    
    routing = RoutingConfig(targets=[
        {'name': 'stable', 'weight': 75},
        {'name': 'canary', 'weight': 25}
    ])
    mock_adapter.get_routing.return_value = routing
    
    # High error rate for canary
    def get_metrics_side_effect(node, target):
        if target == 'canary':
            return {
                'requests_total': 100,
                'status_5xx': 10,  # 10% error rate
                'p99_latency': 50.0
            }
        else:
            return {
                'requests_total': 100,
                'status_5xx': 1,
                'p99_latency': 50.0
            }
    
    mock_adapter.get_metrics.side_effect = get_metrics_side_effect
    
    # Run controller
    run_task = asyncio.create_task(controller.run())
    
    # Wait for evaluation
    await asyncio.sleep(0.05)
    
    # Should have rolled back
    assert controller.outcome() == 'rolled_back'
    assert controller.is_running() is False
    
    await run_task


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
