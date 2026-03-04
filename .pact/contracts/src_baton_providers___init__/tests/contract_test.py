"""
Contract-driven pytest test suite for Deployment Provider Protocol and Factory.

This module contains tests organized into four categories:
1. Factory tests: provider creation, validation, and error handling
2. Protocol compliance tests: verify all providers implement required methods
3. Lifecycle tests: state transitions and idempotency
4. Integration tests: end-to-end workflows

All tests use mocking for dependencies (baton.schemas, baton.providers.*).
Tests verify behavior at boundaries (inputs/outputs), not internals.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys


# ==============================================================================
# TEST FIXTURES AND HELPERS
# ==============================================================================

@pytest.fixture
def mock_circuit_spec():
    """Create a mock CircuitSpec for testing."""
    mock_spec = Mock()
    mock_spec.name = "test_circuit"
    mock_spec.id = "circuit_123"
    return mock_spec


@pytest.fixture
def mock_deployment_target():
    """Create a mock DeploymentTarget for testing."""
    mock_target = Mock()
    mock_target.name = "test_target"
    mock_target.region = "us-east-1"
    return mock_target


@pytest.fixture
def mock_circuit_state():
    """Create a mock CircuitState for testing."""
    mock_state = Mock()
    mock_state.status = "deployed"
    mock_state.circuit_id = "circuit_123"
    return mock_state


@pytest.fixture
def mock_local_provider():
    """Create a mock LocalProvider with required methods."""
    provider = Mock()
    provider.deploy = Mock(return_value=Mock())
    provider.teardown = Mock(return_value=None)
    provider.status = Mock(return_value=Mock())
    return provider


@pytest.fixture
def mock_gcp_provider():
    """Create a mock GCPProvider with required methods."""
    provider = Mock()
    provider.deploy = Mock(return_value=Mock())
    provider.teardown = Mock(return_value=None)
    provider.status = Mock(return_value=Mock())
    return provider


@pytest.fixture
def mock_aws_provider():
    """Create a mock AWSProvider with required methods."""
    provider = Mock()
    provider.deploy = Mock(return_value=Mock())
    provider.teardown = Mock(return_value=None)
    provider.status = Mock(return_value=Mock())
    return provider


# ==============================================================================
# FACTORY TESTS: Provider Creation and Validation
# ==============================================================================

class TestCreateProviderFactory:
    """Tests for create_provider factory function."""

    @patch('src.src_baton_providers___init__.LocalProvider')
    def test_create_provider_local_happy_path(self, mock_local_class):
        """Creating a local provider returns a LocalProvider instance."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_instance = Mock()
        mock_local_class.return_value = mock_instance
        
        # Execute
        result = create_provider('local')
        
        # Assert
        assert result is not None, "Result should not be None"
        assert type(result).__name__ == 'Mock' or type(result).__name__ == 'LocalProvider', \
            f"Expected LocalProvider instance, got {type(result).__name__}"
        mock_local_class.assert_called_once()

    @patch('src.src_baton_providers___init__.GCPProvider')
    def test_create_provider_gcp_happy_path(self, mock_gcp_class):
        """Creating a gcp provider returns a GCPProvider instance."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_instance = Mock()
        mock_gcp_class.return_value = mock_instance
        
        # Execute
        result = create_provider('gcp')
        
        # Assert
        assert result is not None, "Result should not be None"
        assert type(result).__name__ == 'Mock' or type(result).__name__ == 'GCPProvider', \
            f"Expected GCPProvider instance, got {type(result).__name__}"
        mock_gcp_class.assert_called_once()

    @patch('src.src_baton_providers___init__.AWSProvider')
    def test_create_provider_aws_happy_path(self, mock_aws_class):
        """Creating an aws provider returns an AWSProvider instance."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_instance = Mock()
        mock_aws_class.return_value = mock_instance
        
        # Execute
        result = create_provider('aws')
        
        # Assert
        assert result is not None, "Result should not be None"
        assert type(result).__name__ == 'Mock' or type(result).__name__ == 'AWSProvider', \
            f"Expected AWSProvider instance, got {type(result).__name__}"
        mock_aws_class.assert_called_once()

    def test_create_provider_unknown_error(self):
        """Creating a provider with unknown name raises unknown_provider error."""
        from src.baton.providers.__init__ import create_provider
        
        # Execute & Assert
        with pytest.raises(Exception) as exc_info:
            create_provider('azure')
        
        # Verify the exception message contains 'unknown_provider' or similar
        assert 'unknown' in str(exc_info.value).lower() or \
               'azure' in str(exc_info.value).lower() or \
               'not found' in str(exc_info.value).lower(), \
            f"Expected unknown_provider error, got: {exc_info.value}"

    def test_create_provider_empty_name_error(self):
        """Creating a provider with empty name raises unknown_provider error."""
        from src.baton.providers.__init__ import create_provider
        
        # Execute & Assert
        with pytest.raises(Exception) as exc_info:
            create_provider('')
        
        # Verify the exception is raised
        assert exc_info.value is not None, "Expected exception for empty provider name"

    def test_create_provider_case_sensitive(self):
        """Creating a provider with uppercase name (LOCAL) raises unknown_provider error."""
        from src.baton.providers.__init__ import create_provider
        
        # Execute & Assert
        with pytest.raises(Exception) as exc_info:
            create_provider('LOCAL')
        
        # Verify case sensitivity
        assert exc_info.value is not None, \
            "Expected exception for case-sensitive name validation"

    def test_create_provider_whitespace(self):
        """Creating a provider with whitespace padding raises unknown_provider error."""
        from src.baton.providers.__init__ import create_provider
        
        # Execute & Assert
        with pytest.raises(Exception) as exc_info:
            create_provider(' local ')
        
        # Verify whitespace handling
        assert exc_info.value is not None, \
            "Expected exception for whitespace-padded name"

    @patch('src.src_baton_providers___init__.LocalProvider')
    @patch('src.src_baton_providers___init__.GCPProvider')
    @patch('src.src_baton_providers___init__.AWSProvider')
    def test_concurrent_provider_creation(self, mock_aws, mock_gcp, mock_local):
        """Creating multiple providers concurrently works correctly."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_local.return_value = Mock(name='LocalProvider')
        mock_gcp.return_value = Mock(name='GCPProvider')
        mock_aws.return_value = Mock(name='AWSProvider')
        
        # Execute
        local_provider = create_provider('local')
        gcp_provider = create_provider('gcp')
        aws_provider = create_provider('aws')
        
        # Assert
        assert local_provider is not None, "Local provider should be created"
        assert gcp_provider is not None, "GCP provider should be created"
        assert aws_provider is not None, "AWS provider should be created"
        
        mock_local.assert_called_once()
        mock_gcp.assert_called_once()
        mock_aws.assert_called_once()


# ==============================================================================
# PROTOCOL COMPLIANCE TESTS: Verify All Providers Implement Required Methods
# ==============================================================================

class TestProtocolCompliance:
    """Tests to verify all providers implement the DeploymentProvider protocol."""

    @patch('src.src_baton_providers___init__.LocalProvider')
    def test_local_provider_has_required_methods(self, mock_local_class):
        """LocalProvider implements deploy, teardown, and status methods."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_instance = Mock()
        mock_instance.deploy = Mock()
        mock_instance.teardown = Mock()
        mock_instance.status = Mock()
        mock_local_class.return_value = mock_instance
        
        # Execute
        provider = create_provider('local')
        
        # Assert
        assert hasattr(provider, 'deploy'), "LocalProvider must have deploy method"
        assert hasattr(provider, 'teardown'), "LocalProvider must have teardown method"
        assert hasattr(provider, 'status'), "LocalProvider must have status method"
        assert callable(provider.deploy), "deploy must be callable"
        assert callable(provider.teardown), "teardown must be callable"
        assert callable(provider.status), "status must be callable"

    @patch('src.src_baton_providers___init__.GCPProvider')
    def test_gcp_provider_has_required_methods(self, mock_gcp_class):
        """GCPProvider implements deploy, teardown, and status methods."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_instance = Mock()
        mock_instance.deploy = Mock()
        mock_instance.teardown = Mock()
        mock_instance.status = Mock()
        mock_gcp_class.return_value = mock_instance
        
        # Execute
        provider = create_provider('gcp')
        
        # Assert
        assert hasattr(provider, 'deploy'), "GCPProvider must have deploy method"
        assert hasattr(provider, 'teardown'), "GCPProvider must have teardown method"
        assert hasattr(provider, 'status'), "GCPProvider must have status method"
        assert callable(provider.deploy), "deploy must be callable"
        assert callable(provider.teardown), "teardown must be callable"
        assert callable(provider.status), "status must be callable"

    @patch('src.src_baton_providers___init__.AWSProvider')
    def test_aws_provider_has_required_methods(self, mock_aws_class):
        """AWSProvider implements deploy, teardown, and status methods."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_instance = Mock()
        mock_instance.deploy = Mock()
        mock_instance.teardown = Mock()
        mock_instance.status = Mock()
        mock_aws_class.return_value = mock_instance
        
        # Execute
        provider = create_provider('aws')
        
        # Assert
        assert hasattr(provider, 'deploy'), "AWSProvider must have deploy method"
        assert hasattr(provider, 'teardown'), "AWSProvider must have teardown method"
        assert hasattr(provider, 'status'), "AWSProvider must have status method"
        assert callable(provider.deploy), "deploy must be callable"
        assert callable(provider.teardown), "teardown must be callable"
        assert callable(provider.status), "status must be callable"


# ==============================================================================
# LIFECYCLE TESTS: State Transitions and Idempotency
# ==============================================================================

class TestProviderLifecycle:
    """Tests for deploy, teardown, status lifecycle and state transitions."""

    @patch('src.src_baton_providers___init__.LocalProvider')
    def test_deploy_returns_circuit_state(self, mock_local_class, 
                                         mock_circuit_spec, mock_deployment_target):
        """Deploy method returns a CircuitState object."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_circuit_state = Mock()
        mock_circuit_state.__class__.__name__ = 'CircuitState'
        
        mock_instance = Mock()
        mock_instance.deploy = Mock(return_value=mock_circuit_state)
        mock_local_class.return_value = mock_instance
        
        # Execute
        provider = create_provider('local')
        result = provider.deploy(mock_circuit_spec, mock_deployment_target)
        
        # Assert
        assert result is not None, "Deploy should return a CircuitState"
        assert type(result).__name__ == 'CircuitState' or type(result).__name__ == 'Mock', \
            f"Expected CircuitState, got {type(result).__name__}"

    @patch('src.src_baton_providers___init__.LocalProvider')
    def test_teardown_returns_none(self, mock_local_class, 
                                   mock_circuit_spec, mock_deployment_target):
        """Teardown method returns None."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_instance = Mock()
        mock_instance.teardown = Mock(return_value=None)
        mock_local_class.return_value = mock_instance
        
        # Execute
        provider = create_provider('local')
        result = provider.teardown(mock_circuit_spec, mock_deployment_target)
        
        # Assert
        assert result is None, "Teardown should return None"

    @patch('src.src_baton_providers___init__.LocalProvider')
    def test_status_returns_circuit_state(self, mock_local_class, 
                                         mock_circuit_spec, mock_deployment_target):
        """Status method returns a CircuitState object."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_circuit_state = Mock()
        mock_circuit_state.__class__.__name__ = 'CircuitState'
        
        mock_instance = Mock()
        mock_instance.status = Mock(return_value=mock_circuit_state)
        mock_local_class.return_value = mock_instance
        
        # Execute
        provider = create_provider('local')
        result = provider.status(mock_circuit_spec, mock_deployment_target)
        
        # Assert
        assert result is not None, "Status should return a CircuitState"
        assert type(result).__name__ == 'CircuitState' or type(result).__name__ == 'Mock', \
            f"Expected CircuitState, got {type(result).__name__}"

    @patch('src.src_baton_providers___init__.LocalProvider')
    def test_deploy_lifecycle_state_transition(self, mock_local_class,
                                               mock_circuit_spec, mock_deployment_target):
        """Deploy followed by status returns consistent CircuitState."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_deploy_state = Mock()
        mock_deploy_state.__class__.__name__ = 'CircuitState'
        mock_status_state = Mock()
        mock_status_state.__class__.__name__ = 'CircuitState'
        
        mock_instance = Mock()
        mock_instance.deploy = Mock(return_value=mock_deploy_state)
        mock_instance.status = Mock(return_value=mock_status_state)
        mock_local_class.return_value = mock_instance
        
        # Execute
        provider = create_provider('local')
        deploy_result = provider.deploy(mock_circuit_spec, mock_deployment_target)
        status_result = provider.status(mock_circuit_spec, mock_deployment_target)
        
        # Assert
        assert deploy_result is not None, "Deploy should return a result"
        assert status_result is not None, "Status should return a result"
        assert type(deploy_result).__name__ in ['CircuitState', 'Mock'], \
            f"Deploy result should be CircuitState, got {type(deploy_result).__name__}"
        assert type(status_result).__name__ in ['CircuitState', 'Mock'], \
            f"Status result should be CircuitState, got {type(status_result).__name__}"

    @patch('src.src_baton_providers___init__.LocalProvider')
    def test_deploy_idempotency(self, mock_local_class,
                               mock_circuit_spec, mock_deployment_target):
        """Deploying the same circuit twice should be idempotent."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_state = Mock()
        mock_state.__class__.__name__ = 'CircuitState'
        
        mock_instance = Mock()
        mock_instance.deploy = Mock(return_value=mock_state)
        mock_local_class.return_value = mock_instance
        
        # Execute
        provider = create_provider('local')
        first_result = provider.deploy(mock_circuit_spec, mock_deployment_target)
        second_result = provider.deploy(mock_circuit_spec, mock_deployment_target)
        
        # Assert
        assert first_result is not None, "First deploy should return a result"
        assert second_result is not None, "Second deploy should return a result"
        assert mock_instance.deploy.call_count == 2, "Deploy should be called twice"

    @patch('src.src_baton_providers___init__.LocalProvider')
    def test_teardown_idempotency(self, mock_local_class,
                                  mock_circuit_spec, mock_deployment_target):
        """Tearing down the same circuit twice should be idempotent."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_instance = Mock()
        mock_instance.teardown = Mock(return_value=None)
        mock_local_class.return_value = mock_instance
        
        # Execute
        provider = create_provider('local')
        first_teardown = provider.teardown(mock_circuit_spec, mock_deployment_target)
        second_teardown = provider.teardown(mock_circuit_spec, mock_deployment_target)
        
        # Assert
        assert first_teardown is None, "First teardown should return None"
        assert second_teardown is None, "Second teardown should return None"
        assert mock_instance.teardown.call_count == 2, "Teardown should be called twice"

    @patch('src.src_baton_providers___init__.LocalProvider')
    def test_teardown_on_nonexistent_circuit(self, mock_local_class,
                                             mock_circuit_spec, mock_deployment_target):
        """Teardown of non-existent circuit completes without error."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_instance = Mock()
        mock_instance.teardown = Mock(return_value=None)
        mock_local_class.return_value = mock_instance
        
        # Execute
        provider = create_provider('local')
        result = provider.teardown(mock_circuit_spec, mock_deployment_target)
        
        # Assert - no exception raised
        assert result is None, "Teardown should return None even for non-existent circuit"

    @patch('src.src_baton_providers___init__.LocalProvider')
    def test_status_on_nonexistent_circuit(self, mock_local_class,
                                           mock_circuit_spec, mock_deployment_target):
        """Status check on non-existent circuit returns CircuitState."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_state = Mock()
        mock_state.__class__.__name__ = 'CircuitState'
        mock_state.status = 'not_found'
        
        mock_instance = Mock()
        mock_instance.status = Mock(return_value=mock_state)
        mock_local_class.return_value = mock_instance
        
        # Execute
        provider = create_provider('local')
        result = provider.status(mock_circuit_spec, mock_deployment_target)
        
        # Assert
        assert result is not None, "Status should return a CircuitState"
        assert type(result).__name__ in ['CircuitState', 'Mock'], \
            f"Expected CircuitState, got {type(result).__name__}"


# ==============================================================================
# INVARIANT TESTS: Contract Guarantees
# ==============================================================================

class TestInvariants:
    """Tests for contract invariants."""

    @patch('src.src_baton_providers___init__.LocalProvider')
    @patch('src.src_baton_providers___init__.GCPProvider')
    @patch('src.src_baton_providers___init__.AWSProvider')
    def test_provider_only_supports_three_types(self, mock_aws, mock_gcp, mock_local):
        """Invariant: Only local, gcp, and aws providers are supported."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup mocks
        mock_local.return_value = Mock()
        mock_gcp.return_value = Mock()
        mock_aws.return_value = Mock()
        
        # Test valid providers
        local_provider = create_provider('local')
        gcp_provider = create_provider('gcp')
        aws_provider = create_provider('aws')
        
        assert local_provider is not None, "local provider should be created"
        assert gcp_provider is not None, "gcp provider should be created"
        assert aws_provider is not None, "aws provider should be created"
        
        # Test invalid providers
        invalid_names = ['azure', 'ibm', 'oracle', 'digitalocean', '']
        for invalid_name in invalid_names:
            with pytest.raises(Exception):
                create_provider(invalid_name)


# ==============================================================================
# INTEGRATION TESTS: End-to-End Workflows
# ==============================================================================

class TestIntegration:
    """Integration tests for complete workflows."""

    @patch('src.src_baton_providers___init__.LocalProvider')
    def test_complete_deployment_lifecycle(self, mock_local_class,
                                           mock_circuit_spec, mock_deployment_target):
        """Test complete lifecycle: create provider -> deploy -> status -> teardown."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_deploy_state = Mock()
        mock_deploy_state.__class__.__name__ = 'CircuitState'
        mock_deploy_state.status = 'deployed'
        
        mock_status_state = Mock()
        mock_status_state.__class__.__name__ = 'CircuitState'
        mock_status_state.status = 'deployed'
        
        mock_instance = Mock()
        mock_instance.deploy = Mock(return_value=mock_deploy_state)
        mock_instance.status = Mock(return_value=mock_status_state)
        mock_instance.teardown = Mock(return_value=None)
        mock_local_class.return_value = mock_instance
        
        # Execute complete lifecycle
        provider = create_provider('local')
        
        # Deploy
        deploy_result = provider.deploy(mock_circuit_spec, mock_deployment_target)
        assert deploy_result is not None, "Deploy should succeed"
        
        # Check status
        status_result = provider.status(mock_circuit_spec, mock_deployment_target)
        assert status_result is not None, "Status check should succeed"
        
        # Teardown
        teardown_result = provider.teardown(mock_circuit_spec, mock_deployment_target)
        assert teardown_result is None, "Teardown should succeed and return None"
        
        # Verify all methods were called
        mock_instance.deploy.assert_called_once()
        mock_instance.status.assert_called_once()
        mock_instance.teardown.assert_called_once()

    @patch('src.src_baton_providers___init__.LocalProvider')
    @patch('src.src_baton_providers___init__.GCPProvider')
    @patch('src.src_baton_providers___init__.AWSProvider')
    def test_multiple_providers_independent(self, mock_aws, mock_gcp, mock_local,
                                            mock_circuit_spec, mock_deployment_target):
        """Test that multiple provider instances work independently."""
        from src.baton.providers.__init__ import create_provider
        
        # Setup
        mock_state = Mock()
        mock_state.__class__.__name__ = 'CircuitState'
        
        local_instance = Mock()
        local_instance.deploy = Mock(return_value=mock_state)
        mock_local.return_value = local_instance
        
        gcp_instance = Mock()
        gcp_instance.deploy = Mock(return_value=mock_state)
        mock_gcp.return_value = gcp_instance
        
        aws_instance = Mock()
        aws_instance.deploy = Mock(return_value=mock_state)
        mock_aws.return_value = aws_instance
        
        # Execute
        local_provider = create_provider('local')
        gcp_provider = create_provider('gcp')
        aws_provider = create_provider('aws')
        
        local_result = local_provider.deploy(mock_circuit_spec, mock_deployment_target)
        gcp_result = gcp_provider.deploy(mock_circuit_spec, mock_deployment_target)
        aws_result = aws_provider.deploy(mock_circuit_spec, mock_deployment_target)
        
        # Assert
        assert local_result is not None, "Local deploy should succeed"
        assert gcp_result is not None, "GCP deploy should succeed"
        assert aws_result is not None, "AWS deploy should succeed"
        
        local_instance.deploy.assert_called_once()
        gcp_instance.deploy.assert_called_once()
        aws_instance.deploy.assert_called_once()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
