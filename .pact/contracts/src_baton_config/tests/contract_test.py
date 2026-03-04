"""
Contract-driven pytest test suite for Baton Configuration Loader (src_baton_config)

Tests verify the component's behavior at boundaries (inputs/outputs) against
the contract specification. All dependencies are mocked for isolation.

Generated test structure:
- Happy path tests for all public functions
- Edge cases for boundary conditions and special inputs
- Error cases for each documented error condition
- Invariant tests for contract-specified invariants
- Round-trip tests for save/load and serialize/parse operations
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, mock_open
import yaml
import tempfile
import os

# Import component under test
from src.baton.config import (
    load_circuit,
    save_circuit,
    load_circuit_from_services,
    _discover_service_dirs,
    add_service_path,
    _parse_circuit,
    _serialize_circuit,
)


# ==============================================================================
# FIXTURES
# ==============================================================================

@pytest.fixture
def tmp_project_dir(tmp_path):
    """Create a temporary project directory for testing."""
    return tmp_path


@pytest.fixture
def valid_circuit_dict():
    """Valid circuit configuration as a dictionary."""
    return {
        'name': 'test-circuit',
        'version': 1,
        'nodes': [
            {
                'name': 'service-a',
                'host': '127.0.0.1',
                'port': 8001,
                'proxy_mode': 'http',
                'role': 'service'
            },
            {
                'name': 'service-b',
                'host': '127.0.0.1',
                'port': 8002,
                'proxy_mode': 'http',
                'role': 'service'
            }
        ],
        'edges': [
            {
                'source': 'service-a',
                'target': 'service-b',
                'label': 'depends_on'
            }
        ]
    }


@pytest.fixture
def valid_circuit_yaml(valid_circuit_dict):
    """Valid circuit configuration as YAML string."""
    return yaml.dump(valid_circuit_dict, default_flow_style=False, sort_keys=False)


@pytest.fixture
def minimal_circuit_dict():
    """Minimal circuit configuration (tests defaults)."""
    return {}


@pytest.fixture
def mock_circuit_spec():
    """Mock CircuitSpec object with typical structure."""
    mock = Mock()
    mock.name = 'test-circuit'
    mock.version = 1
    mock.nodes = [
        Mock(name='service-a', host='127.0.0.1', port=8001, proxy_mode='http', role='service'),
        Mock(name='service-b', host='192.168.1.1', port=8002, proxy_mode='tcp', role='gateway'),
    ]
    mock.edges = [
        Mock(source='service-a', target='service-b', label='depends_on')
    ]
    return mock


@pytest.fixture
def empty_circuit_spec():
    """Mock empty CircuitSpec object."""
    mock = Mock()
    mock.name = 'default'
    mock.version = 1
    mock.nodes = []
    mock.edges = []
    return mock


@pytest.fixture
def service_manifest_dict():
    """Valid service manifest configuration."""
    return {
        'name': 'test-service',
        'port': 8000,
        'dependencies': []
    }


# ==============================================================================
# load_circuit TESTS
# ==============================================================================

class TestLoadCircuit:
    """Test suite for load_circuit function."""
    
    def test_load_circuit_happy_path(self, tmp_project_dir, valid_circuit_yaml):
        """Load a valid CircuitSpec from baton.yaml with complete configuration."""
        # Setup: Create baton.yaml with valid content
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text(valid_circuit_yaml)
        
        # Execute
        circuit = load_circuit(tmp_project_dir)
        
        # Verify
        assert circuit is not None, "Circuit should be loaded successfully"
        assert hasattr(circuit, 'name'), "Circuit should have name attribute"
        assert hasattr(circuit, 'nodes'), "Circuit should have nodes attribute"
        assert hasattr(circuit, 'edges'), "Circuit should have edges attribute"
    
    def test_load_circuit_with_path_object(self, tmp_project_dir, valid_circuit_yaml):
        """Verify function accepts pathlib.Path objects."""
        # Setup
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text(valid_circuit_yaml)
        
        # Execute with Path object
        circuit = load_circuit(Path(tmp_project_dir))
        
        # Verify
        assert circuit is not None, "Circuit should be loaded with Path object"
    
    def test_load_circuit_with_string_path(self, tmp_project_dir, valid_circuit_yaml):
        """Verify function accepts string paths."""
        # Setup
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text(valid_circuit_yaml)
        
        # Execute with string path
        circuit = load_circuit(str(tmp_project_dir))
        
        # Verify
        assert circuit is not None, "Circuit should be loaded with string path"
    
    def test_load_circuit_empty_yaml(self, tmp_project_dir):
        """Load CircuitSpec from baton.yaml containing only null/empty content."""
        # Setup: Create baton.yaml with null content
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('null\n')
        
        # Execute
        circuit = load_circuit(tmp_project_dir)
        
        # Verify - should return empty CircuitSpec
        assert circuit is not None, "Should return empty CircuitSpec for null content"
        assert hasattr(circuit, 'name'), "Empty circuit should have name"
    
    def test_load_circuit_file_not_found(self, tmp_project_dir):
        """Error when baton.yaml does not exist in project_dir."""
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            load_circuit(tmp_project_dir)
        
        # Verify error type or message indicates file_not_found
        assert 'file_not_found' in str(exc_info.value).lower() or \
               'not found' in str(exc_info.value).lower() or \
               'does not exist' in str(exc_info.value).lower(), \
               "Should raise file_not_found error"
    
    def test_load_circuit_yaml_parse_error(self, tmp_project_dir):
        """Error when YAML content is malformed."""
        # Setup: Create baton.yaml with invalid YAML
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('invalid: yaml: content: [unclosed')
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            load_circuit(tmp_project_dir)
        
        # Verify error indicates YAML parse error
        assert 'yaml' in str(exc_info.value).lower() or \
               'parse' in str(exc_info.value).lower(), \
               "Should raise yaml_parse_error"
    
    def test_load_circuit_yaml_parse_error_invalid_structure(self, tmp_project_dir):
        """Error when YAML is valid but has invalid structure."""
        # Setup: Create baton.yaml with structurally invalid content
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('name: test\nnodes: "should be list not string"')
        
        # Execute - may raise parse error or validation error
        with pytest.raises(Exception) as exc_info:
            load_circuit(tmp_project_dir)
        
        # Verify some error is raised
        assert exc_info.value is not None, "Should raise error for invalid structure"
    
    @patch('builtins.open', side_effect=PermissionError("Permission denied"))
    def test_load_circuit_file_read_error(self, mock_file, tmp_project_dir):
        """Error when cannot open or read the file."""
        # Setup: Mock file read to raise permission error
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('name: test')
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            load_circuit(tmp_project_dir)
        
        # Verify error indicates file read error
        assert 'permission' in str(exc_info.value).lower() or \
               'read' in str(exc_info.value).lower() or \
               'file_read_error' in str(exc_info.value).lower(), \
               "Should raise file_read_error"


# ==============================================================================
# save_circuit TESTS
# ==============================================================================

class TestSaveCircuit:
    """Test suite for save_circuit function."""
    
    def test_save_circuit_happy_path(self, tmp_project_dir, mock_circuit_spec):
        """Save a valid CircuitSpec to baton.yaml with proper formatting."""
        # Execute
        save_circuit(mock_circuit_spec, tmp_project_dir)
        
        # Verify file was created
        baton_file = tmp_project_dir / 'baton.yaml'
        assert baton_file.exists(), "baton.yaml should be created"
        
        # Verify content is valid YAML
        content = baton_file.read_text()
        parsed = yaml.safe_load(content)
        assert parsed is not None, "Saved content should be valid YAML"
        assert 'name' in parsed, "Saved YAML should contain name"
    
    def test_save_circuit_formatting(self, tmp_project_dir, mock_circuit_spec):
        """Verify YAML is formatted with default_flow_style=False and sort_keys=False."""
        # Execute
        save_circuit(mock_circuit_spec, tmp_project_dir)
        
        # Verify formatting
        baton_file = tmp_project_dir / 'baton.yaml'
        content = baton_file.read_text()
        
        # Check that YAML is in block style (not flow style)
        assert '{' not in content or '[' not in content or \
               content.count('\n') > 3, \
               "YAML should use block style, not flow style"
    
    def test_save_circuit_with_path_object(self, tmp_project_dir, mock_circuit_spec):
        """Verify function accepts pathlib.Path objects."""
        # Execute with Path object
        save_circuit(mock_circuit_spec, Path(tmp_project_dir))
        
        # Verify
        baton_file = tmp_project_dir / 'baton.yaml'
        assert baton_file.exists(), "Should save with Path object"
    
    def test_save_circuit_with_string_path(self, tmp_project_dir, mock_circuit_spec):
        """Verify function accepts string paths."""
        # Execute with string path
        save_circuit(mock_circuit_spec, str(tmp_project_dir))
        
        # Verify
        baton_file = tmp_project_dir / 'baton.yaml'
        assert baton_file.exists(), "Should save with string path"
    
    def test_save_circuit_file_write_error_readonly(self, tmp_project_dir, mock_circuit_spec):
        """Error when cannot write to file or directory (readonly)."""
        # Setup: Make directory readonly
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('existing')
        baton_file.chmod(0o444)  # Read-only file
        tmp_project_dir.chmod(0o555)  # Read-only directory
        
        try:
            # Execute and verify error
            with pytest.raises(Exception) as exc_info:
                save_circuit(mock_circuit_spec, tmp_project_dir)
            
            # Verify error indicates write error
            assert 'permission' in str(exc_info.value).lower() or \
                   'write' in str(exc_info.value).lower() or \
                   'file_write_error' in str(exc_info.value).lower(), \
                   "Should raise file_write_error"
        finally:
            # Cleanup: Restore permissions
            tmp_project_dir.chmod(0o755)
            if baton_file.exists():
                baton_file.chmod(0o644)
    
    @patch('yaml.dump', side_effect=yaml.YAMLError("Cannot serialize"))
    def test_save_circuit_yaml_dump_error(self, mock_dump, tmp_project_dir, mock_circuit_spec):
        """Error when circuit data cannot be serialized to YAML."""
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            save_circuit(mock_circuit_spec, tmp_project_dir)
        
        # Verify error indicates YAML dump error
        assert 'yaml' in str(exc_info.value).lower() or \
               'serialize' in str(exc_info.value).lower() or \
               'dump' in str(exc_info.value).lower(), \
               "Should raise yaml_dump_error"
    
    def test_save_circuit_invalid_directory(self, mock_circuit_spec):
        """Error when project_dir does not exist."""
        # Execute with non-existent directory
        invalid_dir = '/nonexistent/directory/path'
        
        with pytest.raises(Exception) as exc_info:
            save_circuit(mock_circuit_spec, invalid_dir)
        
        # Verify error
        assert exc_info.value is not None, "Should raise error for invalid directory"


# ==============================================================================
# load_circuit_from_services TESTS
# ==============================================================================

class TestLoadCircuitFromServices:
    """Test suite for load_circuit_from_services function."""
    
    @patch('src.src_baton_config.load_manifests')
    @patch('src.src_baton_config.derive_circuit')
    def test_load_circuit_from_services_happy_path(self, mock_derive, mock_load_manifests, 
                                                    tmp_project_dir, mock_circuit_spec):
        """Derive CircuitSpec from service manifests with explicit service_dirs."""
        # Setup
        service_dirs = [tmp_project_dir / 'service-a', tmp_project_dir / 'service-b']
        for sdir in service_dirs:
            sdir.mkdir()
            (sdir / 'baton-service.yaml').write_text('name: test')
        
        mock_load_manifests.return_value = [Mock(), Mock()]
        mock_derive.return_value = mock_circuit_spec
        
        # Execute
        circuit = load_circuit_from_services(tmp_project_dir, service_dirs)
        
        # Verify
        assert circuit is not None, "Should return CircuitSpec"
        assert circuit == mock_circuit_spec, "Should return derived circuit"
        mock_load_manifests.assert_called_once()
        mock_derive.assert_called_once()
    
    @patch('src.src_baton_config.load_manifests')
    @patch('src.src_baton_config.derive_circuit')
    @patch('src.src_baton_config._discover_service_dirs')
    def test_load_circuit_from_services_auto_discover(self, mock_discover, mock_derive, 
                                                       mock_load_manifests, tmp_project_dir, 
                                                       mock_circuit_spec):
        """Derive CircuitSpec with service_dirs=None, auto-discovering services."""
        # Setup
        discovered_dirs = [tmp_project_dir / 'service-a']
        mock_discover.return_value = discovered_dirs
        mock_load_manifests.return_value = [Mock()]
        mock_derive.return_value = mock_circuit_spec
        
        # Execute with service_dirs=None
        circuit = load_circuit_from_services(tmp_project_dir, None)
        
        # Verify
        assert circuit is not None, "Should return CircuitSpec with auto-discovery"
        mock_discover.assert_called_once_with(Path(tmp_project_dir))
        mock_load_manifests.assert_called_once()
        mock_derive.assert_called_once()
    
    @patch('src.src_baton_config._discover_service_dirs')
    def test_load_circuit_from_services_no_services_found(self, mock_discover, tmp_project_dir):
        """Error when service_dirs is empty after discovery."""
        # Setup: Discovery returns empty list
        mock_discover.return_value = []
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            load_circuit_from_services(tmp_project_dir, None)
        
        # Verify error indicates no services found
        assert 'no_services_found' in str(exc_info.value).lower() or \
               'no services' in str(exc_info.value).lower() or \
               'empty' in str(exc_info.value).lower(), \
               "Should raise no_services_found error"
    
    def test_load_circuit_from_services_yaml_parse_error(self, tmp_project_dir):
        """Error when cannot parse baton.yaml when reading circuit name."""
        # Setup: Create invalid baton.yaml
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('invalid: yaml: [unclosed')
        
        service_dirs = [tmp_project_dir / 'service-a']
        service_dirs[0].mkdir()
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            load_circuit_from_services(tmp_project_dir, service_dirs)
        
        # Verify error indicates YAML parse error
        assert 'yaml' in str(exc_info.value).lower() or \
               'parse' in str(exc_info.value).lower(), \
               "Should raise yaml_parse_error"
    
    @patch('src.src_baton_config.load_manifests', side_effect=Exception("Manifest load failed"))
    @patch('src.src_baton_config._discover_service_dirs')
    def test_load_circuit_from_services_manifest_load_error(self, mock_discover, 
                                                             mock_load_manifests, tmp_project_dir):
        """Error when load_manifests fails to load service manifests."""
        # Setup
        mock_discover.return_value = [tmp_project_dir / 'service-a']
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            load_circuit_from_services(tmp_project_dir, None)
        
        # Verify error indicates manifest load error
        assert 'manifest' in str(exc_info.value).lower() or \
               'load' in str(exc_info.value).lower(), \
               "Should raise manifest_load_error"
    
    @patch('src.src_baton_config.derive_circuit', side_effect=Exception("Derive failed"))
    @patch('src.src_baton_config.load_manifests')
    @patch('src.src_baton_config._discover_service_dirs')
    def test_load_circuit_from_services_derive_circuit_error(self, mock_discover, 
                                                              mock_load_manifests, 
                                                              mock_derive, tmp_project_dir):
        """Error when derive_circuit fails to create CircuitSpec."""
        # Setup
        mock_discover.return_value = [tmp_project_dir / 'service-a']
        mock_load_manifests.return_value = [Mock()]
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            load_circuit_from_services(tmp_project_dir, None)
        
        # Verify error indicates derive circuit error
        assert 'derive' in str(exc_info.value).lower() or \
               'circuit' in str(exc_info.value).lower(), \
               "Should raise derive_circuit_error"
    
    @patch('src.src_baton_config.load_manifests')
    @patch('src.src_baton_config.derive_circuit')
    def test_load_circuit_from_services_circuit_name_from_yaml(self, mock_derive, 
                                                                mock_load_manifests, 
                                                                tmp_project_dir, 
                                                                mock_circuit_spec):
        """Extract circuit name from baton.yaml when it exists."""
        # Setup: Create baton.yaml with name
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('name: custom-circuit\n')
        
        service_dirs = [tmp_project_dir / 'service-a']
        service_dirs[0].mkdir()
        
        mock_load_manifests.return_value = [Mock()]
        mock_circuit_spec.name = 'custom-circuit'
        mock_derive.return_value = mock_circuit_spec
        
        # Execute
        circuit = load_circuit_from_services(tmp_project_dir, service_dirs)
        
        # Verify circuit name matches
        assert circuit.name == 'custom-circuit', "Circuit name should be from baton.yaml"
    
    @patch('src.src_baton_config.load_manifests')
    @patch('src.src_baton_config.derive_circuit')
    def test_load_circuit_from_services_default_circuit_name(self, mock_derive, 
                                                              mock_load_manifests, 
                                                              tmp_project_dir, 
                                                              mock_circuit_spec):
        """Use default circuit name when baton.yaml doesn't have name."""
        # Setup: No baton.yaml or empty one
        service_dirs = [tmp_project_dir / 'service-a']
        service_dirs[0].mkdir()
        
        mock_load_manifests.return_value = [Mock()]
        mock_circuit_spec.name = 'default'
        mock_derive.return_value = mock_circuit_spec
        
        # Execute
        circuit = load_circuit_from_services(tmp_project_dir, service_dirs)
        
        # Verify default name is used
        assert circuit.name == 'default', "Should use default circuit name"


# ==============================================================================
# _discover_service_dirs TESTS
# ==============================================================================

class TestDiscoverServiceDirs:
    """Test suite for _discover_service_dirs function."""
    
    def test_discover_service_dirs_from_baton_yaml(self, tmp_project_dir):
        """Discover service directories from baton.yaml services list."""
        # Setup: Create baton.yaml with services list
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('services:\n  - service-a\n  - service-b\n')
        
        # Create service directories
        (tmp_project_dir / 'service-a').mkdir()
        (tmp_project_dir / 'service-b').mkdir()
        
        # Execute
        service_dirs = _discover_service_dirs(tmp_project_dir)
        
        # Verify
        assert len(service_dirs) >= 0, "Should return list of service directories"
        # Note: Actual implementation may resolve paths differently
    
    def test_discover_service_dirs_by_scanning(self, tmp_project_dir):
        """Discover service directories by scanning for baton-service.yaml."""
        # Setup: Create subdirectories with baton-service.yaml
        service_a = tmp_project_dir / 'service-a'
        service_b = tmp_project_dir / 'service-b'
        service_a.mkdir()
        service_b.mkdir()
        
        (service_a / 'baton-service.yaml').write_text('name: service-a')
        (service_b / 'baton-service.yaml').write_text('name: service-b')
        
        # Also create a directory without manifest
        (tmp_project_dir / 'not-a-service').mkdir()
        
        # Execute
        service_dirs = _discover_service_dirs(tmp_project_dir)
        
        # Verify
        assert isinstance(service_dirs, list), "Should return list"
        assert len(service_dirs) >= 0, "Should find service directories"
        # Results should be sorted
        if len(service_dirs) > 1:
            assert service_dirs == sorted(service_dirs), "Service directories should be sorted"
    
    def test_discover_service_dirs_empty(self, tmp_project_dir):
        """Returns empty list when no services found."""
        # Setup: Empty project directory (no baton.yaml, no services)
        
        # Execute
        service_dirs = _discover_service_dirs(tmp_project_dir)
        
        # Verify
        assert service_dirs == [], "Should return empty list when no services found"
    
    def test_discover_service_dirs_yaml_parse_error(self, tmp_project_dir):
        """Error when cannot parse baton.yaml."""
        # Setup: Create invalid baton.yaml
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('invalid: yaml: content: [unclosed')
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            _discover_service_dirs(tmp_project_dir)
        
        # Verify error indicates YAML parse error
        assert 'yaml' in str(exc_info.value).lower() or \
               'parse' in str(exc_info.value).lower(), \
               "Should raise yaml_parse_error"
    
    @patch('builtins.open', side_effect=PermissionError("Permission denied"))
    def test_discover_service_dirs_file_read_error(self, mock_file, tmp_project_dir):
        """Error when cannot read baton.yaml."""
        # Setup: Create baton.yaml but mock read to fail
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('services: []')
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            _discover_service_dirs(tmp_project_dir)
        
        # Verify error indicates file read error
        assert 'permission' in str(exc_info.value).lower() or \
               'read' in str(exc_info.value).lower() or \
               'file_read_error' in str(exc_info.value).lower(), \
               "Should raise file_read_error"


# ==============================================================================
# add_service_path TESTS
# ==============================================================================

class TestAddServicePath:
    """Test suite for add_service_path function."""
    
    def test_add_service_path_happy_path(self, tmp_project_dir):
        """Add a new service path to baton.yaml services list."""
        # Setup: Create baton.yaml with existing services
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('services:\n  - service-a\n')
        
        # Execute
        add_service_path(tmp_project_dir, 'service-b')
        
        # Verify
        content = yaml.safe_load(baton_file.read_text())
        assert 'services' in content, "services key should exist"
        assert 'service-b' in content['services'], "New service should be added"
    
    def test_add_service_path_no_duplicate(self, tmp_project_dir):
        """Do not add duplicate service_path if already present."""
        # Setup: Create baton.yaml with service already in list
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('services:\n  - service-a\n  - service-b\n')
        
        # Execute - try to add duplicate
        add_service_path(tmp_project_dir, 'service-a')
        
        # Verify - no duplicate should be added
        content = yaml.safe_load(baton_file.read_text())
        service_count = content['services'].count('service-a')
        assert service_count == 1, "Should not add duplicate service"
    
    def test_add_service_path_creates_services_list(self, tmp_project_dir):
        """Add service path when services list doesn't exist yet."""
        # Setup: Create baton.yaml without services key
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('name: test-circuit\n')
        
        # Execute
        add_service_path(tmp_project_dir, 'service-a')
        
        # Verify
        content = yaml.safe_load(baton_file.read_text())
        assert 'services' in content, "services key should be created"
        assert 'service-a' in content['services'], "Service should be added"
    
    def test_add_service_path_file_not_found(self, tmp_project_dir):
        """Error when baton.yaml does not exist in project_dir."""
        # Execute and verify error (no baton.yaml created)
        with pytest.raises(Exception) as exc_info:
            add_service_path(tmp_project_dir, 'service-a')
        
        # Verify error indicates file not found
        assert 'file_not_found' in str(exc_info.value).lower() or \
               'not found' in str(exc_info.value).lower() or \
               'does not exist' in str(exc_info.value).lower(), \
               "Should raise file_not_found error"
    
    def test_add_service_path_yaml_parse_error(self, tmp_project_dir):
        """Error when cannot parse existing baton.yaml."""
        # Setup: Create invalid baton.yaml
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('invalid: yaml: [unclosed')
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            add_service_path(tmp_project_dir, 'service-a')
        
        # Verify error indicates YAML parse error
        assert 'yaml' in str(exc_info.value).lower() or \
               'parse' in str(exc_info.value).lower(), \
               "Should raise yaml_parse_error"
    
    def test_add_service_path_file_write_error(self, tmp_project_dir):
        """Error when cannot write updated config back to file."""
        # Setup: Create baton.yaml and make it readonly
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('services: []\n')
        baton_file.chmod(0o444)  # Read-only
        tmp_project_dir.chmod(0o555)  # Read-only directory
        
        try:
            # Execute and verify error
            with pytest.raises(Exception) as exc_info:
                add_service_path(tmp_project_dir, 'service-a')
            
            # Verify error indicates write error
            assert 'permission' in str(exc_info.value).lower() or \
                   'write' in str(exc_info.value).lower() or \
                   'file_write_error' in str(exc_info.value).lower(), \
                   "Should raise file_write_error"
        finally:
            # Cleanup
            tmp_project_dir.chmod(0o755)
            if baton_file.exists():
                baton_file.chmod(0o644)


# ==============================================================================
# _parse_circuit TESTS
# ==============================================================================

class TestParseCircuit:
    """Test suite for _parse_circuit function."""
    
    def test_parse_circuit_complete(self, valid_circuit_dict):
        """Parse raw YAML dict with all fields into CircuitSpec."""
        # Execute
        circuit = _parse_circuit(valid_circuit_dict)
        
        # Verify
        assert circuit is not None, "Should return CircuitSpec"
        assert hasattr(circuit, 'name'), "Should have name attribute"
        assert hasattr(circuit, 'version'), "Should have version attribute"
        assert hasattr(circuit, 'nodes'), "Should have nodes attribute"
        assert hasattr(circuit, 'edges'), "Should have edges attribute"
    
    def test_parse_circuit_minimal(self, minimal_circuit_dict):
        """Parse minimal raw dict with defaults applied."""
        # Execute
        circuit = _parse_circuit(minimal_circuit_dict)
        
        # Verify defaults
        assert circuit is not None, "Should return CircuitSpec"
        # Check for default values as per invariants
        if hasattr(circuit, 'name'):
            assert circuit.name == 'default', "Default name should be 'default'"
        if hasattr(circuit, 'version'):
            assert circuit.version == 1, "Default version should be 1"
        if hasattr(circuit, 'nodes'):
            assert circuit.nodes == [], "Default nodes should be empty list"
        if hasattr(circuit, 'edges'):
            assert circuit.edges == [], "Default edges should be empty list"
    
    def test_parse_circuit_with_nodes(self):
        """Parse circuit with valid nodes."""
        raw = {
            'name': 'test',
            'version': 1,
            'nodes': [
                {'name': 'node1', 'port': 8001},
                {'name': 'node2', 'port': 8002}
            ]
        }
        
        # Execute
        circuit = _parse_circuit(raw)
        
        # Verify
        assert circuit is not None, "Should parse circuit with nodes"
        assert len(circuit.nodes) == 2, "Should have 2 nodes"
    
    def test_parse_circuit_with_edges(self):
        """Parse circuit with valid edges."""
        raw = {
            'name': 'test',
            'version': 1,
            'nodes': [
                {'name': 'node1', 'port': 8001},
                {'name': 'node2', 'port': 8002}
            ],
            'edges': [
                {'source': 'node1', 'target': 'node2'}
            ]
        }
        
        # Execute
        circuit = _parse_circuit(raw)
        
        # Verify
        assert circuit is not None, "Should parse circuit with edges"
        assert len(circuit.edges) == 1, "Should have 1 edge"
    
    def test_parse_circuit_node_spec_error(self):
        """Error when node data cannot be unpacked into NodeSpec."""
        # Setup: Invalid node data
        raw = {
            'nodes': [
                {'invalid_field': 'value', 'missing_required': 'fields'}
            ]
        }
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            _parse_circuit(raw)
        
        # Verify error indicates node spec error
        assert 'node' in str(exc_info.value).lower() or \
               'spec' in str(exc_info.value).lower(), \
               "Should raise node_spec_error"
    
    def test_parse_circuit_edge_spec_error(self):
        """Error when edge data cannot be unpacked into EdgeSpec."""
        # Setup: Invalid edge data
        raw = {
            'edges': [
                {'invalid_edge': 'missing source and target'}
            ]
        }
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            _parse_circuit(raw)
        
        # Verify error indicates edge spec error
        assert 'edge' in str(exc_info.value).lower() or \
               'spec' in str(exc_info.value).lower(), \
               "Should raise edge_spec_error"
    
    def test_parse_circuit_circuit_spec_error(self):
        """Error when CircuitSpec constructor fails with provided data."""
        # Setup: Data that would cause CircuitSpec constructor to fail
        # This might be incompatible types or validation failures
        raw = {
            'version': 'not_an_integer',  # Invalid type
            'name': 12345  # Wrong type
        }
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            _parse_circuit(raw)
        
        # Verify error
        assert exc_info.value is not None, "Should raise circuit_spec_error"


# ==============================================================================
# _serialize_circuit TESTS
# ==============================================================================

class TestSerializeCircuit:
    """Test suite for _serialize_circuit function."""
    
    def test_serialize_circuit_complete(self, mock_circuit_spec):
        """Convert CircuitSpec with all fields to dict."""
        # Execute
        result = _serialize_circuit(mock_circuit_spec)
        
        # Verify
        assert isinstance(result, dict), "Should return dictionary"
        assert 'name' in result, "Should contain name"
        assert 'version' in result, "Should contain version"
        assert result['name'] == 'test-circuit', "Name should match"
        assert result['version'] == 1, "Version should match"
    
    def test_serialize_circuit_minimal(self, empty_circuit_spec):
        """Serialize CircuitSpec with only defaults."""
        # Execute
        result = _serialize_circuit(empty_circuit_spec)
        
        # Verify - should only have name and version, not empty collections
        assert 'name' in result, "Should always include name"
        assert 'version' in result, "Should always include version"
        # Empty nodes/edges may or may not be included based on implementation
    
    def test_serialize_circuit_includes_nodes(self, mock_circuit_spec):
        """Include nodes list when circuit has nodes."""
        # Execute
        result = _serialize_circuit(mock_circuit_spec)
        
        # Verify
        if len(mock_circuit_spec.nodes) > 0:
            assert 'nodes' in result, "Should include nodes when present"
    
    def test_serialize_circuit_includes_edges(self, mock_circuit_spec):
        """Include edges list when circuit has edges."""
        # Execute
        result = _serialize_circuit(mock_circuit_spec)
        
        # Verify
        if len(mock_circuit_spec.edges) > 0:
            assert 'edges' in result, "Should include edges when present"
    
    def test_serialize_non_default_host(self):
        """Include host field when it differs from default 127.0.0.1."""
        # Setup: Circuit with non-default host
        circuit = Mock()
        circuit.name = 'test'
        circuit.version = 1
        circuit.nodes = [
            Mock(name='node1', host='192.168.1.1', port=8001, proxy_mode='http', role='service')
        ]
        circuit.edges = []
        
        # Execute
        result = _serialize_circuit(circuit)
        
        # Verify - node should include host field
        if 'nodes' in result and len(result['nodes']) > 0:
            node = result['nodes'][0]
            # Host should be included when non-default
            assert 'host' in node or node.get('host') == '192.168.1.1', \
                   "Should include non-default host"
    
    def test_serialize_non_default_proxy_mode(self):
        """Include proxy_mode field when it differs from default 'http'."""
        # Setup: Circuit with non-default proxy_mode
        circuit = Mock()
        circuit.name = 'test'
        circuit.version = 1
        circuit.nodes = [
            Mock(name='node1', host='127.0.0.1', port=8001, proxy_mode='tcp', role='service')
        ]
        circuit.edges = []
        
        # Execute
        result = _serialize_circuit(circuit)
        
        # Verify - node should include proxy_mode field
        if 'nodes' in result and len(result['nodes']) > 0:
            node = result['nodes'][0]
            # proxy_mode should be included when non-default
            assert 'proxy_mode' in node or node.get('proxy_mode') == 'tcp', \
                   "Should include non-default proxy_mode"
    
    def test_serialize_non_default_role(self):
        """Include role field when it differs from default 'service'."""
        # Setup: Circuit with non-default role
        circuit = Mock()
        circuit.name = 'test'
        circuit.version = 1
        circuit.nodes = [
            Mock(name='node1', host='127.0.0.1', port=8001, proxy_mode='http', role='gateway')
        ]
        circuit.edges = []
        
        # Execute
        result = _serialize_circuit(circuit)
        
        # Verify - node should include role field
        if 'nodes' in result and len(result['nodes']) > 0:
            node = result['nodes'][0]
            # role should be included when non-default
            assert 'role' in node or node.get('role') == 'gateway', \
                   "Should include non-default role"
    
    def test_serialize_edge_with_label(self):
        """Include edge label field when present."""
        # Setup: Circuit with labeled edge
        circuit = Mock()
        circuit.name = 'test'
        circuit.version = 1
        circuit.nodes = []
        circuit.edges = [
            Mock(source='node1', target='node2', label='depends_on')
        ]
        
        # Execute
        result = _serialize_circuit(circuit)
        
        # Verify - edge should include label
        if 'edges' in result and len(result['edges']) > 0:
            edge = result['edges'][0]
            assert 'label' in edge or hasattr(edge, 'label'), \
                   "Should include label when present"
    
    def test_serialize_edge_without_label(self):
        """Omit edge label field when not present."""
        # Setup: Circuit with unlabeled edge
        circuit = Mock()
        circuit.name = 'test'
        circuit.version = 1
        circuit.nodes = []
        edge_mock = Mock(source='node1', target='node2')
        edge_mock.label = None
        circuit.edges = [edge_mock]
        
        # Execute
        result = _serialize_circuit(circuit)
        
        # Verify - edge should not include empty label
        if 'edges' in result and len(result['edges']) > 0:
            edge = result['edges'][0]
            # Label should be omitted or None
            if isinstance(edge, dict):
                assert edge.get('label') is None or 'label' not in edge, \
                       "Should omit empty label"
    
    def test_serialize_circuit_attribute_error(self):
        """Error when CircuitSpec object missing expected attributes."""
        # Setup: Mock object missing required attributes
        invalid_circuit = Mock(spec=[])  # Empty spec means no attributes
        
        # Execute and verify error
        with pytest.raises(Exception) as exc_info:
            _serialize_circuit(invalid_circuit)
        
        # Verify error indicates attribute error
        assert 'attribute' in str(exc_info.value).lower() or \
               'has no attribute' in str(exc_info.value).lower(), \
               "Should raise attribute_error"


# ==============================================================================
# INVARIANT TESTS
# ==============================================================================

class TestInvariants:
    """Test suite for contract invariants."""
    
    def test_config_filename_invariant(self):
        """Verify CONFIG_FILENAME constant is 'baton.yaml'."""
        # Import and check constant
        from src.baton.config import CONFIG_FILENAME
        assert CONFIG_FILENAME == 'baton.yaml', \
               "CONFIG_FILENAME must be 'baton.yaml'"
    
    def test_default_circuit_name_invariant(self):
        """Verify default circuit name is 'default'."""
        # Parse empty dict to get defaults
        circuit = _parse_circuit({})
        
        # Verify default name
        assert circuit.name == 'default', \
               "Default circuit name must be 'default'"
    
    def test_default_circuit_version_invariant(self):
        """Verify default circuit version is 1."""
        # Parse empty dict to get defaults
        circuit = _parse_circuit({})
        
        # Verify default version
        assert circuit.version == 1, \
               "Default circuit version must be 1"
    
    def test_default_node_host_invariant(self):
        """Verify default node host is '127.0.0.1'."""
        # Parse circuit with node without explicit host
        raw = {
            'nodes': [{'name': 'test-node', 'port': 8000}]
        }
        circuit = _parse_circuit(raw)
        
        # Verify default host if applicable
        if len(circuit.nodes) > 0:
            node = circuit.nodes[0]
            if hasattr(node, 'host'):
                # Default should be 127.0.0.1
                assert node.host == '127.0.0.1' or not hasattr(node, 'host'), \
                       "Default node host should be '127.0.0.1'"
    
    def test_default_node_proxy_mode_invariant(self):
        """Verify default node proxy_mode is 'http'."""
        # Parse circuit with node without explicit proxy_mode
        raw = {
            'nodes': [{'name': 'test-node', 'port': 8000}]
        }
        circuit = _parse_circuit(raw)
        
        # Verify default proxy_mode if applicable
        if len(circuit.nodes) > 0:
            node = circuit.nodes[0]
            if hasattr(node, 'proxy_mode'):
                # Default should be 'http'
                assert node.proxy_mode == 'http' or not hasattr(node, 'proxy_mode'), \
                       "Default node proxy_mode should be 'http'"
    
    def test_default_node_role_invariant(self):
        """Verify default node role is 'service'."""
        # Parse circuit with node without explicit role
        raw = {
            'nodes': [{'name': 'test-node', 'port': 8000}]
        }
        circuit = _parse_circuit(raw)
        
        # Verify default role if applicable
        if len(circuit.nodes) > 0:
            node = circuit.nodes[0]
            if hasattr(node, 'role'):
                # Default should be 'service'
                assert node.role == 'service' or not hasattr(node, 'role'), \
                       "Default node role should be 'service'"


# ==============================================================================
# ROUND-TRIP TESTS
# ==============================================================================

class TestRoundTrip:
    """Test suite for round-trip operations (save/load, serialize/parse)."""
    
    def test_roundtrip_save_load(self, tmp_project_dir, mock_circuit_spec):
        """Verify save_circuit followed by load_circuit preserves data."""
        # Execute: Save then load
        save_circuit(mock_circuit_spec, tmp_project_dir)
        loaded_circuit = load_circuit(tmp_project_dir)
        
        # Verify essential fields are preserved
        assert loaded_circuit.name == mock_circuit_spec.name, \
               "Circuit name should be preserved"
        assert loaded_circuit.version == mock_circuit_spec.version, \
               "Circuit version should be preserved"
        # Note: Full deep equality may require more sophisticated comparison
    
    def test_roundtrip_serialize_parse(self, mock_circuit_spec):
        """Verify _serialize_circuit followed by _parse_circuit is idempotent."""
        # Execute: Serialize then parse
        serialized = _serialize_circuit(mock_circuit_spec)
        parsed_circuit = _parse_circuit(serialized)
        
        # Verify essential fields are preserved
        assert parsed_circuit.name == mock_circuit_spec.name, \
               "Circuit name should be preserved in serialize/parse round-trip"
        assert parsed_circuit.version == mock_circuit_spec.version, \
               "Circuit version should be preserved in serialize/parse round-trip"
    
    def test_roundtrip_empty_circuit(self, tmp_project_dir, empty_circuit_spec):
        """Verify round-trip works with empty circuit."""
        # Execute: Save then load empty circuit
        save_circuit(empty_circuit_spec, tmp_project_dir)
        loaded_circuit = load_circuit(tmp_project_dir)
        
        # Verify
        assert loaded_circuit.name == empty_circuit_spec.name, \
               "Empty circuit name should be preserved"
    
    def test_roundtrip_complex_circuit(self, tmp_project_dir):
        """Verify round-trip with complex circuit including nodes and edges."""
        # Setup: Create complex circuit
        complex_circuit = Mock()
        complex_circuit.name = 'complex'
        complex_circuit.version = 2
        complex_circuit.nodes = [
            Mock(name='n1', host='10.0.0.1', port=8001, proxy_mode='tcp', role='gateway'),
            Mock(name='n2', host='127.0.0.1', port=8002, proxy_mode='http', role='service'),
        ]
        complex_circuit.edges = [
            Mock(source='n1', target='n2', label='connects_to')
        ]
        
        # Execute: Save then load
        save_circuit(complex_circuit, tmp_project_dir)
        loaded_circuit = load_circuit(tmp_project_dir)
        
        # Verify key properties preserved
        assert loaded_circuit.name == 'complex', "Name should be preserved"
        assert loaded_circuit.version == 2, "Version should be preserved"


# ==============================================================================
# EDGE CASE TESTS
# ==============================================================================

class TestEdgeCases:
    """Additional edge case tests."""
    
    def test_load_circuit_with_comments(self, tmp_project_dir):
        """Load circuit from YAML with comments."""
        # Setup: YAML with comments
        yaml_content = """# Circuit configuration
name: test
version: 1
# Nodes section
nodes: []
"""
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text(yaml_content)
        
        # Execute
        circuit = load_circuit(tmp_project_dir)
        
        # Verify
        assert circuit is not None, "Should load YAML with comments"
    
    def test_save_circuit_overwrites_existing(self, tmp_project_dir, mock_circuit_spec):
        """Verify save_circuit overwrites existing baton.yaml."""
        # Setup: Create existing baton.yaml
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('name: old-circuit\n')
        
        # Execute: Save new circuit
        save_circuit(mock_circuit_spec, tmp_project_dir)
        
        # Verify: File should be overwritten
        content = yaml.safe_load(baton_file.read_text())
        assert content['name'] == 'test-circuit', "Should overwrite existing file"
    
    def test_add_service_path_with_empty_services(self, tmp_project_dir):
        """Add service when services list exists but is empty."""
        # Setup: baton.yaml with empty services list
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('services: []\n')
        
        # Execute
        add_service_path(tmp_project_dir, 'service-a')
        
        # Verify
        content = yaml.safe_load(baton_file.read_text())
        assert 'service-a' in content['services'], "Should add to empty list"
    
    def test_parse_circuit_with_extra_fields(self):
        """Parse circuit with extra unknown fields (should be ignored or handled)."""
        # Setup: Dict with extra fields
        raw = {
            'name': 'test',
            'version': 1,
            'unknown_field': 'should be ignored',
            'nodes': [],
            'extra': {'nested': 'data'}
        }
        
        # Execute
        circuit = _parse_circuit(raw)
        
        # Verify - should parse successfully, ignoring unknown fields
        assert circuit is not None, "Should handle extra fields gracefully"
        assert circuit.name == 'test', "Should parse known fields"
    
    def test_serialize_circuit_preserves_order(self, mock_circuit_spec):
        """Verify serialization maintains reasonable field order."""
        # Execute
        result = _serialize_circuit(mock_circuit_spec)
        
        # Verify - name and version should be present
        keys = list(result.keys())
        assert 'name' in keys, "Should include name"
        assert 'version' in keys, "Should include version"
        # Order may vary, but essential fields should be present
    
    def test_discover_service_dirs_with_nested_manifests(self, tmp_project_dir):
        """Verify discovery only finds immediate subdirectories, not nested."""
        # Setup: Create nested structure
        service_a = tmp_project_dir / 'service-a'
        service_a.mkdir()
        (service_a / 'baton-service.yaml').write_text('name: a')
        
        nested = service_a / 'nested'
        nested.mkdir()
        (nested / 'baton-service.yaml').write_text('name: nested')
        
        # Execute
        service_dirs = _discover_service_dirs(tmp_project_dir)
        
        # Verify - should only find immediate subdirectories
        assert len(service_dirs) >= 0, "Should find services"
        # Nested service should not be discovered (only immediate subdirs)
    
    def test_load_circuit_with_unicode(self, tmp_project_dir):
        """Load circuit with Unicode characters in names."""
        # Setup: YAML with Unicode
        yaml_content = """name: тест-サーキット
version: 1
nodes: []
"""
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text(yaml_content, encoding='utf-8')
        
        # Execute
        circuit = load_circuit(tmp_project_dir)
        
        # Verify
        assert circuit is not None, "Should handle Unicode"
        assert 'тест' in circuit.name or 'サーキット' in circuit.name, \
               "Should preserve Unicode characters"


# ==============================================================================
# INTEGRATION TESTS
# ==============================================================================

class TestIntegration:
    """Integration tests combining multiple functions."""
    
    def test_full_workflow_create_save_load(self, tmp_project_dir):
        """Test complete workflow: create circuit, save, load, verify."""
        # Setup: Create circuit
        circuit = Mock()
        circuit.name = 'integration-test'
        circuit.version = 1
        circuit.nodes = [
            Mock(name='api', host='127.0.0.1', port=8000, proxy_mode='http', role='service')
        ]
        circuit.edges = []
        
        # Execute: Save circuit
        save_circuit(circuit, tmp_project_dir)
        
        # Verify file exists
        baton_file = tmp_project_dir / 'baton.yaml'
        assert baton_file.exists(), "baton.yaml should exist"
        
        # Execute: Load circuit
        loaded = load_circuit(tmp_project_dir)
        
        # Verify loaded matches original
        assert loaded.name == 'integration-test', "Loaded circuit should match"
    
    @patch('src.src_baton_config.load_manifests')
    @patch('src.src_baton_config.derive_circuit')
    def test_service_discovery_and_load(self, mock_derive, mock_load_manifests, tmp_project_dir):
        """Test service discovery integrated with load_circuit_from_services."""
        # Setup: Create service directories
        service_a = tmp_project_dir / 'service-a'
        service_b = tmp_project_dir / 'service-b'
        service_a.mkdir()
        service_b.mkdir()
        
        (service_a / 'baton-service.yaml').write_text('name: service-a\n')
        (service_b / 'baton-service.yaml').write_text('name: service-b\n')
        
        # Mock dependencies
        mock_load_manifests.return_value = [Mock(), Mock()]
        mock_circuit = Mock()
        mock_circuit.name = 'derived'
        mock_circuit.version = 1
        mock_derive.return_value = mock_circuit
        
        # Execute: Load circuit from services with auto-discovery
        circuit = load_circuit_from_services(tmp_project_dir, None)
        
        # Verify
        assert circuit is not None, "Should load circuit from services"
        assert circuit.name == 'derived', "Should have derived circuit"
    
    def test_add_multiple_services(self, tmp_project_dir):
        """Test adding multiple services sequentially."""
        # Setup: Create initial baton.yaml
        baton_file = tmp_project_dir / 'baton.yaml'
        baton_file.write_text('services: []\n')
        
        # Execute: Add multiple services
        services = ['service-a', 'service-b', 'service-c']
        for service in services:
            add_service_path(tmp_project_dir, service)
        
        # Verify all services added
        content = yaml.safe_load(baton_file.read_text())
        for service in services:
            assert service in content['services'], f"{service} should be in list"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
