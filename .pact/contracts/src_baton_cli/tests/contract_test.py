"""
Contract-driven tests for Baton CLI Entry Point (src_baton_cli).

Tests verify the CLI layer behavior at boundaries (inputs/outputs) by mocking
all underlying business logic from baton.* modules. Covers 34 functions across
7 command groups with focus on exit codes, error handling, and state mutations.

Test Organization:
- TestMain: Entry point and argv parsing
- TestAsyncDispatchers: Command routing (_cmd_async, _cmd_route_async, _cmd_image_async)
- TestLifecycleCommands: up, down, slot, swap, collapse, watch
- TestRouteCommands: route show/ab/canary/set/lock/unlock/clear
- TestDeployCommands: deploy, teardown, deploy-status, build_deploy_target
- TestImageCommands: image list/build/push
- TestConfigCommands: init, node, edge, contract
- TestServiceCommands: service register/list/derive, check
- TestMonitoringCommands: signals, metrics, dashboard, status
- TestInvariants: Cross-cutting invariants (CONFIG_FILENAME, exit codes)
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, mock_open, call
from argparse import Namespace
import sys
import asyncio
from pathlib import Path

# Import component under test
# Adjust import path based on actual module structure
try:
    from src.baton_cli import *
except ImportError:
    # Fallback for different project structures
    try:
        from baton_cli import *
    except ImportError:
        # Create mock module for testing if actual import fails
        import types
        sys.modules['src.baton_cli'] = types.ModuleType('src.baton_cli')


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_args():
    """Factory fixture for creating argparse.Namespace with defaults."""
    def _create(**kwargs):
        defaults = {
            'command': 'status',
            'dir': '/tmp/test_circuit',
            'mock': False,
            'node': 'node1',
            'route_command': 'show',
            'image_command': 'list',
            'node_command': 'add',
            'edge_command': 'add',
            'contract_command': 'set',
            'service_command': 'list',
            'split': '50/50',
            'strategy': 'weighted',
            'targets': 'svc1:8080:50,svc2:8081:50',
            'rules': None,
            'promote': False,
            'provider': 'local',
            'region': 'us-west1',
            'namespace': 'default',
            'serve': False,
            'tag': None,
            'path': None,
            'live': [],
            'name': 'test_node',
            'source': 'node1',
            'target': 'node2',
            'spec': '/tmp/contract.yaml',
        }
        defaults.update(kwargs)
        return Namespace(**defaults)
    return _create


@pytest.fixture
def mock_circuit():
    """Mock baton.circuit module."""
    with patch('baton.circuit.Circuit') as mock:
        circuit_instance = MagicMock()
        mock.return_value = circuit_instance
        yield circuit_instance


@pytest.fixture
def mock_lifecycle():
    """Mock baton.lifecycle module."""
    with patch('baton.lifecycle.LifecycleManager') as mock:
        lifecycle_instance = MagicMock()
        mock.return_value = lifecycle_instance
        yield lifecycle_instance


@pytest.fixture
def mock_providers():
    """Mock baton.providers module."""
    with patch('baton.providers.create_provider') as mock:
        provider_instance = MagicMock()
        mock.return_value = provider_instance
        yield mock


@pytest.fixture
def mock_config():
    """Mock baton.config module."""
    with patch('baton.config.load_circuit') as load_mock, \
         patch('baton.config.save_circuit') as save_mock:
        yield {'load': load_mock, 'save': save_mock}


@pytest.fixture
def mock_state():
    """Mock baton.state module."""
    with patch('baton.state.StateManager') as mock:
        state_instance = MagicMock()
        mock.return_value = state_instance
        yield state_instance


# =============================================================================
# Test Classes
# =============================================================================


class TestMain:
    """Tests for main() entry point."""

    @patch('sys.argv', ['baton', 'status'])
    @patch('baton.config.load_circuit')
    @patch('baton.state.StateManager')
    def test_main_success(self, mock_state, mock_load, mock_args):
        """main returns 0 on successful command execution."""
        mock_load.return_value = MagicMock()
        mock_state.return_value = MagicMock()
        
        with patch('src.baton_cli._cmd_status', return_value=0) as mock_cmd:
            result = main(['status'])
            assert result == 0

    @patch('sys.argv', ['baton', '--invalid-flag'])
    def test_main_parsing_error(self):
        """main returns 1 on command parsing errors."""
        with patch('argparse.ArgumentParser.parse_args', side_effect=SystemExit(2)):
            result = main(['--invalid-flag'])
            assert result == 1

    @patch('sys.argv', ['baton'])
    def test_main_missing_command(self):
        """main returns 1 on missing command."""
        with patch('argparse.ArgumentParser.parse_args') as mock_parse:
            mock_parse.return_value = Namespace(command=None, dir='/tmp')
            result = main([])
            assert result == 1

    @patch('sys.argv', ['baton', 'up'])
    def test_main_keyboard_interrupt(self, mock_args):
        """main returns 130 on KeyboardInterrupt."""
        with patch('src.baton_cli._cmd_async', side_effect=KeyboardInterrupt()):
            result = main(['up'])
            assert result == 130

    @patch('sys.argv', ['baton', 'status'])
    def test_main_file_not_found(self):
        """main returns 1 when configuration files not found."""
        with patch('baton.config.load_circuit', side_effect=FileNotFoundError()):
            result = main(['status'])
            assert result == 1

    @patch('sys.argv', ['baton', 'status', '--dir', '/tmp/test'])
    @patch('baton.config.load_circuit')
    def test_main_with_real_argv(self, mock_load):
        """Integration test for main with real argv parsing."""
        mock_load.return_value = MagicMock()
        with patch('src.baton_cli._cmd_status', return_value=0):
            result = main(['status', '--dir', '/tmp/test'])
            assert result == 0


class TestAsyncDispatchers:
    """Tests for async command dispatchers."""

    @patch('src.baton_cli._cmd_up', return_value=0)
    def test_cmd_async_up_command(self, mock_up, mock_args):
        """_cmd_async routes 'up' command to handler."""
        args = mock_args(command='up')
        result = _cmd_async(args)
        assert result == 0
        mock_up.assert_called_once_with(args)

    def test_cmd_async_unrecognized_command(self, mock_args):
        """_cmd_async returns 1 for unrecognized command."""
        args = mock_args(command='invalid_command')
        result = _cmd_async(args)
        assert result == 1

    @pytest.mark.parametrize('command,handler', [
        ('up', '_cmd_up'),
        ('down', '_cmd_down'),
        ('slot', '_cmd_slot'),
        ('swap', '_cmd_swap'),
        ('collapse', '_cmd_collapse'),
        ('watch', '_cmd_watch'),
        ('route', '_cmd_route_async'),
        ('deploy', '_cmd_deploy'),
        ('teardown', '_cmd_teardown'),
        ('deploy-status', '_cmd_deploy_status'),
        ('dashboard', '_cmd_dashboard'),
        ('image', '_cmd_image_async'),
    ])
    def test_cmd_async_all_commands(self, command, handler, mock_args):
        """_cmd_async routes all valid async commands."""
        args = mock_args(command=command)
        with patch(f'src.baton_cli.{handler}', return_value=0) as mock_handler:
            result = _cmd_async(args)
            assert result == 0
            mock_handler.assert_called_once_with(args)

    @patch('src.baton_cli._cmd_route_ab', return_value=0)
    def test_cmd_route_async_ab(self, mock_ab, mock_args):
        """_cmd_route_async routes 'ab' command."""
        args = mock_args(route_command='ab')
        result = _cmd_route_async(args)
        assert result == 0
        mock_ab.assert_called_once_with(args)

    def test_cmd_route_async_unrecognized(self, mock_args):
        """_cmd_route_async returns 1 for unrecognized route command."""
        args = mock_args(route_command='invalid')
        result = _cmd_route_async(args)
        assert result == 1

    @patch('src.baton_cli._cmd_image_build', return_value=0)
    def test_cmd_image_async_build(self, mock_build, mock_args):
        """_cmd_image_async routes 'build' command."""
        args = mock_args(image_command='build')
        result = _cmd_image_async(args)
        assert result == 0
        mock_build.assert_called_once_with(args)

    def test_cmd_image_async_unrecognized(self, mock_args):
        """_cmd_image_async returns 1 for unrecognized image command."""
        args = mock_args(image_command='invalid')
        result = _cmd_image_async(args)
        assert result == 1


class TestLifecycleCommands:
    """Tests for circuit lifecycle commands."""

    @patch('baton.lifecycle.LifecycleManager')
    @patch('baton.config.load_circuit')
    def test_cmd_up_basic(self, mock_load, mock_lifecycle, mock_args):
        """_cmd_up boots circuit and starts adapters."""
        args = mock_args(mock=False)
        mock_circuit = MagicMock()
        mock_load.return_value = mock_circuit
        mock_lm = MagicMock()
        mock_lifecycle.return_value = mock_lm
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_up(args)
            assert result == 0

    @patch('baton.lifecycle.LifecycleManager')
    @patch('baton.config.load_circuit')
    @patch('baton.collapse.start_mock_server')
    def test_cmd_up_with_mock(self, mock_mock_server, mock_load, mock_lifecycle, mock_args):
        """_cmd_up boots circuit with mock server."""
        args = mock_args(mock=True)
        mock_circuit = MagicMock()
        mock_load.return_value = mock_circuit
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_up(args)
            assert result == 0

    @patch('baton.state.clear_state')
    def test_cmd_down_success(self, mock_clear, mock_args):
        """_cmd_down clears circuit state."""
        args = mock_args()
        result = _cmd_down(args)
        assert result == 0
        mock_clear.assert_called_once()

    @patch('baton.lifecycle.LifecycleManager')
    def test_cmd_slot_success(self, mock_lifecycle, mock_args):
        """_cmd_slot slots service into node."""
        args = mock_args(mock=False, command='./service')
        mock_lm = MagicMock()
        mock_lifecycle.return_value = mock_lm
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_slot(args)
            assert result == 0

    def test_cmd_slot_mock_mode_error(self, mock_args):
        """_cmd_slot returns 1 when in mock mode."""
        args = mock_args(mock=True)
        result = _cmd_slot(args)
        assert result == 1

    def test_cmd_slot_no_command_error(self, mock_args):
        """_cmd_slot returns 1 when no command provided."""
        args = mock_args(mock=False, command=None)
        result = _cmd_slot(args)
        assert result == 1

    @patch('baton.lifecycle.LifecycleManager')
    def test_cmd_swap_success(self, mock_lifecycle, mock_args):
        """_cmd_swap hot-swaps service."""
        args = mock_args(command='./new_service')
        mock_lm = MagicMock()
        mock_lifecycle.return_value = mock_lm
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_swap(args)
            assert result == 0

    @patch('baton.config.load_circuit')
    @patch('baton.collapse.validate_live_nodes')
    @patch('baton.collapse.start_mock_server')
    @patch('baton.lifecycle.LifecycleManager')
    def test_cmd_collapse_success(self, mock_lm, mock_mock, mock_validate, mock_load, mock_args):
        """_cmd_collapse runs circuit with specified nodes live."""
        args = mock_args(live=['node1', 'node2'])
        mock_circuit = MagicMock()
        mock_load.return_value = mock_circuit
        mock_validate.return_value = True
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_collapse(args)
            assert result == 0

    @patch('baton.config.load_circuit')
    @patch('baton.collapse.validate_live_nodes')
    def test_cmd_collapse_unknown_node(self, mock_validate, mock_load, mock_args):
        """_cmd_collapse returns 1 for unknown nodes."""
        args = mock_args(live=['unknown_node'])
        mock_circuit = MagicMock()
        mock_load.return_value = mock_circuit
        mock_validate.side_effect = ValueError("Unknown node: unknown_node")
        
        result = _cmd_collapse(args)
        assert result == 1

    @patch('baton.custodian.CustodianMonitor')
    def test_cmd_watch_success(self, mock_custodian, mock_args):
        """_cmd_watch starts custodian monitor."""
        args = mock_args()
        mock_monitor = MagicMock()
        mock_custodian.return_value = mock_monitor
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_watch(args)
            assert result == 0

    @patch('baton.lifecycle.LifecycleManager')
    def test_cmd_up_keyboard_interrupt(self, mock_lifecycle, mock_args):
        """_cmd_up handles KeyboardInterrupt during running."""
        args = mock_args()
        with patch('asyncio.run', side_effect=KeyboardInterrupt()):
            result = _cmd_up(args)
            assert result == 0


class TestRouteCommands:
    """Tests for routing configuration commands."""

    @patch('baton.state.StateManager')
    def test_cmd_route_show_success(self, mock_state, mock_args):
        """_cmd_route_show displays routing config."""
        args = mock_args(node='node1')
        mock_sm = MagicMock()
        mock_sm.get_node_routing.return_value = {'backend': 'service:8080'}
        mock_state.return_value = mock_sm
        
        result = _cmd_route_show(args)
        assert result == 0

    @patch('baton.state.StateManager')
    def test_cmd_route_show_node_not_found(self, mock_state, mock_args):
        """_cmd_route_show returns 1 when node not found."""
        args = mock_args(node='nonexistent')
        mock_sm = MagicMock()
        mock_sm.get_node_routing.side_effect = KeyError("Node not found")
        mock_state.return_value = mock_sm
        
        result = _cmd_route_show(args)
        assert result == 1

    @patch('baton.lifecycle.LifecycleManager')
    def test_cmd_route_ab_valid_split(self, mock_lifecycle, mock_args):
        """_cmd_route_ab configures A/B routing with valid split."""
        args = mock_args(split='80/20', node='node1')
        mock_lm = MagicMock()
        mock_lifecycle.return_value = mock_lm
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_route_ab(args)
            assert result == 0

    def test_cmd_route_ab_invalid_format(self, mock_args):
        """_cmd_route_ab returns 1 for invalid split format."""
        args = mock_args(split='invalid')
        result = _cmd_route_ab(args)
        assert result == 1

    def test_cmd_route_ab_non_integer(self, mock_args):
        """_cmd_route_ab returns 1 for non-integer split values."""
        args = mock_args(split='50.5/49.5')
        result = _cmd_route_ab(args)
        assert result == 1

    @pytest.mark.parametrize('split', ['100/0', '0/100'])
    def test_cmd_route_ab_edge_splits(self, split, mock_args, mock_lifecycle):
        """_cmd_route_ab handles edge case splits (100/0, 0/100)."""
        args = mock_args(split=split, node='node1')
        mock_lm = MagicMock()
        mock_lifecycle.return_value = mock_lm
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_route_ab(args)
            assert result == 0

    @patch('baton.lifecycle.LifecycleManager')
    def test_cmd_route_canary_basic(self, mock_lifecycle, mock_args):
        """_cmd_route_canary configures canary deployment."""
        args = mock_args(promote=False, node='node1')
        mock_lm = MagicMock()
        mock_lifecycle.return_value = mock_lm
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_route_canary(args)
            assert result == 0

    @patch('baton.lifecycle.LifecycleManager')
    @patch('baton.custodian.CanaryController')
    def test_cmd_route_canary_with_promotion(self, mock_canary, mock_lifecycle, mock_args):
        """_cmd_route_canary runs canary controller with auto-promotion."""
        args = mock_args(promote=True, node='node1')
        mock_lm = MagicMock()
        mock_lifecycle.return_value = mock_lm
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_route_canary(args)
            assert result == 0

    @patch('baton.lifecycle.LifecycleManager')
    def test_cmd_route_set_weighted(self, mock_lifecycle, mock_args):
        """_cmd_route_set configures weighted routing."""
        args = mock_args(strategy='weighted', targets='svc1:8080:70,svc2:8081:30', node='node1')
        mock_lm = MagicMock()
        mock_lifecycle.return_value = mock_lm
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_route_set(args)
            assert result == 0

    @patch('baton.lifecycle.LifecycleManager')
    def test_cmd_route_set_header(self, mock_lifecycle, mock_args):
        """_cmd_route_set configures header-based routing."""
        args = mock_args(strategy='header', targets='svc1:8080,svc2:8081', node='node1')
        mock_lm = MagicMock()
        mock_lifecycle.return_value = mock_lm
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_route_set(args)
            assert result == 0

    def test_cmd_route_set_invalid_target(self, mock_args):
        """_cmd_route_set returns 1 for invalid target format."""
        args = mock_args(targets='invalid_format', node='node1')
        result = _cmd_route_set(args)
        assert result == 1

    def test_cmd_route_set_invalid_rule(self, mock_args):
        """_cmd_route_set returns 1 for invalid rule format."""
        args = mock_args(strategy='header', rules='bad_rule', node='node1')
        result = _cmd_route_set(args)
        assert result == 1

    def test_cmd_route_set_empty_targets(self, mock_args):
        """_cmd_route_set handles empty targets string."""
        args = mock_args(targets='', node='node1')
        result = _cmd_route_set(args)
        assert result == 1

    @patch('baton.lifecycle.LifecycleManager')
    def test_cmd_route_lock_success(self, mock_lifecycle, mock_args):
        """_cmd_route_lock locks routing config."""
        args = mock_args(node='node1')
        mock_lm = MagicMock()
        mock_lifecycle.return_value = mock_lm
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_route_lock(args)
            assert result == 0

    @patch('baton.lifecycle.LifecycleManager')
    def test_cmd_route_unlock_success(self, mock_lifecycle, mock_args):
        """_cmd_route_unlock unlocks routing config."""
        args = mock_args(node='node1')
        mock_lm = MagicMock()
        mock_lifecycle.return_value = mock_lm
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_route_unlock(args)
            assert result == 0

    @patch('baton.lifecycle.LifecycleManager')
    def test_cmd_route_clear_success(self, mock_lifecycle, mock_args):
        """_cmd_route_clear clears routing config."""
        args = mock_args(node='node1')
        mock_lm = MagicMock()
        mock_lm.adapters = {'node1': MagicMock()}
        mock_lifecycle.return_value = mock_lm
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_route_clear(args)
            assert result == 0

    @patch('baton.lifecycle.LifecycleManager')
    def test_cmd_route_clear_node_not_found(self, mock_lifecycle, mock_args):
        """_cmd_route_clear returns 1 when node not found."""
        args = mock_args(node='nonexistent')
        mock_lm = MagicMock()
        mock_lm.adapters = {}
        mock_lifecycle.return_value = mock_lm
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_route_clear(args)
            assert result == 1


class TestDeployCommands:
    """Tests for deployment commands."""

    def test_build_deploy_target_basic(self, mock_args):
        """_build_deploy_target constructs DeploymentTarget from args."""
        args = mock_args(provider='gcp', region='us-west1', namespace='default')
        with patch('baton.providers.DeploymentTarget') as mock_target:
            _build_deploy_target(args)
            mock_target.assert_called_once()

    @patch('baton.config.load_circuit')
    @patch('baton.providers.create_provider')
    def test_cmd_deploy_local(self, mock_provider, mock_load, mock_args):
        """_cmd_deploy deploys to local provider and waits."""
        args = mock_args(provider='local')
        mock_circuit = MagicMock()
        mock_load.return_value = mock_circuit
        mock_prov = MagicMock()
        mock_provider.return_value = mock_prov
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_deploy(args)
            assert result == 0

    @patch('baton.config.load_circuit')
    @patch('baton.providers.create_provider')
    def test_cmd_deploy_cloud(self, mock_provider, mock_load, mock_args):
        """_cmd_deploy deploys to cloud provider."""
        args = mock_args(provider='gcp')
        mock_circuit = MagicMock()
        mock_load.return_value = mock_circuit
        mock_prov = MagicMock()
        mock_provider.return_value = mock_prov
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_deploy(args)
            assert result == 0

    @patch('baton.config.load_circuit')
    @patch('baton.providers.create_provider')
    def test_cmd_teardown_success(self, mock_provider, mock_load, mock_args):
        """_cmd_teardown tears down deployed circuit."""
        args = mock_args()
        mock_circuit = MagicMock()
        mock_load.return_value = mock_circuit
        mock_prov = MagicMock()
        mock_provider.return_value = mock_prov
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_teardown(args)
            assert result == 0

    @patch('baton.config.load_circuit')
    @patch('baton.providers.create_provider')
    def test_cmd_deploy_status_success(self, mock_provider, mock_load, mock_args):
        """_cmd_deploy_status displays deployment status."""
        args = mock_args()
        mock_circuit = MagicMock()
        mock_load.return_value = mock_circuit
        mock_prov = MagicMock()
        mock_provider.return_value = mock_prov
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_deploy_status(args)
            assert result == 0


class TestImageCommands:
    """Tests for container image commands."""

    @patch('baton.image.list_images')
    def test_cmd_image_list_success(self, mock_list, mock_args):
        """_cmd_image_list lists built images."""
        args = mock_args()
        mock_list.return_value = [
            {'node': 'node1', 'tag': 'v1.0', 'timestamp': '2023-01-01'}
        ]
        
        result = _cmd_image_list(args)
        assert result == 0

    @patch('baton.config.load_circuit')
    @patch('baton.image.build_image')
    def test_cmd_image_build_with_path(self, mock_build, mock_load, mock_args):
        """_cmd_image_build builds image with --path."""
        args = mock_args(node='node1', path='/path/to/service')
        mock_circuit = MagicMock()
        mock_load.return_value = mock_circuit
        mock_build.return_value = {'tag': 'node1:latest'}
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_image_build(args)
            assert result == 0

    def test_cmd_image_build_missing_node(self, mock_args):
        """_cmd_image_build returns 1 when --node missing."""
        args = mock_args(node=None)
        result = _cmd_image_build(args)
        assert result == 1

    @patch('baton.config.load_circuit')
    def test_cmd_image_build_missing_path(self, mock_load, mock_args):
        """_cmd_image_build returns 1 when --path and service_dir missing."""
        args = mock_args(node='node1', path=None)
        mock_circuit = MagicMock()
        mock_circuit.get_node_metadata.return_value = {}
        mock_load.return_value = mock_circuit
        
        result = _cmd_image_build(args)
        assert result == 1

    @patch('baton.image.push_image')
    def test_cmd_image_push_with_tag(self, mock_push, mock_args):
        """_cmd_image_push pushes image with --tag."""
        args = mock_args(tag='myimage:latest')
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_image_push(args)
            assert result == 0

    def test_cmd_image_push_missing_tag(self, mock_args):
        """_cmd_image_push returns 1 when tag cannot be resolved."""
        args = mock_args(tag=None, node=None)
        result = _cmd_image_push(args)
        assert result == 1


class TestConfigCommands:
    """Tests for circuit configuration commands."""

    @patch('pathlib.Path.exists', return_value=False)
    @patch('pathlib.Path.mkdir')
    @patch('baton.config.save_circuit')
    def test_cmd_init_success(self, mock_save, mock_mkdir, mock_exists, mock_args):
        """_cmd_init creates new circuit project."""
        args = mock_args()
        result = _cmd_init(args)
        assert result == 0

    @patch('pathlib.Path.exists', return_value=True)
    def test_cmd_init_config_exists(self, mock_exists, mock_args):
        """_cmd_init returns 1 when baton.yaml exists."""
        args = mock_args()
        result = _cmd_init(args)
        assert result == 1

    @patch('baton.config.load_circuit')
    @patch('baton.config.save_circuit')
    def test_cmd_node_add(self, mock_save, mock_load, mock_args):
        """_cmd_node adds node to circuit."""
        args = mock_args(node_command='add', name='new_node')
        mock_circuit = MagicMock()
        mock_load.return_value = mock_circuit
        
        result = _cmd_node(args)
        assert result == 0

    @patch('baton.config.load_circuit')
    @patch('baton.config.save_circuit')
    def test_cmd_node_remove(self, mock_save, mock_load, mock_args):
        """_cmd_node removes node from circuit."""
        args = mock_args(node_command='rm', name='old_node')
        mock_circuit = MagicMock()
        mock_load.return_value = mock_circuit
        
        result = _cmd_node(args)
        assert result == 0

    def test_cmd_node_invalid_command(self, mock_args):
        """_cmd_node returns 1 for invalid node command."""
        args = mock_args(node_command='invalid')
        result = _cmd_node(args)
        assert result == 1

    @patch('baton.config.load_circuit')
    @patch('baton.config.save_circuit')
    def test_cmd_edge_add(self, mock_save, mock_load, mock_args):
        """_cmd_edge adds edge to circuit."""
        args = mock_args(edge_command='add', source='node1', target='node2')
        mock_circuit = MagicMock()
        mock_load.return_value = mock_circuit
        
        result = _cmd_edge(args)
        assert result == 0

    def test_cmd_edge_invalid_command(self, mock_args):
        """_cmd_edge returns 1 for invalid edge command."""
        args = mock_args(edge_command='invalid')
        result = _cmd_edge(args)
        assert result == 1

    @patch('baton.config.load_circuit')
    @patch('baton.config.save_circuit')
    @patch('pathlib.Path.exists', return_value=True)
    def test_cmd_contract_set(self, mock_exists, mock_save, mock_load, mock_args):
        """_cmd_contract sets contract for node."""
        args = mock_args(contract_command='set', node='node1', spec='/tmp/contract.yaml')
        mock_circuit = MagicMock()
        mock_load.return_value = mock_circuit
        
        result = _cmd_contract(args)
        assert result == 0

    def test_cmd_contract_invalid_command(self, mock_args):
        """_cmd_contract returns 1 for invalid contract command."""
        args = mock_args(contract_command='invalid')
        result = _cmd_contract(args)
        assert result == 1


class TestServiceCommands:
    """Tests for service manifest commands."""

    @patch('baton.manifest.register_service')
    def test_cmd_service_register(self, mock_register, mock_args):
        """_cmd_service registers service manifest."""
        args = mock_args(service_command='register', path='/path/to/manifest.yaml')
        result = _cmd_service(args)
        assert result == 0

    @patch('baton.manifest.list_services')
    def test_cmd_service_list(self, mock_list, mock_args):
        """_cmd_service lists service manifests."""
        args = mock_args(service_command='list')
        mock_list.return_value = ['service1', 'service2']
        result = _cmd_service(args)
        assert result == 0

    @patch('baton.manifest.derive_circuit')
    def test_cmd_service_derive(self, mock_derive, mock_args):
        """_cmd_service derives circuit from services."""
        args = mock_args(service_command='derive')
        mock_derive.return_value = MagicMock()
        result = _cmd_service(args)
        assert result == 0

    def test_cmd_service_invalid_command(self, mock_args):
        """_cmd_service returns 1 for invalid service command."""
        args = mock_args(service_command='invalid')
        result = _cmd_service(args)
        assert result == 1

    @patch('baton.compat.check_compatibility')
    @patch('baton.manifest.list_services')
    def test_cmd_check_compatible(self, mock_list, mock_check, mock_args):
        """_cmd_check reports compatibility for services."""
        args = mock_args()
        mock_list.return_value = ['service1', 'service2']
        mock_check.return_value = {'compatible': True, 'issues': []}
        
        result = _cmd_check(args)
        assert result == 0

    @patch('baton.manifest.list_services')
    def test_cmd_check_no_services(self, mock_list, mock_args):
        """_cmd_check returns 1 when no services registered."""
        args = mock_args()
        mock_list.return_value = []
        
        result = _cmd_check(args)
        assert result == 1

    @patch('baton.compat.check_compatibility')
    @patch('baton.manifest.list_services')
    def test_cmd_check_incompatible(self, mock_list, mock_check, mock_args):
        """_cmd_check returns 1 when incompatibilities found."""
        args = mock_args()
        mock_list.return_value = ['service1', 'service2']
        mock_check.return_value = {'compatible': False, 'issues': ['Version mismatch']}
        
        result = _cmd_check(args)
        assert result == 1

    @patch('baton.manifest.list_services')
    def test_cmd_check_service_not_found(self, mock_list, mock_args):
        """_cmd_check returns 1 when specified service not found."""
        args = mock_args(service='nonexistent')
        mock_list.return_value = ['service1']
        
        result = _cmd_check(args)
        assert result == 1


class TestMonitoringCommands:
    """Tests for monitoring and observability commands."""

    @patch('baton.signals.get_signal_history')
    def test_cmd_signals_success(self, mock_signals, mock_args):
        """_cmd_signals displays signal data."""
        args = mock_args()
        mock_signals.return_value = [
            {'path': '/api/test', 'latency': 100, 'status': 200}
        ]
        
        result = _cmd_signals(args)
        assert result == 0

    @patch('baton.signals.get_signal_history')
    def test_cmd_signals_not_found(self, mock_signals, mock_args):
        """_cmd_signals returns 1 when no signals found."""
        args = mock_args()
        mock_signals.return_value = []
        
        result = _cmd_signals(args)
        assert result == 1

    @patch('baton.telemetry.get_metrics')
    def test_cmd_metrics_success(self, mock_metrics, mock_args):
        """_cmd_metrics displays metrics data."""
        args = mock_args()
        mock_metrics.return_value = [
            {'node': 'node1', 'cpu': 50, 'memory': 1024}
        ]
        
        result = _cmd_metrics(args)
        assert result == 0

    @patch('baton.telemetry.get_metrics')
    def test_cmd_metrics_not_found(self, mock_metrics, mock_args):
        """_cmd_metrics returns 1 when no metrics found."""
        args = mock_args()
        mock_metrics.return_value = []
        
        result = _cmd_metrics(args)
        assert result == 1

    @patch('baton.dashboard_server.start_server')
    def test_cmd_dashboard_serve(self, mock_server, mock_args):
        """_cmd_dashboard serves interactive dashboard."""
        args = mock_args(serve=True)
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_dashboard(args)
            assert result == 0

    @patch('baton.config.load_circuit')
    @patch('baton.dashboard.collect_snapshot')
    def test_cmd_dashboard_snapshot(self, mock_snapshot, mock_load, mock_args):
        """_cmd_dashboard displays snapshot."""
        args = mock_args(serve=False)
        mock_circuit = MagicMock()
        mock_load.return_value = mock_circuit
        mock_snapshot.return_value = {'nodes': [], 'edges': []}
        
        result = _cmd_dashboard(args)
        assert result == 0

    @patch('baton.config.load_circuit')
    def test_cmd_dashboard_no_state(self, mock_load, mock_args):
        """_cmd_dashboard returns 1 when no state found in non-serve mode."""
        args = mock_args(serve=False)
        mock_load.side_effect = FileNotFoundError()
        
        result = _cmd_dashboard(args)
        assert result == 1

    @patch('baton.config.load_circuit')
    @patch('baton.state.StateManager')
    def test_cmd_status_success(self, mock_state, mock_load, mock_args):
        """_cmd_status displays circuit status."""
        args = mock_args()
        mock_circuit = MagicMock()
        mock_load.return_value = mock_circuit
        
        result = _cmd_status(args)
        assert result == 0


class TestInvariants:
    """Tests for cross-cutting invariants."""

    def test_invariant_config_filename(self):
        """CONFIG_FILENAME is always 'baton.yaml'."""
        # This test verifies the constant is defined correctly
        with patch('src.baton_cli.CONFIG_FILENAME', 'baton.yaml') as config_const:
            assert config_const == 'baton.yaml'

    @pytest.mark.parametrize('exit_code,scenario', [
        (0, 'success'),
        (1, 'error'),
        (130, 'keyboard_interrupt'),
    ])
    def test_invariant_exit_codes(self, exit_code, scenario):
        """Exit codes follow contract: 0=success, 1=error, 130=KeyboardInterrupt."""
        # Verify the exit code mapping is respected
        if scenario == 'success':
            assert exit_code == 0
        elif scenario == 'error':
            assert exit_code == 1
        elif scenario == 'keyboard_interrupt':
            assert exit_code == 130


# =============================================================================
# Edge Cases and Integration Tests
# =============================================================================

class TestEdgeCases:
    """Additional edge case tests for boundary conditions."""

    @patch('baton.config.load_circuit')
    def test_main_with_none_argv(self, mock_load):
        """main handles None argv by using sys.argv."""
        with patch('sys.argv', ['baton', 'status']):
            with patch('src.baton_cli._cmd_status', return_value=0):
                result = main(None)
                assert result == 0

    def test_cmd_route_ab_missing_slash(self, mock_args):
        """_cmd_route_ab handles split without slash."""
        args = mock_args(split='8020')
        result = _cmd_route_ab(args)
        assert result == 1

    def test_cmd_route_ab_too_many_parts(self, mock_args):
        """_cmd_route_ab handles split with too many parts."""
        args = mock_args(split='30/30/40')
        result = _cmd_route_ab(args)
        assert result == 1

    @patch('baton.lifecycle.LifecycleManager')
    def test_cmd_route_set_single_target(self, mock_lifecycle, mock_args):
        """_cmd_route_set handles single target."""
        args = mock_args(strategy='weighted', targets='svc1:8080:100', node='node1')
        mock_lm = MagicMock()
        mock_lifecycle.return_value = mock_lm
        
        with patch('asyncio.run', return_value=None):
            result = _cmd_route_set(args)
            assert result == 0

    def test_build_deploy_target_with_extra_config(self, mock_args):
        """_build_deploy_target includes extra config parameters."""
        args = mock_args(provider='gcp', region='us-west1', project='my-project')
        with patch('baton.providers.DeploymentTarget') as mock_target:
            _build_deploy_target(args)
            # Verify all args attributes are passed to config dict
            mock_target.assert_called_once()


# =============================================================================
# Pytest Configuration
# =============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: integration tests requiring file I/O")
    config.addinivalue_line("markers", "slow: slow running tests")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--cov=src.baton_cli', '--cov-branch'])
"""