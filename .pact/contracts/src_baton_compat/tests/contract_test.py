"""
Contract-driven tests for Static Compatibility Analysis component.

This test suite verifies the behavior of compatibility checking functions
that validate OpenAPI specs between service providers and consumers.

Tests are organized into:
- Unit tests for internal functions (_load_api_paths, _extract_response_schema, etc.)
- Integration tests for check_compatibility
- Edge case and error handling tests
- Invariant validation tests

All dependencies are mocked to ensure isolation.
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, mock_open
from dataclasses import dataclass, field
from typing import Any

# Import component under test
from src.baton.compat import (
    CompatIssue,
    CompatReport,
    check_compatibility,
    _load_api_paths,
    _extract_response_schema,
    _compare_paths,
    _compare_schemas,
)


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def minimal_openapi_yaml():
    """Minimal valid OpenAPI spec in YAML format."""
    return """
openapi: 3.0.0
info:
  title: Test API
  version: 1.0.0
paths:
  /users:
    get:
      responses:
        '200':
          description: Success
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                  name:
                    type: string
"""

@pytest.fixture
def minimal_openapi_json():
    """Minimal valid OpenAPI spec in JSON format."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/users": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "Success",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "name": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

@pytest.fixture
def service_manifest_factory():
    """Factory for creating ServiceManifest mock objects."""
    def _create(name, api_spec=None, expected_api=None, dependencies=None):
        manifest = Mock()
        manifest.name = name
        manifest.api_spec = api_spec or f"{name}_spec.yaml"
        manifest.expected_api = expected_api
        manifest.dependencies = dependencies or {}
        return manifest
    return _create


# ============================================================================
# Tests for check_compatibility
# ============================================================================

class TestCheckCompatibility:
    """Tests for the main check_compatibility function."""
    
    def test_check_compatibility_happy_path(self, tmp_path, service_manifest_factory):
        """check_compatibility returns compatible=True when provider satisfies all consumer requirements."""
        # Setup provider spec
        provider_spec = tmp_path / "provider.yaml"
        provider_spec.write_text("""
openapi: 3.0.0
paths:
  /users:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                  name:
                    type: string
                  email:
                    type: string
""")
        
        # Setup consumer spec
        consumer_spec = tmp_path / "consumer.yaml"
        consumer_spec.write_text("""
openapi: 3.0.0
paths:
  /users:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                  name:
                    type: string
""")
        
        provider = service_manifest_factory("provider", api_spec="provider.yaml")
        consumer = service_manifest_factory(
            "consumer", 
            expected_api="consumer.yaml",
            dependencies={"provider": "1.0.0"}
        )
        
        report = check_compatibility(provider, [consumer], tmp_path)
        
        assert report.compatible is True, "Report should be compatible"
        error_issues = [i for i in report.issues if i.severity == 'error']
        assert len(error_issues) == 0, "Should have no error-severity issues"
    
    def test_check_compatibility_multiple_consumers(self, tmp_path, service_manifest_factory):
        """check_compatibility validates all consumers depending on provider."""
        # Setup provider
        provider_spec = tmp_path / "provider.yaml"
        provider_spec.write_text("""
openapi: 3.0.0
paths:
  /api/resource:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  data:
                    type: string
""")
        
        # Setup multiple consumers
        consumer1_spec = tmp_path / "consumer1.yaml"
        consumer1_spec.write_text("""
openapi: 3.0.0
paths:
  /api/resource:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  data:
                    type: string
""")
        
        consumer2_spec = tmp_path / "consumer2.yaml"
        consumer2_spec.write_text("""
openapi: 3.0.0
paths:
  /api/resource:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  data:
                    type: string
""")
        
        provider = service_manifest_factory("provider", api_spec="provider.yaml")
        consumer1 = service_manifest_factory(
            "consumer1",
            expected_api="consumer1.yaml",
            dependencies={"provider": "1.0.0"}
        )
        consumer2 = service_manifest_factory(
            "consumer2",
            expected_api="consumer2.yaml",
            dependencies={"provider": "1.0.0"}
        )
        
        report = check_compatibility(provider, [consumer1, consumer2], tmp_path)
        
        assert report is not None, "Report should be generated"
        # Both consumers should be validated (compatible in this case)
        assert report.compatible is True, "All consumers with expected_api should be validated"
    
    def test_check_compatibility_skip_no_expected_api(self, tmp_path, service_manifest_factory):
        """check_compatibility skips consumers without expected_api defined."""
        provider_spec = tmp_path / "provider.yaml"
        provider_spec.write_text("""
openapi: 3.0.0
paths:
  /test:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
""")
        
        provider = service_manifest_factory("provider", api_spec="provider.yaml")
        
        # Consumer without expected_api
        consumer_no_api = service_manifest_factory(
            "consumer_no_api",
            expected_api=None,
            dependencies={"provider": "1.0.0"}
        )
        
        report = check_compatibility(provider, [consumer_no_api], tmp_path)
        
        # Should not fail, consumer without expected_api is skipped
        assert report is not None, "Report should be generated"
        assert len(report.issues) == 0, "Consumers without expected_api should be skipped"
    
    def test_check_compatibility_invalid_base_dir(self, service_manifest_factory):
        """check_compatibility raises FileNotFoundError for invalid base_dir."""
        provider = service_manifest_factory("provider")
        consumer = service_manifest_factory("consumer", expected_api="spec.yaml")
        
        with pytest.raises(FileNotFoundError):
            # Path that doesn't exist should raise FileNotFoundError
            check_compatibility(provider, [consumer], "/nonexistent/path/12345")
    
    def test_check_compatibility_malformed_yaml(self, tmp_path, service_manifest_factory):
        """check_compatibility propagates YAMLError when spec files are malformed YAML."""
        # Create malformed YAML
        provider_spec = tmp_path / "provider.yaml"
        provider_spec.write_text("""
openapi: 3.0.0
paths:
  /test:
    get:
      responses:
        - this is invalid yaml indentation
      - and this too
""")
        
        provider = service_manifest_factory("provider", api_spec="provider.yaml")
        consumer = service_manifest_factory(
            "consumer",
            expected_api="provider.yaml",
            dependencies={"provider": "1.0.0"}
        )
        
        # YAMLError should be propagated from _load_api_paths
        with pytest.raises(Exception):  # yaml.YAMLError
            check_compatibility(provider, [consumer], tmp_path)
    
    def test_check_compatibility_malformed_json(self, tmp_path, service_manifest_factory):
        """check_compatibility propagates JSONDecodeError when spec files are malformed JSON."""
        # Create malformed JSON
        provider_spec = tmp_path / "provider.json"
        provider_spec.write_text("""
{
  "openapi": "3.0.0",
  "paths": {
    "incomplete": "missing closing braces"
""")
        
        provider = service_manifest_factory("provider", api_spec="provider.json")
        consumer = service_manifest_factory(
            "consumer",
            expected_api="provider.json",
            dependencies={"provider": "1.0.0"}
        )
        
        with pytest.raises(json.JSONDecodeError):
            check_compatibility(provider, [consumer], tmp_path)
    
    def test_check_compatibility_missing_attributes(self, tmp_path):
        """check_compatibility raises AttributeError when provider or consumers have missing attributes."""
        # Create manifest with missing attributes
        provider = Mock(spec=[])  # Empty spec means no attributes
        consumer = Mock(spec=[])
        
        with pytest.raises(AttributeError):
            check_compatibility(provider, [consumer], tmp_path)
    
    def test_check_compatibility_incompatible_schemas(self, tmp_path, service_manifest_factory):
        """check_compatibility returns compatible=False when schemas are incompatible."""
        # Provider missing required field
        provider_spec = tmp_path / "provider.yaml"
        provider_spec.write_text("""
openapi: 3.0.0
paths:
  /users:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
""")
        
        # Consumer expects additional required field
        consumer_spec = tmp_path / "consumer.yaml"
        consumer_spec.write_text("""
openapi: 3.0.0
paths:
  /users:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                  email:
                    type: string
                required:
                  - email
""")
        
        provider = service_manifest_factory("provider", api_spec="provider.yaml")
        consumer = service_manifest_factory(
            "consumer",
            expected_api="consumer.yaml",
            dependencies={"provider": "1.0.0"}
        )
        
        report = check_compatibility(provider, [consumer], tmp_path)
        
        assert report.compatible is False, "Report should be incompatible"
        error_issues = [i for i in report.issues if i.severity == 'error']
        assert len(error_issues) > 0, "Should have error-severity issues"


# ============================================================================
# Tests for _load_api_paths
# ============================================================================

class TestLoadApiPaths:
    """Tests for _load_api_paths function."""
    
    def test_load_api_paths_yaml_happy(self, tmp_path, minimal_openapi_yaml):
        """_load_api_paths successfully loads YAML OpenAPI spec."""
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text(minimal_openapi_yaml)
        
        result = _load_api_paths(tmp_path, "spec.yaml")
        
        assert isinstance(result, dict), "Result should be a dict"
        assert "/users" in result, "Should contain /users path"
        assert "GET" in result["/users"], "Should contain GET method"
        # Verify all method keys are uppercase
        for path, methods in result.items():
            for method in methods.keys():
                assert method.isupper(), f"Method {method} should be uppercase"
    
    def test_load_api_paths_json_happy(self, tmp_path):
        """_load_api_paths successfully loads JSON OpenAPI spec."""
        spec_content = {
            "openapi": "3.0.0",
            "paths": {
                "/items": {
                    "post": {
                        "responses": {
                            "201": {
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(json.dumps(spec_content))
        
        result = _load_api_paths(tmp_path, "spec.json")
        
        assert isinstance(result, dict), "Result should be a dict"
        assert "/items" in result, "Should contain /items path"
        assert "POST" in result["/items"], "Should contain POST method (uppercase)"
    
    def test_load_api_paths_file_not_exists(self, tmp_path):
        """_load_api_paths returns empty dict when file does not exist."""
        result = _load_api_paths(tmp_path, "nonexistent.yaml")
        
        assert result == {}, "Should return empty dict for non-existent file"
    
    def test_load_api_paths_no_paths_key(self, tmp_path):
        """_load_api_paths returns empty dict when spec lacks paths key."""
        spec_content = {
            "openapi": "3.0.0",
            "info": {"title": "No Paths", "version": "1.0.0"}
        }
        
        spec_file = tmp_path / "no_paths.json"
        spec_file.write_text(json.dumps(spec_content))
        
        result = _load_api_paths(tmp_path, "no_paths.json")
        
        assert result == {}, "Should return empty dict when paths key is missing"
    
    def test_load_api_paths_uppercase_methods(self, tmp_path):
        """_load_api_paths converts all method keys to uppercase."""
        spec_content = {
            "openapi": "3.0.0",
            "paths": {
                "/test": {
                    "get": {"responses": {"200": {}}},
                    "post": {"responses": {"201": {}}},
                    "put": {"responses": {"200": {}}},
                    "delete": {"responses": {"204": {}}},
                    "patch": {"responses": {"200": {}}}
                }
            }
        }
        
        spec_file = tmp_path / "methods.json"
        spec_file.write_text(json.dumps(spec_content))
        
        result = _load_api_paths(tmp_path, "methods.json")
        
        assert "/test" in result, "Should contain /test path"
        methods = result["/test"]
        for method_key in methods.keys():
            assert method_key.isupper(), f"Method {method_key} should be uppercase"
        assert all(m in methods for m in ["GET", "POST", "PUT", "DELETE", "PATCH"]), \
            "All standard HTTP methods should be present and uppercase"
    
    def test_load_api_paths_excludes_x_methods(self, tmp_path):
        """_load_api_paths excludes methods starting with x-."""
        spec_content = {
            "openapi": "3.0.0",
            "paths": {
                "/test": {
                    "get": {"responses": {"200": {}}},
                    "x-custom": {"some": "data"},
                    "x-internal": {"other": "data"}
                }
            }
        }
        
        spec_file = tmp_path / "x_methods.json"
        spec_file.write_text(json.dumps(spec_content))
        
        result = _load_api_paths(tmp_path, "x_methods.json")
        
        assert "/test" in result, "Should contain /test path"
        methods = result["/test"]
        assert "GET" in methods, "Should contain GET method"
        # Check no method keys start with 'X-' or 'x-'
        for method_key in methods.keys():
            assert not method_key.upper().startswith('X-'), \
                f"Method {method_key} should not start with x-"
    
    def test_load_api_paths_excludes_parameters(self, tmp_path):
        """_load_api_paths excludes parameters key."""
        spec_content = {
            "openapi": "3.0.0",
            "paths": {
                "/test/{id}": {
                    "parameters": [{"name": "id", "in": "path"}],
                    "get": {"responses": {"200": {}}}
                }
            }
        }
        
        spec_file = tmp_path / "params.json"
        spec_file.write_text(json.dumps(spec_content))
        
        result = _load_api_paths(tmp_path, "params.json")
        
        assert "/test/{id}" in result, "Should contain path"
        methods = result["/test/{id}"]
        assert "PARAMETERS" not in methods, "PARAMETERS should be excluded"
        assert "GET" in methods, "GET method should be present"
    
    def test_load_api_paths_yaml_error(self, tmp_path):
        """_load_api_paths raises YAMLError for malformed YAML."""
        spec_file = tmp_path / "malformed.yaml"
        spec_file.write_text("""
        this is: [invalid
        yaml: content
        - missing closing bracket
        """)
        
        with pytest.raises(Exception):  # yaml.YAMLError or similar
            _load_api_paths(tmp_path, "malformed.yaml")
    
    def test_load_api_paths_json_error(self, tmp_path):
        """_load_api_paths raises JSONDecodeError for malformed JSON."""
        spec_file = tmp_path / "malformed.json"
        spec_file.write_text("""
        {
          "openapi": "3.0.0",
          "paths": {
            "incomplete"
        """)
        
        with pytest.raises(json.JSONDecodeError):
            _load_api_paths(tmp_path, "malformed.json")
    
    def test_load_api_paths_os_error(self, tmp_path):
        """_load_api_paths raises OSError if file cannot be read."""
        # Create a file with no read permissions (Unix-like systems)
        spec_file = tmp_path / "no_read.yaml"
        spec_file.write_text("openapi: 3.0.0")
        spec_file.chmod(0o000)
        
        try:
            with pytest.raises(OSError):
                _load_api_paths(tmp_path, "no_read.yaml")
        finally:
            # Restore permissions for cleanup
            spec_file.chmod(0o644)


# ============================================================================
# Tests for _extract_response_schema
# ============================================================================

class TestExtractResponseSchema:
    """Tests for _extract_response_schema function."""
    
    def test_extract_response_schema_200(self):
        """_extract_response_schema extracts 200 response schema."""
        operation = {
            "responses": {
                "200": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"id": {"type": "string"}}
                            }
                        }
                    }
                }
            }
        }
        components = {}
        
        result = _extract_response_schema(operation, components)
        
        assert result is not None, "Should extract schema"
        assert isinstance(result, dict), "Result should be a dict"
        assert result["type"] == "object", "Should be object type"
    
    def test_extract_response_schema_201(self):
        """_extract_response_schema extracts 201 response schema when 200 not present."""
        operation = {
            "responses": {
                "201": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"created": {"type": "boolean"}}
                            }
                        }
                    }
                }
            }
        }
        components = {}
        
        result = _extract_response_schema(operation, components)
        
        assert result is not None, "Should extract schema from 201"
        assert isinstance(result, dict), "Result should be a dict"
    
    def test_extract_response_schema_prioritizes_200(self):
        """_extract_response_schema prioritizes 200 over 201."""
        operation = {
            "responses": {
                "200": {
                    "content": {
                        "application/json": {
                            "schema": {"type": "object", "properties": {"from_200": {"type": "string"}}}
                        }
                    }
                },
                "201": {
                    "content": {
                        "application/json": {
                            "schema": {"type": "object", "properties": {"from_201": {"type": "string"}}}
                        }
                    }
                }
            }
        }
        components = {}
        
        result = _extract_response_schema(operation, components)
        
        assert result is not None, "Should extract schema"
        # Should be from 200, not 201
        assert "from_200" in result.get("properties", {}), "Should prioritize 200 response"
    
    def test_extract_response_schema_no_schema(self):
        """_extract_response_schema returns None when no schema found."""
        operation = {
            "responses": {
                "204": {
                    "description": "No content"
                }
            }
        }
        components = {}
        
        result = _extract_response_schema(operation, components)
        
        assert result is None, "Should return None when no schema found"
    
    def test_extract_response_schema_resolves_ref(self):
        """_extract_response_schema resolves $ref references to components."""
        operation = {
            "responses": {
                "200": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/User"
                            }
                        }
                    }
                }
            }
        }
        components = {
            "schemas": {
                "User": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"}
                    }
                }
            }
        }
        
        result = _extract_response_schema(operation, components)
        
        assert result is not None, "Should resolve $ref"
        assert result["type"] == "object", "Should be resolved schema"
        assert "id" in result["properties"], "Should have resolved properties"
    
    def test_extract_response_schema_index_error(self):
        """_extract_response_schema raises IndexError when $ref lacks separator."""
        operation = {
            "responses": {
                "200": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "InvalidRefWithoutSlash"
                            }
                        }
                    }
                }
            }
        }
        components = {}
        
        with pytest.raises(IndexError):
            _extract_response_schema(operation, components)
    
    def test_extract_response_schema_key_error(self):
        """_extract_response_schema raises KeyError for malformed or missing references."""
        operation = {
            "responses": {
                "200": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/NonExistent"
                            }
                        }
                    }
                }
            }
        }
        components = {
            "schemas": {}
        }
        
        with pytest.raises(KeyError):
            _extract_response_schema(operation, components)
    
    def test_extract_response_schema_json_only(self):
        """_extract_response_schema only extracts application/json content."""
        operation = {
            "responses": {
                "200": {
                    "content": {
                        "text/html": {
                            "schema": {"type": "string"}
                        },
                        "application/xml": {
                            "schema": {"type": "object"}
                        }
                    }
                }
            }
        }
        components = {}
        
        result = _extract_response_schema(operation, components)
        
        # Should return None since only non-JSON content types are present
        assert result is None, "Should only extract application/json content"


# ============================================================================
# Tests for _compare_paths
# ============================================================================

class TestComparePaths:
    """Tests for _compare_paths function."""
    
    def test_compare_paths_missing_path(self):
        """_compare_paths adds error for missing paths in provider."""
        expected = {
            "/users": {
                "GET": {"schema": {"type": "object"}}
            }
        }
        actual = {}
        report = CompatReport(compatible=True, issues=[])
        
        _compare_paths("consumer", "provider", expected, actual, report)
        
        assert len(report.issues) > 0, "Should add issue for missing path"
        error_issues = [i for i in report.issues if i.severity == 'error']
        assert len(error_issues) > 0, "Should have error-severity issue"
        assert any("/users" in i.path for i in error_issues), "Issue should reference /users"
    
    def test_compare_paths_missing_method(self):
        """_compare_paths adds error for missing methods in provider."""
        expected = {
            "/users": {
                "GET": {"schema": {"type": "object"}},
                "POST": {"schema": {"type": "object"}}
            }
        }
        actual = {
            "/users": {
                "GET": {"schema": {"type": "object"}}
            }
        }
        report = CompatReport(compatible=True, issues=[])
        
        _compare_paths("consumer", "provider", expected, actual, report)
        
        assert len(report.issues) > 0, "Should add issue for missing method"
        error_issues = [i for i in report.issues if i.severity == 'error']
        assert len(error_issues) > 0, "Should have error-severity issue"
        assert any("POST" in i.method for i in error_issues), "Issue should reference POST"
    
    def test_compare_paths_schema_comparison(self):
        """_compare_paths delegates to _compare_schemas when both schemas exist."""
        expected = {
            "/users": {
                "GET": {
                    "schema": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}}
                    }
                }
            }
        }
        actual = {
            "/users": {
                "GET": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"}
                        }
                    }
                }
            }
        }
        report = CompatReport(compatible=True, issues=[])
        
        with patch('src.src_baton_compat._compare_schemas') as mock_compare:
            _compare_paths("consumer", "provider", expected, actual, report)
            
            # _compare_schemas should have been called
            assert mock_compare.called, "_compare_schemas should be called"
    
    def test_compare_paths_no_schema_comparison(self):
        """_compare_paths skips schema comparison when expected or actual schema missing."""
        expected = {
            "/users": {
                "GET": {
                    "schema": None
                }
            }
        }
        actual = {
            "/users": {
                "GET": {
                    "schema": {"type": "object"}
                }
            }
        }
        report = CompatReport(compatible=True, issues=[])
        
        with patch('src.src_baton_compat._compare_schemas') as mock_compare:
            _compare_paths("consumer", "provider", expected, actual, report)
            
            # _compare_schemas should NOT be called when expected schema is None
            assert not mock_compare.called, "_compare_schemas should not be called when schema is None"


# ============================================================================
# Tests for _compare_schemas
# ============================================================================

class TestCompareSchemas:
    """Tests for _compare_schemas function."""
    
    def test_compare_schemas_type_mismatch(self):
        """_compare_schemas adds error and returns early on type mismatch."""
        expected = {"type": "string"}
        actual = {"type": "integer"}
        report = CompatReport(compatible=True, issues=[])
        
        _compare_schemas("consumer", "provider", "/test", "GET", expected, actual, report)
        
        assert len(report.issues) > 0, "Should add issue for type mismatch"
        error_issues = [i for i in report.issues if i.severity == 'error']
        assert len(error_issues) > 0, "Should have error-severity issue"
    
    def test_compare_schemas_missing_required_property(self):
        """_compare_schemas adds error for missing required properties in object types."""
        expected = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "email": {"type": "string"}
            },
            "required": ["email"]
        }
        actual = {
            "type": "object",
            "properties": {
                "id": {"type": "string"}
            }
        }
        report = CompatReport(compatible=True, issues=[])
        
        _compare_schemas("consumer", "provider", "/users", "POST", expected, actual, report)
        
        assert len(report.issues) > 0, "Should add issue for missing required property"
        error_issues = [i for i in report.issues if i.severity == 'error']
        assert len(error_issues) > 0, "Should have error-severity issue for missing property"
    
    def test_compare_schemas_array_items_recursive(self):
        """_compare_schemas recursively validates array item schemas."""
        expected = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"}
                }
            }
        }
        actual = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "extra": {"type": "string"}
                }
            }
        }
        report = CompatReport(compatible=True, issues=[])
        
        _compare_schemas("consumer", "provider", "/items", "GET", expected, actual, report)
        
        # Should recursively validate item schemas (structural subtyping allows extra fields)
        # No errors expected since actual has all expected fields plus extra
        error_issues = [i for i in report.issues if i.severity == 'error']
        assert len(error_issues) == 0, "Should recursively validate without errors"
    
    def test_compare_schemas_extra_fields_allowed(self):
        """_compare_schemas allows extra fields in actual (structural subtyping)."""
        expected = {
            "type": "object",
            "properties": {
                "id": {"type": "string"}
            }
        }
        actual = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "email": {"type": "string"}
            }
        }
        report = CompatReport(compatible=True, issues=[])
        
        _compare_schemas("consumer", "provider", "/users", "GET", expected, actual, report)
        
        # No errors expected - extra fields in actual are allowed
        error_issues = [i for i in report.issues if i.severity == 'error']
        assert len(error_issues) == 0, "Extra fields in actual should be allowed"


# ============================================================================
# Tests for CompatReport.add
# ============================================================================

class TestCompatReportAdd:
    """Tests for CompatReport.add method."""
    
    def test_compat_report_add_error_severity(self):
        """CompatReport.add sets compatible to False for error-severity issues."""
        report = CompatReport(compatible=True, issues=[])
        issue = CompatIssue(
            consumer="consumer",
            provider="provider",
            path="/test",
            method="GET",
            severity="error",
            detail="Test error"
        )
        
        report.add(issue)
        
        assert issue in report.issues, "Issue should be appended"
        assert report.compatible is False, "compatible should be set to False for error"
    
    def test_compat_report_add_non_error_severity(self):
        """CompatReport.add keeps compatible unchanged for non-error severity."""
        report = CompatReport(compatible=True, issues=[])
        issue = CompatIssue(
            consumer="consumer",
            provider="provider",
            path="/test",
            method="GET",
            severity="warning",
            detail="Test warning"
        )
        
        report.add(issue)
        
        assert issue in report.issues, "Issue should be appended"
        assert report.compatible is True, "compatible should remain True for warning"


# ============================================================================
# Invariant Tests
# ============================================================================

class TestInvariants:
    """Tests for contract invariants."""
    
    def test_invariant_compatible_false_with_errors(self, tmp_path, service_manifest_factory):
        """Invariant: CompatReport.compatible is False if any error-severity issue exists."""
        # Setup incompatible provider/consumer
        provider_spec = tmp_path / "provider.yaml"
        provider_spec.write_text("""
openapi: 3.0.0
paths:
  /test:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
""")
        
        consumer_spec = tmp_path / "consumer.yaml"
        consumer_spec.write_text("""
openapi: 3.0.0
paths:
  /missing:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
""")
        
        provider = service_manifest_factory("provider", api_spec="provider.yaml")
        consumer = service_manifest_factory(
            "consumer",
            expected_api="consumer.yaml",
            dependencies={"provider": "1.0.0"}
        )
        
        report = check_compatibility(provider, [consumer], tmp_path)
        
        error_issues = [i for i in report.issues if i.severity == 'error']
        if len(error_issues) > 0:
            assert report.compatible is False, \
                "CompatReport.compatible must be False when error-severity issues exist"
    
    def test_invariant_http_methods_uppercase(self, tmp_path):
        """Invariant: HTTP methods in path mappings are always uppercase."""
        spec_content = {
            "openapi": "3.0.0",
            "paths": {
                "/test": {
                    "get": {"responses": {"200": {}}},
                    "post": {"responses": {"201": {}}},
                    "put": {"responses": {"200": {}}}
                }
            }
        }
        
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(json.dumps(spec_content))
        
        result = _load_api_paths(tmp_path, "spec.json")
        
        for path, methods in result.items():
            for method_key in methods.keys():
                assert method_key.isupper(), \
                    f"HTTP method {method_key} must be uppercase (invariant)"
    
    def test_invariant_missing_files_empty_dict(self, tmp_path):
        """Invariant: Missing files result in empty dict rather than exceptions."""
        result = _load_api_paths(tmp_path, "nonexistent_file.yaml")
        
        assert result == {}, \
            "Missing files must return empty dict rather than raising exceptions (invariant)"
    
    def test_invariant_structural_subtyping(self):
        """Invariant: Schema comparison uses structural subtyping (provider can have extra fields)."""
        expected = {
            "type": "object",
            "properties": {
                "id": {"type": "string"}
            }
        }
        actual = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "extra_field": {"type": "string"},
                "another_extra": {"type": "integer"}
            }
        }
        report = CompatReport(compatible=True, issues=[])
        
        _compare_schemas("consumer", "provider", "/test", "GET", expected, actual, report)
        
        error_issues = [i for i in report.issues if i.severity == 'error']
        assert len(error_issues) == 0, \
            "Provider can have extra fields (structural subtyping invariant)"


# ============================================================================
# Edge Case Tests
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases."""
    
    def test_edge_case_empty_spec(self, tmp_path):
        """Edge case: Empty OpenAPI spec files."""
        spec_file = tmp_path / "empty.yaml"
        spec_file.write_text("")
        
        result = _load_api_paths(tmp_path, "empty.yaml")
        
        assert result == {}, "Empty spec should return empty dict"
    
    def test_edge_case_deeply_nested_schemas(self):
        """Edge case: Deeply nested schemas (>5 levels)."""
        # Create deeply nested schema
        deeply_nested_expected = {
            "type": "object",
            "properties": {
                "level1": {
                    "type": "object",
                    "properties": {
                        "level2": {
                            "type": "object",
                            "properties": {
                                "level3": {
                                    "type": "object",
                                    "properties": {
                                        "level4": {
                                            "type": "object",
                                            "properties": {
                                                "level5": {
                                                    "type": "object",
                                                    "properties": {
                                                        "level6": {"type": "string"}
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        
        deeply_nested_actual = {
            "type": "object",
            "properties": {
                "level1": {
                    "type": "object",
                    "properties": {
                        "level2": {
                            "type": "object",
                            "properties": {
                                "level3": {
                                    "type": "object",
                                    "properties": {
                                        "level4": {
                                            "type": "object",
                                            "properties": {
                                                "level5": {
                                                    "type": "object",
                                                    "properties": {
                                                        "level6": {"type": "string"}
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        
        report = CompatReport(compatible=True, issues=[])
        
        _compare_schemas("consumer", "provider", "/deep", "GET", 
                        deeply_nested_expected, deeply_nested_actual, report)
        
        # Should handle deep nesting without stack overflow
        error_issues = [i for i in report.issues if i.severity == 'error']
        assert len(error_issues) == 0, "Deep schemas should be validated correctly"
    
    def test_edge_case_path_parameters(self, tmp_path):
        """Edge case: Path parameter variations."""
        spec_content = {
            "openapi": "3.0.0",
            "paths": {
                "/users/{id}": {
                    "get": {"responses": {"200": {}}}
                },
                "/posts/{postId}/comments/{commentId}": {
                    "get": {"responses": {"200": {}}}
                }
            }
        }
        
        spec_file = tmp_path / "params.json"
        spec_file.write_text(json.dumps(spec_content))
        
        result = _load_api_paths(tmp_path, "params.json")
        
        assert "/users/{id}" in result, "Path with single parameter should be loaded"
        assert "/posts/{postId}/comments/{commentId}" in result, \
            "Path with multiple parameters should be loaded"
    
    def test_edge_case_all_http_methods(self, tmp_path):
        """Edge case: All HTTP methods (GET, POST, PUT, DELETE, PATCH, etc.)."""
        spec_content = {
            "openapi": "3.0.0",
            "paths": {
                "/resource": {
                    "get": {"responses": {"200": {}}},
                    "post": {"responses": {"201": {}}},
                    "put": {"responses": {"200": {}}},
                    "delete": {"responses": {"204": {}}},
                    "patch": {"responses": {"200": {}}},
                    "head": {"responses": {"200": {}}},
                    "options": {"responses": {"200": {}}}
                }
            }
        }
        
        spec_file = tmp_path / "all_methods.json"
        spec_file.write_text(json.dumps(spec_content))
        
        result = _load_api_paths(tmp_path, "all_methods.json")
        
        assert "/resource" in result, "Should contain resource path"
        methods = result["/resource"]
        expected_methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
        for method in expected_methods:
            assert method in methods, f"{method} should be present and uppercase"


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests for full workflow."""
    
    def test_integration_full_workflow(self, tmp_path, service_manifest_factory):
        """Integration: Full check_compatibility workflow with multiple consumers."""
        # Setup provider
        provider_spec = tmp_path / "provider.yaml"
        provider_spec.write_text("""
openapi: 3.0.0
info:
  title: Provider API
  version: 1.0.0
paths:
  /users:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                  name:
                    type: string
                  email:
                    type: string
    post:
      responses:
        '201':
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
  /products:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: array
                items:
                  type: object
                  properties:
                    product_id:
                      type: string
                    name:
                      type: string
""")
        
        # Consumer 1: Compatible
        consumer1_spec = tmp_path / "consumer1.yaml"
        consumer1_spec.write_text("""
openapi: 3.0.0
paths:
  /users:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                  name:
                    type: string
""")
        
        # Consumer 2: Compatible
        consumer2_spec = tmp_path / "consumer2.yaml"
        consumer2_spec.write_text("""
openapi: 3.0.0
paths:
  /products:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: array
                items:
                  type: object
                  properties:
                    product_id:
                      type: string
""")
        
        # Consumer 3: Incompatible (expects missing endpoint)
        consumer3_spec = tmp_path / "consumer3.yaml"
        consumer3_spec.write_text("""
openapi: 3.0.0
paths:
  /orders:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
""")
        
        provider = service_manifest_factory("provider", api_spec="provider.yaml")
        consumer1 = service_manifest_factory(
            "consumer1",
            expected_api="consumer1.yaml",
            dependencies={"provider": "1.0.0"}
        )
        consumer2 = service_manifest_factory(
            "consumer2",
            expected_api="consumer2.yaml",
            dependencies={"provider": "1.0.0"}
        )
        consumer3 = service_manifest_factory(
            "consumer3",
            expected_api="consumer3.yaml",
            dependencies={"provider": "1.0.0"}
        )
        
        report = check_compatibility(provider, [consumer1, consumer2, consumer3], tmp_path)
        
        assert report is not None, "Report should be generated"
        # Should have issues from consumer3
        assert len(report.issues) > 0, "Should have issues from incompatible consumer3"
        # Report should be incompatible due to consumer3
        assert report.compatible is False, "Report should be incompatible"
        # Verify consumer3 issue is present
        consumer3_issues = [i for i in report.issues if i.consumer == "consumer3"]
        assert len(consumer3_issues) > 0, "Should have issues for consumer3"
