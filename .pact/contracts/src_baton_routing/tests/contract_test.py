"""
Contract-based tests for baton.routing module.
Tests verify routing configuration builders against contract specifications.

All dependencies are mocked. Tests verify outputs, not internals.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import sys

# Mock the baton.schemas module before importing the component
mock_schemas = MagicMock()

# Define mock types for RoutingConfig, RoutingTarget, RoutingRule, RoutingStrategy
class MockRoutingStrategy:
    WEIGHTED = "WEIGHTED"
    CANARY = "CANARY"
    HEADER = "HEADER"

class MockRoutingTarget:
    def __init__(self, name, host, port, weight=None):
        self.name = name
        self.host = host
        self.port = port
        self.weight = weight
    
    def __eq__(self, other):
        if not isinstance(other, MockRoutingTarget):
            return False
        return (self.name == other.name and 
                self.host == other.host and 
                self.port == other.port and 
                self.weight == other.weight)
    
    def __repr__(self):
        return f"RoutingTarget(name={self.name}, host={self.host}, port={self.port}, weight={self.weight})"

class MockRoutingRule:
    def __init__(self, header, value, target):
        self.header = header
        self.value = value
        self.target = target
    
    def __eq__(self, other):
        if not isinstance(other, MockRoutingRule):
            return False
        return (self.header == other.header and 
                self.value == other.value and 
                self.target == other.target)
    
    def __repr__(self):
        return f"RoutingRule(header={self.header}, value={self.value}, target={self.target})"

class MockRoutingConfig:
    def __init__(self, strategy=None, targets=None, rules=None, default_target=None):
        self.strategy = strategy
        self.targets = targets or []
        self.rules = rules or []
        self.default_target = default_target
    
    def __eq__(self, other):
        if not isinstance(other, MockRoutingConfig):
            return False
        return (self.strategy == other.strategy and 
                self.targets == other.targets and 
                self.rules == other.rules and 
                self.default_target == other.default_target)
    
    def __repr__(self):
        return f"RoutingConfig(strategy={self.strategy}, targets={self.targets}, rules={self.rules}, default={self.default_target})"

mock_schemas.RoutingStrategy = MockRoutingStrategy
mock_schemas.RoutingTarget = MockRoutingTarget
mock_schemas.RoutingRule = MockRoutingRule
mock_schemas.RoutingConfig = MockRoutingConfig

sys.modules['baton'] = MagicMock()
sys.modules['baton.schemas'] = mock_schemas

# Now import the component under test
from src.baton.routing import ab_split, canary, header_route, weighted_split


# Helper functions for assertions
def find_target_by_name(targets, name):
    """Find a target by name in a list of targets."""
    for target in targets:
        if target.name == name:
            return target
    return None


def sum_weights(targets):
    """Sum all weights from targets."""
    return sum(t.weight for t in targets if t.weight is not None)


class TestAbSplit:
    """Test ab_split function - two-target weighted A/B split."""
    
    def test_ab_split_happy_path_50_50(self):
        """ab_split creates valid 50/50 split configuration"""
        # Arrange
        host = "api.example.com"
        port_a = 8080
        port_b = 8081
        pct_a = 50
        
        # Act
        result = ab_split(host, port_a, port_b, pct_a)
        
        # Assert
        assert result.strategy == MockRoutingStrategy.WEIGHTED, \
            "Strategy should be WEIGHTED"
        assert len(result.targets) == 2, \
            f"Should have exactly 2 targets, got {len(result.targets)}"
        
        target_a = find_target_by_name(result.targets, 'a')
        target_b = find_target_by_name(result.targets, 'b')
        
        assert target_a is not None, "Target 'a' should exist"
        assert target_b is not None, "Target 'b' should exist"
        assert target_a.weight == 50, f"Target 'a' should have weight=50, got {target_a.weight}"
        assert target_b.weight == 50, f"Target 'b' should have weight=50, got {target_b.weight}"
        assert target_a.host == host, f"Target 'a' should use host={host}"
        assert target_b.host == host, f"Target 'b' should use host={host}"
        assert sum_weights(result.targets) == 100, \
            f"Sum of weights should be 100, got {sum_weights(result.targets)}"
    
    def test_ab_split_edge_case_0_percent(self):
        """ab_split with 0% to target A (all traffic to B)"""
        # Arrange
        host = "api.test.com"
        port_a = 8000
        port_b = 9000
        pct_a = 0
        
        # Act
        result = ab_split(host, port_a, port_b, pct_a)
        
        # Assert
        target_a = find_target_by_name(result.targets, 'a')
        target_b = find_target_by_name(result.targets, 'b')
        
        assert target_a.weight == 0, f"Target 'a' should have weight=0, got {target_a.weight}"
        assert target_b.weight == 100, f"Target 'b' should have weight=100, got {target_b.weight}"
    
    def test_ab_split_edge_case_100_percent(self):
        """ab_split with 100% to target A (all traffic to A)"""
        # Arrange
        host = "api.test.com"
        port_a = 8000
        port_b = 9000
        pct_a = 100
        
        # Act
        result = ab_split(host, port_a, port_b, pct_a)
        
        # Assert
        target_a = find_target_by_name(result.targets, 'a')
        target_b = find_target_by_name(result.targets, 'b')
        
        assert target_a.weight == 100, f"Target 'a' should have weight=100, got {target_a.weight}"
        assert target_b.weight == 0, f"Target 'b' should have weight=0, got {target_b.weight}"
    
    def test_ab_split_edge_case_asymmetric(self):
        """ab_split with asymmetric split (95/5)"""
        # Arrange
        host = "api.prod.com"
        port_a = 443
        port_b = 444
        pct_a = 95
        
        # Act
        result = ab_split(host, port_a, port_b, pct_a)
        
        # Assert
        target_a = find_target_by_name(result.targets, 'a')
        target_b = find_target_by_name(result.targets, 'b')
        
        assert target_a.weight == 95, f"Target 'a' should have weight=95, got {target_a.weight}"
        assert target_b.weight == 5, f"Target 'b' should have weight=5, got {target_b.weight}"
        assert sum_weights(result.targets) == 100, \
            f"Sum of weights should be 100, got {sum_weights(result.targets)}"
    
    def test_ab_split_invariant_idempotency(self):
        """ab_split is idempotent - same inputs produce same outputs"""
        # Arrange
        host = "test.com"
        port_a = 8080
        port_b = 8081
        pct_a = 75
        
        # Act
        result1 = ab_split(host, port_a, port_b, pct_a)
        result2 = ab_split(host, port_a, port_b, pct_a)
        
        # Assert
        assert result1.strategy == result2.strategy, \
            "Strategies should match"
        assert len(result1.targets) == len(result2.targets), \
            "Number of targets should match"
        assert result1.targets == result2.targets, \
            "Targets should be equal (deep equality)"


class TestCanary:
    """Test canary function - canary rollout with stable and canary targets."""
    
    def test_canary_happy_path_5_percent(self):
        """canary creates valid 5% canary rollout configuration"""
        # Arrange
        host = "service.example.com"
        port_stable = 8080
        port_canary = 8081
        canary_pct = 5
        
        # Act
        result = canary(host, port_stable, port_canary, canary_pct)
        
        # Assert
        assert result.strategy == MockRoutingStrategy.CANARY, \
            "Strategy should be CANARY"
        assert len(result.targets) == 2, \
            f"Should have exactly 2 targets, got {len(result.targets)}"
        
        target_stable = find_target_by_name(result.targets, 'stable')
        target_canary = find_target_by_name(result.targets, 'canary')
        
        assert target_stable is not None, "Target 'stable' should exist"
        assert target_canary is not None, "Target 'canary' should exist"
        assert target_stable.weight == 95, \
            f"Target 'stable' should have weight=95, got {target_stable.weight}"
        assert target_canary.weight == 5, \
            f"Target 'canary' should have weight=5, got {target_canary.weight}"
        assert target_stable.host == host, f"Target 'stable' should use host={host}"
        assert target_canary.host == host, f"Target 'canary' should use host={host}"
        assert sum_weights(result.targets) == 100, \
            f"Sum of weights should be 100, got {sum_weights(result.targets)}"
    
    def test_canary_edge_case_0_percent(self):
        """canary with 0% canary (all traffic to stable)"""
        # Arrange
        host = "prod.com"
        port_stable = 80
        port_canary = 81
        canary_pct = 0
        
        # Act
        result = canary(host, port_stable, port_canary, canary_pct)
        
        # Assert
        target_stable = find_target_by_name(result.targets, 'stable')
        target_canary = find_target_by_name(result.targets, 'canary')
        
        assert target_stable.weight == 100, \
            f"Target 'stable' should have weight=100, got {target_stable.weight}"
        assert target_canary.weight == 0, \
            f"Target 'canary' should have weight=0, got {target_canary.weight}"
    
    def test_canary_edge_case_100_percent(self):
        """canary with 100% canary (full rollout)"""
        # Arrange
        host = "prod.com"
        port_stable = 80
        port_canary = 81
        canary_pct = 100
        
        # Act
        result = canary(host, port_stable, port_canary, canary_pct)
        
        # Assert
        target_stable = find_target_by_name(result.targets, 'stable')
        target_canary = find_target_by_name(result.targets, 'canary')
        
        assert target_stable.weight == 0, \
            f"Target 'stable' should have weight=0, got {target_stable.weight}"
        assert target_canary.weight == 100, \
            f"Target 'canary' should have weight=100, got {target_canary.weight}"
    
    def test_canary_happy_path_50_percent(self):
        """canary with 50% canary (even split)"""
        # Arrange
        host = "service.io"
        port_stable = 9000
        port_canary = 9001
        canary_pct = 50
        
        # Act
        result = canary(host, port_stable, port_canary, canary_pct)
        
        # Assert
        target_stable = find_target_by_name(result.targets, 'stable')
        target_canary = find_target_by_name(result.targets, 'canary')
        
        assert target_stable.weight == 50, \
            f"Target 'stable' should have weight=50, got {target_stable.weight}"
        assert target_canary.weight == 50, \
            f"Target 'canary' should have weight=50, got {target_canary.weight}"
    
    def test_canary_invariant_idempotency(self):
        """canary is idempotent - same inputs produce same outputs"""
        # Arrange
        host = "test.com"
        port_stable = 8080
        port_canary = 8081
        canary_pct = 10
        
        # Act
        result1 = canary(host, port_stable, port_canary, canary_pct)
        result2 = canary(host, port_stable, port_canary, canary_pct)
        
        # Assert
        assert result1.strategy == result2.strategy, \
            "Strategies should match"
        assert len(result1.targets) == len(result2.targets), \
            "Number of targets should match"
        assert result1.targets == result2.targets, \
            "Targets should be equal (deep equality)"


class TestHeaderRoute:
    """Test header_route function - header-based routing."""
    
    def test_header_route_happy_path_version_routing(self):
        """header_route creates valid header-based routing configuration"""
        # Arrange
        targets = [('v1', 'api.example.com', 8080), ('v2', 'api.example.com', 8081)]
        header = "X-Version"
        rules = [('v1', 'v1'), ('v2', 'v2')]
        default = 'v1'
        
        # Act
        result = header_route(targets, header, rules, default)
        
        # Assert
        assert result.strategy == MockRoutingStrategy.HEADER, \
            "Strategy should be HEADER"
        assert len(result.targets) == 2, \
            f"Should have 2 targets, got {len(result.targets)}"
        assert len(result.rules) == 2, \
            f"Should have 2 rules, got {len(result.rules)}"
        assert result.default_target == 'v1', \
            f"Default target should be 'v1', got {result.default_target}"
        
        # Check that rules use the correct header
        for rule in result.rules:
            assert rule.header == header, \
                f"Rule should use header '{header}', got '{rule.header}'"
    
    def test_header_route_edge_case_single_target(self):
        """header_route with single target (degenerate case)"""
        # Arrange
        targets = [('main', 'api.com', 80)]
        header = "X-Test"
        rules = []
        default = 'main'
        
        # Act
        result = header_route(targets, header, rules, default)
        
        # Assert
        assert len(result.targets) == 1, \
            f"Should have 1 target, got {len(result.targets)}"
        assert len(result.rules) == 0, \
            f"Should have 0 rules, got {len(result.rules)}"
        assert result.default_target == 'main', \
            f"Default target should be 'main', got {result.default_target}"
    
    def test_header_route_edge_case_many_targets(self):
        """header_route with multiple targets and rules"""
        # Arrange
        targets = [
            ('t1', 'h1', 80),
            ('t2', 'h2', 81),
            ('t3', 'h3', 82),
            ('t4', 'h4', 83),
            ('t5', 'h5', 84)
        ]
        header = "X-Region"
        rules = [
            ('us-east', 't1'),
            ('us-west', 't2'),
            ('eu-west', 't3'),
            ('ap-south', 't4'),
            ('ap-east', 't5')
        ]
        default = 't1'
        
        # Act
        result = header_route(targets, header, rules, default)
        
        # Assert
        assert len(result.targets) == 5, \
            f"Should have 5 targets, got {len(result.targets)}"
        assert len(result.rules) == 5, \
            f"Should have 5 rules, got {len(result.rules)}"
    
    def test_header_route_happy_path_user_routing(self):
        """header_route for user-specific routing with default fallback"""
        # Arrange
        targets = [('prod', 'api.prod.com', 443), ('beta', 'api.beta.com', 443)]
        header = "X-User-Type"
        rules = [('beta', 'beta')]
        default = 'prod'
        
        # Act
        result = header_route(targets, header, rules, default)
        
        # Assert
        assert len(result.targets) == 2, \
            f"Should have 2 targets, got {len(result.targets)}"
        assert len(result.rules) == 1, \
            f"Should have 1 rule, got {len(result.rules)}"
        assert result.default_target == 'prod', \
            f"Default target should be 'prod', got {result.default_target}"
    
    def test_header_route_invariant_idempotency(self):
        """header_route is idempotent - same inputs produce same outputs"""
        # Arrange
        targets = [('a', 'host', 80)]
        header = "X-Test"
        rules = [('val', 'a')]
        default = 'a'
        
        # Act
        result1 = header_route(targets, header, rules, default)
        result2 = header_route(targets, header, rules, default)
        
        # Assert
        assert result1.strategy == result2.strategy, \
            "Strategies should match"
        assert len(result1.targets) == len(result2.targets), \
            "Number of targets should match"
        assert len(result1.rules) == len(result2.rules), \
            "Number of rules should match"
        assert result1.default_target == result2.default_target, \
            "Default targets should match"


class TestWeightedSplit:
    """Test weighted_split function - N-target weighted distribution."""
    
    def test_weighted_split_happy_path_three_targets(self):
        """weighted_split creates valid 3-target weighted distribution"""
        # Arrange
        targets = [
            ('primary', 'api.com', 8080, 50),
            ('secondary', 'api.com', 8081, 30),
            ('tertiary', 'api.com', 8082, 20)
        ]
        
        # Act
        result = weighted_split(targets)
        
        # Assert
        assert result.strategy == MockRoutingStrategy.WEIGHTED, \
            "Strategy should be WEIGHTED"
        assert len(result.targets) == 3, \
            f"Should have 3 targets, got {len(result.targets)}"
        
        target_primary = find_target_by_name(result.targets, 'primary')
        target_secondary = find_target_by_name(result.targets, 'secondary')
        target_tertiary = find_target_by_name(result.targets, 'tertiary')
        
        assert target_primary.weight == 50, \
            f"Target 'primary' should have weight=50, got {target_primary.weight}"
        assert target_secondary.weight == 30, \
            f"Target 'secondary' should have weight=30, got {target_secondary.weight}"
        assert target_tertiary.weight == 20, \
            f"Target 'tertiary' should have weight=20, got {target_tertiary.weight}"
    
    def test_weighted_split_edge_case_single_target(self):
        """weighted_split with single target (100% weight)"""
        # Arrange
        targets = [('only', 'service.com', 443, 100)]
        
        # Act
        result = weighted_split(targets)
        
        # Assert
        assert len(result.targets) == 1, \
            f"Should have 1 target, got {len(result.targets)}"
        target_only = find_target_by_name(result.targets, 'only')
        assert target_only.weight == 100, \
            f"Target 'only' should have weight=100, got {target_only.weight}"
    
    def test_weighted_split_edge_case_two_targets(self):
        """weighted_split with two targets (similar to ab_split)"""
        # Arrange
        targets = [
            ('main', 'host.com', 80, 70),
            ('backup', 'host.com', 81, 30)
        ]
        
        # Act
        result = weighted_split(targets)
        
        # Assert
        assert len(result.targets) == 2, \
            f"Should have 2 targets, got {len(result.targets)}"
        target_main = find_target_by_name(result.targets, 'main')
        target_backup = find_target_by_name(result.targets, 'backup')
        assert target_main.weight == 70, \
            f"Target 'main' should have weight=70, got {target_main.weight}"
        assert target_backup.weight == 30, \
            f"Target 'backup' should have weight=30, got {target_backup.weight}"
    
    def test_weighted_split_edge_case_many_targets(self):
        """weighted_split with many targets (5 targets)"""
        # Arrange
        targets = [
            ('t1', 'h1', 80, 40),
            ('t2', 'h2', 81, 25),
            ('t3', 'h3', 82, 20),
            ('t4', 'h4', 83, 10),
            ('t5', 'h5', 84, 5)
        ]
        
        # Act
        result = weighted_split(targets)
        
        # Assert
        assert len(result.targets) == 5, \
            f"Should have 5 targets, got {len(result.targets)}"
        
        # Verify all weights match input
        for name, host, port, weight in targets:
            target = find_target_by_name(result.targets, name)
            assert target is not None, f"Target '{name}' should exist"
            assert target.weight == weight, \
                f"Target '{name}' should have weight={weight}, got {target.weight}"
    
    def test_weighted_split_edge_case_zero_weight(self):
        """weighted_split with one target having zero weight"""
        # Arrange
        targets = [
            ('a', 'host', 80, 50),
            ('b', 'host', 81, 50),
            ('c', 'host', 82, 0)
        ]
        
        # Act
        result = weighted_split(targets)
        
        # Assert
        assert len(result.targets) == 3, \
            f"Should have 3 targets, got {len(result.targets)}"
        target_c = find_target_by_name(result.targets, 'c')
        assert target_c.weight == 0, \
            f"Target 'c' should have weight=0, got {target_c.weight}"
    
    def test_weighted_split_invariant_idempotency(self):
        """weighted_split is idempotent - same inputs produce same outputs"""
        # Arrange
        targets = [
            ('a', 'host', 80, 60),
            ('b', 'host', 81, 40)
        ]
        
        # Act
        result1 = weighted_split(targets)
        result2 = weighted_split(targets)
        
        # Assert
        assert result1.strategy == result2.strategy, \
            "Strategies should match"
        assert len(result1.targets) == len(result2.targets), \
            "Number of targets should match"
        assert result1.targets == result2.targets, \
            "Targets should be equal (deep equality)"


class TestInvariants:
    """Test global invariants across all routing functions."""
    
    def test_all_functions_are_pure(self):
        """Verify all routing functions are pure (no side effects)"""
        # Test ab_split
        config1 = ab_split("host", 80, 81, 50)
        config2 = ab_split("host", 80, 81, 50)
        assert config1.targets == config2.targets
        
        # Test canary
        config3 = canary("host", 80, 81, 10)
        config4 = canary("host", 80, 81, 10)
        assert config3.targets == config4.targets
        
        # Test header_route
        config5 = header_route([('t1', 'h', 80)], "H", [('v', 't1')], 't1')
        config6 = header_route([('t1', 'h', 80)], "H", [('v', 't1')], 't1')
        assert config5.targets == config6.targets
        
        # Test weighted_split
        config7 = weighted_split([('t1', 'h', 80, 100)])
        config8 = weighted_split([('t1', 'h', 80, 100)])
        assert config7.targets == config8.targets
    
    def test_percentage_arithmetic_integrity(self):
        """Verify percentage calculations use integer arithmetic"""
        # ab_split
        result = ab_split("host", 80, 81, 33)
        target_b = find_target_by_name(result.targets, 'b')
        assert target_b.weight == 67  # 100 - 33
        
        # canary
        result = canary("host", 80, 81, 17)
        target_stable = find_target_by_name(result.targets, 'stable')
        assert target_stable.weight == 83  # 100 - 17
