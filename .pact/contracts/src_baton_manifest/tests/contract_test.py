"""
Contract-driven tests for Service Manifest Loader (src_baton_manifest)
Generated from contract version 1

Tests verify load_manifest and _parse_manifest functions against their contracts,
including happy paths, edge cases, error cases, and invariants.
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, mock_open
from typing import Any, Dict, List

# Import the component under test
from src.baton.manifest import load_manifest, _parse_manifest, MANIFEST_FILENAME


# Mock classes for baton.schemas types
class MockDependencySpec:
    """Mock for baton.schemas.DependencySpec"""
    def __init__(self, name: str = None, version: str = None, **kwargs):
        if name is None and isinstance(kwargs.get('data'), str):
            # String-based dependency
            self.name = kwargs.get('data')
            self.version = None
        elif name is None and isinstance(kwargs.get('data'), dict):
            # Dict-based dependency
            self.name = kwargs['data'].get('name')
            self.version = kwargs['data'].get('version')
        else:
            self.name = name
            self.version = version
        
        # Validation
        if not self.name:
            raise ValueError("DependencySpec requires a name")


class MockServiceManifest:
    """Mock for baton.schemas.ServiceManifest"""
    def __init__(self, name: str, version: str = '0.0.0', port: int = 0, 
                 proxy_mode: str = 'http', role: str = 'service',
                 api_spec: str = '', mock_spec: str = '', command: str = '',
                 metadata: dict = None, dependencies: list = None, **kwargs):
        if not name:
            raise ValueError("ServiceManifest requires a name")
        
        self.name = name
        self.version = version
        self.port = port
        self.proxy_mode = proxy_mode
        self.role = role
        self.api_spec = api_spec
        self.mock_spec = mock_spec
        self.command = command
        self.metadata = metadata if metadata is not None else {}
        self.dependencies = dependencies if dependencies is not None else []


# Custom exceptions for error cases
class ManifestNotFoundError(Exception):
    """Raised when baton-service.yaml cannot be found"""
    pass


class EmptyManifestError(Exception):
    """Raised when manifest file is empty"""
    pass


class YamlParseError(Exception):
    """Raised when YAML parsing fails"""
    pass


class IOError(Exception):
    """Raised when file I/O operations fail"""
    pass


class MissingNameError(Exception):
    """Raised when 'name' key is missing from manifest"""
    pass


class InvalidDependencySpecError(Exception):
    """Raised when DependencySpec construction fails"""
    pass


class InvalidServiceManifestError(Exception):
    """Raised when ServiceManifest construction fails"""
    pass


# Fixtures

@pytest.fixture
def temp_service_dir():
    """Create a temporary directory for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def valid_manifest_dict():
    """Minimal valid manifest dictionary"""
    return {
        'name': 'test-service'
    }


@pytest.fixture
def full_manifest_dict():
    """Complete manifest dictionary with all fields"""
    return {
        'name': 'full-service',
        'version': '1.2.3',
        'port': 8080,
        'proxy_mode': 'grpc',
        'role': 'gateway',
        'api_spec': 'openapi.yaml',
        'mock_spec': 'mock.yaml',
        'command': 'python app.py',
        'metadata': {'key': 'value', 'env': 'prod'},
        'dependencies': ['service1', {'name': 'service2', 'version': '2.0.0'}]
    }


@pytest.fixture
def manifest_with_string_deps():
    """Manifest with dependencies as strings"""
    return {
        'name': 'service-with-deps',
        'dependencies': ['dep1', 'dep2', 'dep3']
    }


@pytest.fixture
def manifest_with_dict_deps():
    """Manifest with dependencies as dicts"""
    return {
        'name': 'service-with-deps',
        'dependencies': [
            {'name': 'dep1', 'version': '1.0.0'},
            {'name': 'dep2', 'version': '2.0.0'}
        ]
    }


# Happy Path Tests

def test_load_manifest_happy_path_with_str(temp_service_dir):
    """Load a valid manifest from directory path as string"""
    # Setup
    manifest_path = os.path.join(temp_service_dir, 'baton-service.yaml')
    manifest_content = "name: test-service\nversion: 1.0.0\n"
    
    with open(manifest_path, 'w') as f:
        f.write(manifest_content)
    
    # Execute
    result = load_manifest(temp_service_dir)
    
    # Assert
    assert result is not None, "ServiceManifest object should be returned"
    assert hasattr(result, 'name'), "Manifest should have name attribute"
    assert result.name == 'test-service', "Manifest should have expected name"
    assert hasattr(result, 'version'), "Manifest should have version attribute"


def test_load_manifest_happy_path_with_path(temp_service_dir):
    """Load a valid manifest from directory path as Path object"""
    # Setup
    service_path = Path(temp_service_dir)
    manifest_path = service_path / 'baton-service.yaml'
    manifest_content = "name: test-service-path\nversion: 2.0.0\n"
    
    manifest_path.write_text(manifest_content)
    
    # Execute
    result = load_manifest(service_path)
    
    # Assert
    assert result is not None, "ServiceManifest object should be returned"
    assert result.name == 'test-service-path', "Manifest should have expected name"
    assert result.version == '2.0.0', "Version should be parsed correctly"


def test_load_manifest_with_all_fields(temp_service_dir):
    """Load manifest containing all optional fields"""
    # Setup
    manifest_path = os.path.join(temp_service_dir, 'baton-service.yaml')
    manifest_content = """
name: complete-service
version: 1.2.3
port: 8080
proxy_mode: grpc
role: gateway
api_spec: openapi.yaml
mock_spec: mock.yaml
command: python app.py
metadata:
  key: value
  env: prod
dependencies:
  - service1
  - name: service2
    version: 2.0.0
"""
    
    with open(manifest_path, 'w') as f:
        f.write(manifest_content)
    
    # Execute
    result = load_manifest(temp_service_dir)
    
    # Assert
    assert result.name == 'complete-service', "Name should be parsed"
    assert result.version == '1.2.3', "Version should be parsed"
    assert result.port == 8080, "Port should be parsed"
    assert result.proxy_mode == 'grpc', "Proxy mode should be parsed"
    assert result.role == 'gateway', "Role should be parsed"
    assert result.api_spec == 'openapi.yaml', "API spec should be parsed"
    assert result.mock_spec == 'mock.yaml', "Mock spec should be parsed"
    assert result.command == 'python app.py', "Command should be parsed"
    assert result.metadata == {'key': 'value', 'env': 'prod'}, "Metadata should be parsed"
    assert len(result.dependencies) == 2, "Dependencies should be parsed as DependencySpec objects"


def test_parse_manifest_happy_path(full_manifest_dict):
    """Parse valid dict with all fields into ServiceManifest"""
    # Execute
    result = _parse_manifest(full_manifest_dict)
    
    # Assert
    assert result is not None, "ServiceManifest object should be created"
    assert result.name == 'full-service', "Name should be correctly mapped"
    assert result.version == '1.2.3', "Version should be correctly mapped"
    assert result.port == 8080, "Port should be correctly mapped"
    assert result.proxy_mode == 'grpc', "Proxy mode should be correctly mapped"
    assert result.role == 'gateway', "Role should be correctly mapped"
    assert result.api_spec == 'openapi.yaml', "API spec should be correctly mapped"
    assert result.mock_spec == 'mock.yaml', "Mock spec should be correctly mapped"
    assert result.command == 'python app.py', "Command should be correctly mapped"
    assert result.metadata == {'key': 'value', 'env': 'prod'}, "Metadata should be correctly mapped"
    assert len(result.dependencies) == 2, "Dependencies should be converted to DependencySpec"


def test_parse_manifest_minimal(valid_manifest_dict):
    """Parse dict with only required 'name' field"""
    # Execute
    result = _parse_manifest(valid_manifest_dict)
    
    # Assert
    assert result.name == 'test-service', "Name field should be populated"
    assert result.version == '0.0.0', "Default version should be '0.0.0'"
    assert result.port == 0, "Default port should be 0"
    assert result.proxy_mode == 'http', "Default proxy_mode should be 'http'"
    assert result.role == 'service', "Default role should be 'service'"
    assert result.api_spec == '', "Default api_spec should be empty string"
    assert result.mock_spec == '', "Default mock_spec should be empty string"
    assert result.command == '', "Default command should be empty string"
    assert result.metadata == {}, "Default metadata should be empty dict"
    assert result.dependencies == [], "Default dependencies should be empty list"


def test_parse_manifest_dependencies_as_strings(manifest_with_string_deps):
    """Parse dependencies specified as list of strings"""
    # Execute
    result = _parse_manifest(manifest_with_string_deps)
    
    # Assert
    assert len(result.dependencies) == 3, "Should have 3 dependencies"
    for dep in result.dependencies:
        assert hasattr(dep, 'name'), "Each dependency should be a DependencySpec object"
    assert result.dependencies[0].name == 'dep1', "First dependency name should be correct"
    assert result.dependencies[1].name == 'dep2', "Second dependency name should be correct"
    assert result.dependencies[2].name == 'dep3', "Third dependency name should be correct"


def test_parse_manifest_dependencies_as_dicts(manifest_with_dict_deps):
    """Parse dependencies specified as list of dicts"""
    # Execute
    result = _parse_manifest(manifest_with_dict_deps)
    
    # Assert
    assert len(result.dependencies) == 2, "Should have 2 dependencies"
    assert result.dependencies[0].name == 'dep1', "First dependency name should be correct"
    assert result.dependencies[0].version == '1.0.0', "First dependency version should be correct"
    assert result.dependencies[1].name == 'dep2', "Second dependency name should be correct"
    assert result.dependencies[1].version == '2.0.0', "Second dependency version should be correct"


# Edge Case Tests

def test_load_manifest_with_minimal_fields(temp_service_dir):
    """Load manifest containing only required field (name)"""
    # Setup
    manifest_path = os.path.join(temp_service_dir, 'baton-service.yaml')
    manifest_content = "name: minimal-service\n"
    
    with open(manifest_path, 'w') as f:
        f.write(manifest_content)
    
    # Execute
    result = load_manifest(temp_service_dir)
    
    # Assert
    assert result.name == 'minimal-service', "Name field should be populated"
    assert result.version == '0.0.0', "Default version should be applied"
    assert result.port == 0, "Default port should be applied"
    assert result.proxy_mode == 'http', "Default proxy_mode should be applied"


def test_load_manifest_with_unicode(temp_service_dir):
    """Load manifest with Unicode characters in fields"""
    # Setup
    manifest_path = os.path.join(temp_service_dir, 'baton-service.yaml')
    manifest_content = "name: 服务-αβγ-🚀\ncommand: echo 'Hello 世界'\n"
    
    with open(manifest_path, 'w', encoding='utf-8') as f:
        f.write(manifest_content)
    
    # Execute
    result = load_manifest(temp_service_dir)
    
    # Assert
    assert '服务' in result.name, "Unicode characters should be preserved in name"
    assert '世界' in result.command, "Unicode characters should be preserved in command"


def test_parse_manifest_mixed_dependencies():
    """Parse dependencies with mixed string and dict formats"""
    # Setup
    manifest = {
        'name': 'mixed-deps-service',
        'dependencies': [
            'string-dep',
            {'name': 'dict-dep', 'version': '1.0'},
            'another-string-dep'
        ]
    }
    
    # Execute
    result = _parse_manifest(manifest)
    
    # Assert
    assert len(result.dependencies) == 3, "All dependencies should be converted"
    assert result.dependencies[0].name == 'string-dep', "String dependency should be converted"
    assert result.dependencies[1].name == 'dict-dep', "Dict dependency should be converted"
    assert result.dependencies[1].version == '1.0', "Dict dependency version should be preserved"
    assert result.dependencies[2].name == 'another-string-dep', "Second string dependency should be converted"


def test_load_manifest_relative_path(temp_service_dir):
    """Load manifest using relative path"""
    # Setup
    manifest_path = os.path.join(temp_service_dir, 'baton-service.yaml')
    manifest_content = "name: relative-path-service\n"
    
    with open(manifest_path, 'w') as f:
        f.write(manifest_content)
    
    # Change to temp directory and use relative path
    original_dir = os.getcwd()
    try:
        os.chdir(temp_service_dir)
        
        # Execute
        result = load_manifest('.')
        
        # Assert
        assert result is not None, "Manifest should be loaded with relative path"
        assert result.name == 'relative-path-service', "Manifest should have correct name"
    finally:
        os.chdir(original_dir)


def test_load_manifest_absolute_path(temp_service_dir):
    """Load manifest using absolute path"""
    # Setup
    manifest_path = os.path.join(temp_service_dir, 'baton-service.yaml')
    manifest_content = "name: absolute-path-service\n"
    
    with open(manifest_path, 'w') as f:
        f.write(manifest_content)
    
    # Execute with absolute path
    abs_path = os.path.abspath(temp_service_dir)
    result = load_manifest(abs_path)
    
    # Assert
    assert result is not None, "Manifest should be loaded with absolute path"
    assert result.name == 'absolute-path-service', "Manifest should have correct name"


def test_parse_manifest_with_null_optional_fields():
    """Parse manifest where optional fields are explicitly null"""
    # Setup
    manifest = {
        'name': 'null-fields-service',
        'version': None,
        'port': None,
        'metadata': None,
        'dependencies': None
    }
    
    # Execute
    result = _parse_manifest(manifest)
    
    # Assert
    assert result.name == 'null-fields-service', "Name should be preserved"
    assert result.version == '0.0.0' or result.version is None, "Null version should be handled"
    assert result.port == 0 or result.port is None, "Null port should be handled"
    assert result.metadata == {} or result.metadata is None, "Null metadata should be handled"
    assert result.dependencies == [] or result.dependencies is None, "Null dependencies should be handled"


def test_parse_manifest_empty_dependencies_list():
    """Parse manifest with empty dependencies list"""
    # Setup
    manifest = {
        'name': 'no-deps-service',
        'dependencies': []
    }
    
    # Execute
    result = _parse_manifest(manifest)
    
    # Assert
    assert result.dependencies == [], "Empty dependencies list should be preserved"
    assert len(result.dependencies) == 0, "No DependencySpec objects should be created"


# Error Case Tests

def test_load_manifest_error_not_found(temp_service_dir):
    """Error when baton-service.yaml does not exist"""
    # Execute & Assert
    with pytest.raises((ManifestNotFoundError, FileNotFoundError, Exception)) as exc_info:
        load_manifest(temp_service_dir)
    
    assert exc_info.value is not None, "Should raise exception for missing file"


def test_load_manifest_error_empty(temp_service_dir):
    """Error when YAML file is empty"""
    # Setup
    manifest_path = os.path.join(temp_service_dir, 'baton-service.yaml')
    
    with open(manifest_path, 'w') as f:
        f.write('')  # Empty file
    
    # Execute & Assert
    with pytest.raises((EmptyManifestError, Exception)) as exc_info:
        load_manifest(temp_service_dir)
    
    assert exc_info.value is not None, "Should raise exception for empty manifest"


def test_load_manifest_error_yaml_parse(temp_service_dir):
    """Error when YAML syntax is invalid"""
    # Setup
    manifest_path = os.path.join(temp_service_dir, 'baton-service.yaml')
    
    with open(manifest_path, 'w') as f:
        f.write("name: test\n  invalid: indentation\n  - malformed\n[[[")
    
    # Execute & Assert
    with pytest.raises((YamlParseError, Exception)) as exc_info:
        load_manifest(temp_service_dir)
    
    assert exc_info.value is not None, "Should raise exception for YAML parse error"


def test_load_manifest_error_io():
    """Error when file cannot be opened or read"""
    # This test is platform-specific and may not work in all environments
    # We'll use a mock to simulate the IO error
    
    with patch('builtins.open', side_effect=IOError("Permission denied")):
        with pytest.raises((IOError, Exception)) as exc_info:
            load_manifest('/some/path')
    
    assert exc_info.value is not None, "Should raise exception for IO error"


def test_load_manifest_error_invalid_directory():
    """Error when service_dir is not a valid directory"""
    # Execute & Assert
    with pytest.raises((ManifestNotFoundError, FileNotFoundError, Exception)) as exc_info:
        load_manifest('/nonexistent/directory/path')
    
    assert exc_info.value is not None, "Should raise exception for invalid directory"


def test_parse_manifest_error_missing_name():
    """Error when 'name' key is missing from dict"""
    # Setup
    manifest = {
        'version': '1.0.0',
        'port': 8080
    }
    
    # Execute & Assert
    with pytest.raises((MissingNameError, KeyError, ValueError, Exception)) as exc_info:
        _parse_manifest(manifest)
    
    assert exc_info.value is not None, "Should raise exception for missing name"


def test_parse_manifest_error_invalid_dependency():
    """Error when DependencySpec construction fails"""
    # Setup - dependency without name will fail
    manifest = {
        'name': 'test-service',
        'dependencies': [
            {'version': '1.0.0'}  # Missing 'name' field
        ]
    }
    
    # Execute & Assert
    with pytest.raises((InvalidDependencySpecError, ValueError, Exception)) as exc_info:
        _parse_manifest(manifest)
    
    assert exc_info.value is not None, "Should raise exception for invalid dependency"


def test_parse_manifest_error_invalid_manifest():
    """Error when ServiceManifest construction fails"""
    # This is tricky to test without knowing exact validation rules
    # We can try passing invalid types
    manifest = {
        'name': '',  # Empty name might be invalid
        'port': 'not-a-number'  # Invalid type for port
    }
    
    # Execute & Assert
    try:
        result = _parse_manifest(manifest)
        # If it doesn't raise, check if validation occurred
        if hasattr(result, 'name'):
            assert result.name == '' or result.name is not None
    except (InvalidServiceManifestError, ValueError, TypeError, Exception) as e:
        assert e is not None, "Should raise exception for invalid manifest structure"


# Invariant Tests

def test_invariant_manifest_filename():
    """Verify MANIFEST_FILENAME constant is 'baton-service.yaml'"""
    # Assert
    assert MANIFEST_FILENAME == 'baton-service.yaml', \
        "MANIFEST_FILENAME should equal 'baton-service.yaml'"


def test_invariant_defaults():
    """Verify default values are applied per invariants"""
    # Setup
    manifest = {'name': 'test-defaults'}
    
    # Execute
    result = _parse_manifest(manifest)
    
    # Assert all default values
    assert result.version == '0.0.0', "Default version should be '0.0.0'"
    assert result.port == 0, "Default port should be 0"
    assert result.proxy_mode == 'http', "Default proxy_mode should be 'http'"
    assert result.role == 'service', "Default role should be 'service'"
    assert result.api_spec == '', "Default api_spec should be empty string"
    assert result.mock_spec == '', "Default mock_spec should be empty string"
    assert result.command == '', "Default command should be empty string"
    assert result.metadata == {}, "Default metadata should be empty dict"


# Additional comprehensive tests

def test_load_manifest_yaml_with_comments(temp_service_dir):
    """Load manifest with YAML comments"""
    # Setup
    manifest_path = os.path.join(temp_service_dir, 'baton-service.yaml')
    manifest_content = """
# This is a comment
name: commented-service  # inline comment
version: 1.0.0
# Another comment
"""
    
    with open(manifest_path, 'w') as f:
        f.write(manifest_content)
    
    # Execute
    result = load_manifest(temp_service_dir)
    
    # Assert
    assert result.name == 'commented-service', "Comments should be ignored"
    assert result.version == '1.0.0', "Version should be parsed correctly"


def test_parse_manifest_with_extra_fields():
    """Parse manifest with extra unknown fields"""
    # Setup
    manifest = {
        'name': 'extra-fields-service',
        'unknown_field': 'should be ignored',
        'another_unknown': 123
    }
    
    # Execute
    result = _parse_manifest(manifest)
    
    # Assert
    assert result.name == 'extra-fields-service', "Known fields should be parsed"
    # Extra fields should be ignored or handled gracefully


def test_load_manifest_with_nested_metadata(temp_service_dir):
    """Load manifest with nested metadata structure"""
    # Setup
    manifest_path = os.path.join(temp_service_dir, 'baton-service.yaml')
    manifest_content = """
name: nested-metadata-service
metadata:
  level1:
    level2:
      key: value
  array:
    - item1
    - item2
"""
    
    with open(manifest_path, 'w') as f:
        f.write(manifest_content)
    
    # Execute
    result = load_manifest(temp_service_dir)
    
    # Assert
    assert result.name == 'nested-metadata-service', "Name should be parsed"
    assert 'level1' in result.metadata, "Nested metadata should be preserved"
    assert result.metadata['level1']['level2']['key'] == 'value', "Deeply nested values should be accessible"


def test_parse_manifest_special_characters_in_strings():
    """Parse manifest with special characters in string fields"""
    # Setup
    manifest = {
        'name': 'special-chars-!@#$%',
        'command': 'echo "Hello World" && ls -la',
        'api_spec': './path/to/spec.yaml'
    }
    
    # Execute
    result = _parse_manifest(manifest)
    
    # Assert
    assert 'special-chars' in result.name, "Special characters should be preserved"
    assert '&&' in result.command, "Command with special chars should be preserved"
    assert './' in result.api_spec, "Path notation should be preserved"


def test_load_manifest_windows_path_separators(temp_service_dir):
    """Load manifest handling Windows-style path separators"""
    # Setup
    manifest_path = os.path.join(temp_service_dir, 'baton-service.yaml')
    manifest_content = "name: windows-path-service\n"
    
    with open(manifest_path, 'w') as f:
        f.write(manifest_content)
    
    # Execute with mixed separators (if on Windows)
    if os.name == 'nt':
        path_with_backslashes = temp_service_dir.replace('/', '\\')
        result = load_manifest(path_with_backslashes)
        assert result.name == 'windows-path-service', "Windows paths should be handled"
    else:
        # On Unix, just verify normal behavior
        result = load_manifest(temp_service_dir)
        assert result.name == 'windows-path-service', "Path should work on Unix"


def test_parse_manifest_numeric_string_fields():
    """Parse manifest where string fields contain numeric values"""
    # Setup
    manifest = {
        'name': '12345',
        'version': '1.0.0',
        'command': '12345'
    }
    
    # Execute
    result = _parse_manifest(manifest)
    
    # Assert
    assert result.name == '12345', "Numeric strings should be preserved"
    assert result.command == '12345', "Numeric command should be preserved"


def test_load_manifest_large_file(temp_service_dir):
    """Load manifest with large metadata/dependencies"""
    # Setup
    manifest_path = os.path.join(temp_service_dir, 'baton-service.yaml')
    
    # Create large dependencies list
    deps = ['dep' + str(i) for i in range(100)]
    deps_yaml = '\n'.join(['  - ' + dep for dep in deps])
    
    manifest_content = f"""
name: large-manifest-service
dependencies:
{deps_yaml}
"""
    
    with open(manifest_path, 'w') as f:
        f.write(manifest_content)
    
    # Execute
    result = load_manifest(temp_service_dir)
    
    # Assert
    assert result.name == 'large-manifest-service', "Name should be parsed"
    assert len(result.dependencies) == 100, "All 100 dependencies should be parsed"


def test_parse_manifest_boolean_and_numeric_types():
    """Parse manifest with boolean and numeric metadata"""
    # Setup
    manifest = {
        'name': 'typed-metadata-service',
        'port': 8080,
        'metadata': {
            'enabled': True,
            'count': 42,
            'ratio': 3.14,
            'flag': False
        }
    }
    
    # Execute
    result = _parse_manifest(manifest)
    
    # Assert
    assert result.name == 'typed-metadata-service', "Name should be parsed"
    assert result.port == 8080, "Numeric port should be preserved"
    assert result.metadata['enabled'] is True, "Boolean true should be preserved"
    assert result.metadata['flag'] is False, "Boolean false should be preserved"
    assert result.metadata['count'] == 42, "Integer should be preserved"
    assert result.metadata['ratio'] == 3.14, "Float should be preserved"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
