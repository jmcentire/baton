"""
Contract-driven pytest test suite for Baton State Persistence component.

This test suite verifies the contract for state management functions including
directory creation, state serialization/deserialization, and JSONL operations.
"""

import pytest
import json
import os
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, mock_open
from json import JSONDecodeError

# Import the component under test
from src.baton.state import (
    ensure_baton_dir,
    save_state,
    load_state,
    clear_state,
    append_jsonl,
    read_jsonl,
    BATON_DIR,
    STATE_FILE
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_circuit_state():
    """Create a mock CircuitState object with model_dump() method."""
    state = Mock()
    state.model_dump.return_value = {
        "status": "active",
        "step": 1,
        "data": {"test": "value"}
    }
    return state


@pytest.fixture
def mock_circuit_state_complex():
    """Create a mock CircuitState with more complex data structure."""
    state = Mock()
    state.model_dump.return_value = {
        "status": "running",
        "step": 5,
        "nested": {
            "level1": {
                "level2": "deep_value"
            }
        },
        "list_data": [1, 2, 3]
    }
    return state


@pytest.fixture
def object_without_model_dump():
    """Create an object without model_dump() method."""
    return {"status": "active"}


@pytest.fixture
def state_with_non_serializable():
    """Create a state object that returns non-serializable data."""
    state = Mock()
    state.model_dump.return_value = {
        "status": "active",
        "non_serializable": lambda x: x  # Functions are not JSON serializable
    }
    return state


# ============================================================================
# Tests for ensure_baton_dir()
# ============================================================================

def test_ensure_baton_dir_happy_path_with_string(tmp_path):
    """ensure_baton_dir creates .baton directory successfully with string path."""
    project_dir = str(tmp_path)
    
    result = ensure_baton_dir(project_dir)
    
    assert isinstance(result, Path), "Should return a Path object"
    assert result.exists(), ".baton directory should exist"
    assert result.is_dir(), ".baton should be a directory"
    assert result.name == ".baton", "Directory should be named .baton"
    assert result.parent == tmp_path, ".baton should be in project_dir"


def test_ensure_baton_dir_happy_path_with_path_object(tmp_path):
    """ensure_baton_dir creates .baton directory successfully with Path object."""
    project_dir = Path(tmp_path)
    
    result = ensure_baton_dir(project_dir)
    
    assert isinstance(result, Path), "Should return a Path object"
    assert result.exists(), ".baton directory should exist"
    assert result.is_dir(), ".baton should be a directory"
    assert result.name == ".baton", "Directory should be named .baton"


def test_ensure_baton_dir_idempotent(tmp_path):
    """ensure_baton_dir is idempotent - can be called multiple times safely."""
    project_dir = str(tmp_path)
    
    result1 = ensure_baton_dir(project_dir)
    result2 = ensure_baton_dir(project_dir)
    result3 = ensure_baton_dir(project_dir)
    
    assert result1 == result2 == result3, "Multiple calls should return same path"
    assert result1.exists() and result1.is_dir(), "Directory should remain valid"


def test_ensure_baton_dir_creates_parent_directories(tmp_path):
    """ensure_baton_dir creates parent directories if they don't exist."""
    nested_path = tmp_path / "nested" / "parent" / "dirs"
    
    result = ensure_baton_dir(nested_path)
    
    assert result.exists(), ".baton directory should exist"
    assert result.parent.exists(), "Parent directories should be created"
    assert result.name == ".baton", "Directory should be named .baton"


def test_ensure_baton_dir_invalid_path():
    """ensure_baton_dir raises OSError for invalid path or insufficient permissions."""
    # Use a path that is likely to fail on most systems
    invalid_path = "/root/completely_invalid_path_no_permission/test"
    
    with pytest.raises(OSError):
        ensure_baton_dir(invalid_path)


def test_invariant_baton_dir_constant(tmp_path):
    """Verify BATON_DIR constant is '.baton' across all operations."""
    assert BATON_DIR == ".baton", "BATON_DIR constant should be '.baton'"
    
    result = ensure_baton_dir(tmp_path)
    assert result.name == ".baton", "Directory created should use BATON_DIR constant"


# ============================================================================
# Tests for save_state()
# ============================================================================

def test_save_state_happy_path(tmp_path, mock_circuit_state):
    """save_state successfully saves CircuitState to state.json."""
    project_dir = str(tmp_path)
    
    save_state(mock_circuit_state, project_dir)
    
    state_file = tmp_path / ".baton" / "state.json"
    assert state_file.exists(), "state.json should exist"
    
    with open(state_file, 'r') as f:
        content = json.load(f)
    
    assert content == mock_circuit_state.model_dump(), "File content should match state data"


def test_save_state_with_path_object(tmp_path, mock_circuit_state):
    """save_state works with Path object as project_dir."""
    project_dir = Path(tmp_path)
    
    save_state(mock_circuit_state, project_dir)
    
    state_file = tmp_path / ".baton" / "state.json"
    assert state_file.exists(), "state.json should exist"


def test_save_state_creates_baton_dir(tmp_path, mock_circuit_state):
    """save_state creates .baton directory if it doesn't exist."""
    project_dir = str(tmp_path)
    baton_dir = tmp_path / ".baton"
    
    # Ensure .baton doesn't exist initially
    assert not baton_dir.exists(), ".baton should not exist initially"
    
    save_state(mock_circuit_state, project_dir)
    
    assert baton_dir.exists(), ".baton directory should be created"
    state_file = baton_dir / "state.json"
    assert state_file.exists(), "state.json should be created"


def test_save_state_uses_2_space_indentation(tmp_path, mock_circuit_state):
    """save_state uses 2-space indentation as per invariant."""
    project_dir = str(tmp_path)
    
    save_state(mock_circuit_state, project_dir)
    
    state_file = tmp_path / ".baton" / "state.json"
    with open(state_file, 'r') as f:
        content = f.read()
    
    # Check for 2-space indentation
    assert '  "status"' in content or '  "step"' in content, \
        "JSON should be indented with 2 spaces"
    assert '    ' not in content or content.count('    ') < content.count('  '), \
        "Should use 2-space indentation, not 4-space"


def test_save_state_no_model_dump_method(tmp_path, object_without_model_dump):
    """save_state raises AttributeError when state object doesn't have model_dump() method."""
    project_dir = str(tmp_path)
    
    with pytest.raises(AttributeError):
        save_state(object_without_model_dump, project_dir)


def test_save_state_non_serializable_data(tmp_path, state_with_non_serializable):
    """save_state raises TypeError when state.model_dump() returns non-serializable data."""
    project_dir = str(tmp_path)
    
    with pytest.raises(TypeError):
        save_state(state_with_non_serializable, project_dir)


def test_save_state_permission_denied(tmp_path, mock_circuit_state):
    """save_state raises OSError when file write permission denied."""
    project_dir = tmp_path
    baton_dir = project_dir / ".baton"
    baton_dir.mkdir()
    
    # Make directory read-only
    os.chmod(baton_dir, 0o444)
    
    try:
        with pytest.raises(OSError):
            save_state(mock_circuit_state, project_dir)
    finally:
        # Restore permissions for cleanup
        os.chmod(baton_dir, 0o755)


def test_invariant_state_file_constant(tmp_path, mock_circuit_state):
    """Verify STATE_FILE constant is 'state.json' for save and load operations."""
    assert STATE_FILE == "state.json", "STATE_FILE constant should be 'state.json'"
    
    save_state(mock_circuit_state, tmp_path)
    
    state_file = tmp_path / ".baton" / "state.json"
    assert state_file.exists(), "File created should be named state.json"


# ============================================================================
# Tests for load_state()
# ============================================================================

def test_load_state_happy_path(tmp_path):
    """load_state successfully loads CircuitState from state.json."""
    # Create a valid state file
    baton_dir = tmp_path / ".baton"
    baton_dir.mkdir()
    state_file = baton_dir / "state.json"
    
    test_data = {"status": "active", "step": 1}
    with open(state_file, 'w') as f:
        json.dump(test_data, f)
    
    with patch('src.baton.state.CircuitState') as MockCircuitState:
        mock_instance = Mock()
        MockCircuitState.return_value = mock_instance
        
        result = load_state(tmp_path)
        
        assert result is not None, "Should return CircuitState instance"
        MockCircuitState.assert_called_once()


def test_load_state_file_not_exists(tmp_path):
    """load_state returns None when state.json doesn't exist."""
    result = load_state(tmp_path)
    
    assert result is None, "Should return None when file doesn't exist"


def test_load_state_with_path_object(tmp_path):
    """load_state works with Path object as project_dir."""
    # Create a valid state file
    baton_dir = tmp_path / ".baton"
    baton_dir.mkdir()
    state_file = baton_dir / "state.json"
    
    test_data = {"status": "active", "step": 1}
    with open(state_file, 'w') as f:
        json.dump(test_data, f)
    
    with patch('src.baton.state.CircuitState') as MockCircuitState:
        mock_instance = Mock()
        MockCircuitState.return_value = mock_instance
        
        result = load_state(Path(tmp_path))
        
        assert result is not None, "Should return CircuitState instance"


def test_load_state_invalid_json(tmp_path):
    """load_state raises JSONDecodeError when state.json contains invalid JSON."""
    baton_dir = tmp_path / ".baton"
    baton_dir.mkdir()
    state_file = baton_dir / "state.json"
    
    # Write invalid JSON
    with open(state_file, 'w') as f:
        f.write("{invalid json content")
    
    with pytest.raises(JSONDecodeError):
        load_state(tmp_path)


def test_load_state_validation_error(tmp_path):
    """load_state raises ValidationError when JSON doesn't match CircuitState schema."""
    baton_dir = tmp_path / ".baton"
    baton_dir.mkdir()
    state_file = baton_dir / "state.json"
    
    # Write valid JSON but invalid schema
    with open(state_file, 'w') as f:
        json.dump({"invalid": "schema"}, f)
    
    with patch('src.baton.state.CircuitState') as MockCircuitState:
        from pydantic import ValidationError
        MockCircuitState.side_effect = ValidationError.from_exception_data(
            "CircuitState", [{"type": "missing", "loc": ("field",), "msg": "field required", "input": {}}]
        )
        
        with pytest.raises(ValidationError):
            load_state(tmp_path)


def test_load_state_permission_denied(tmp_path):
    """load_state raises OSError when file exists but cannot be read."""
    baton_dir = tmp_path / ".baton"
    baton_dir.mkdir()
    state_file = baton_dir / "state.json"
    
    # Create file
    with open(state_file, 'w') as f:
        json.dump({"status": "active"}, f)
    
    # Make file unreadable
    os.chmod(state_file, 0o000)
    
    try:
        with pytest.raises(OSError):
            load_state(tmp_path)
    finally:
        # Restore permissions for cleanup
        os.chmod(state_file, 0o644)


def test_round_trip_save_load_state(tmp_path, mock_circuit_state_complex):
    """Round-trip test: save and load state preserves data."""
    project_dir = tmp_path
    
    # Save state
    save_state(mock_circuit_state_complex, project_dir)
    
    # Load state and verify
    state_file = project_dir / ".baton" / "state.json"
    with open(state_file, 'r') as f:
        loaded_data = json.load(f)
    
    expected_data = mock_circuit_state_complex.model_dump()
    assert loaded_data == expected_data, "Loaded data should match saved data"


# ============================================================================
# Tests for clear_state()
# ============================================================================

def test_clear_state_happy_path(tmp_path, mock_circuit_state):
    """clear_state successfully removes state.json file."""
    # Create state file first
    save_state(mock_circuit_state, tmp_path)
    state_file = tmp_path / ".baton" / "state.json"
    assert state_file.exists(), "State file should exist before clearing"
    
    clear_state(tmp_path)
    
    assert not state_file.exists(), "state.json should not exist after clearing"


def test_clear_state_file_not_exists(tmp_path):
    """clear_state is idempotent - works when file doesn't exist."""
    state_file = tmp_path / ".baton" / "state.json"
    assert not state_file.exists(), "State file should not exist initially"
    
    # Should not raise an error
    clear_state(tmp_path)
    
    assert not state_file.exists(), "state.json should remain non-existent"


def test_clear_state_with_path_object(tmp_path, mock_circuit_state):
    """clear_state works with Path object as project_dir."""
    # Create state file first
    save_state(mock_circuit_state, tmp_path)
    state_file = tmp_path / ".baton" / "state.json"
    assert state_file.exists(), "State file should exist before clearing"
    
    clear_state(Path(tmp_path))
    
    assert not state_file.exists(), "state.json should be removed"


def test_clear_state_permission_denied(tmp_path, mock_circuit_state):
    """clear_state raises OSError when file exists but cannot be deleted due to permissions."""
    # Create state file
    save_state(mock_circuit_state, tmp_path)
    baton_dir = tmp_path / ".baton"
    
    # Make directory read-only (prevents file deletion)
    os.chmod(baton_dir, 0o444)
    
    try:
        with pytest.raises(OSError):
            clear_state(tmp_path)
    finally:
        # Restore permissions for cleanup
        os.chmod(baton_dir, 0o755)


# ============================================================================
# Tests for append_jsonl()
# ============================================================================

def test_append_jsonl_happy_path(tmp_path):
    """append_jsonl successfully appends JSON object to JSONL file."""
    project_dir = tmp_path
    filename = "test.jsonl"
    data = {"key": "value", "number": 42}
    
    append_jsonl(project_dir, filename, data)
    
    jsonl_file = tmp_path / ".baton" / filename
    assert jsonl_file.exists(), "JSONL file should exist"
    
    with open(jsonl_file, 'r') as f:
        content = f.read()
    
    assert content.endswith('\n'), "Content should end with newline"
    loaded_data = json.loads(content.strip())
    assert loaded_data == data, "Loaded data should match appended data"


def test_append_jsonl_multiple_appends(tmp_path):
    """append_jsonl appends multiple entries to same file."""
    project_dir = tmp_path
    filename = "test.jsonl"
    data_list = [
        {"id": 1, "value": "first"},
        {"id": 2, "value": "second"},
        {"id": 3, "value": "third"}
    ]
    
    for data in data_list:
        append_jsonl(project_dir, filename, data)
    
    jsonl_file = tmp_path / ".baton" / filename
    with open(jsonl_file, 'r') as f:
        lines = f.readlines()
    
    assert len(lines) == 3, "Should have 3 lines"
    for i, line in enumerate(lines):
        loaded_data = json.loads(line.strip())
        assert loaded_data == data_list[i], f"Line {i} should match appended data"


def test_append_jsonl_creates_baton_dir(tmp_path):
    """append_jsonl creates .baton directory if it doesn't exist."""
    project_dir = tmp_path
    baton_dir = tmp_path / ".baton"
    assert not baton_dir.exists(), ".baton should not exist initially"
    
    filename = "test.jsonl"
    data = {"key": "value"}
    
    append_jsonl(project_dir, filename, data)
    
    assert baton_dir.exists(), ".baton directory should be created"
    jsonl_file = baton_dir / filename
    assert jsonl_file.exists(), "JSONL file should be created"


def test_append_jsonl_with_path_object(tmp_path):
    """append_jsonl works with Path object as project_dir."""
    project_dir = Path(tmp_path)
    filename = "test.jsonl"
    data = {"key": "value"}
    
    append_jsonl(project_dir, filename, data)
    
    jsonl_file = tmp_path / ".baton" / filename
    assert jsonl_file.exists(), "JSONL file should exist"


def test_append_jsonl_non_serializable_data(tmp_path):
    """append_jsonl raises TypeError when data contains non-JSON-serializable objects."""
    project_dir = tmp_path
    filename = "test.jsonl"
    data = {"key": "value", "func": lambda x: x}
    
    with pytest.raises(TypeError):
        append_jsonl(project_dir, filename, data)


def test_append_jsonl_permission_denied(tmp_path):
    """append_jsonl raises OSError when cannot write to file due to permissions."""
    project_dir = tmp_path
    baton_dir = tmp_path / ".baton"
    baton_dir.mkdir()
    
    # Make directory read-only
    os.chmod(baton_dir, 0o444)
    
    try:
        with pytest.raises(OSError):
            append_jsonl(project_dir, "test.jsonl", {"key": "value"})
    finally:
        # Restore permissions for cleanup
        os.chmod(baton_dir, 0o755)


def test_invariant_jsonl_format(tmp_path):
    """Verify JSONL format: one JSON object per line with trailing newline."""
    project_dir = tmp_path
    filename = "test.jsonl"
    
    data_list = [{"id": 1}, {"id": 2}, {"id": 3}]
    for data in data_list:
        append_jsonl(project_dir, filename, data)
    
    jsonl_file = tmp_path / ".baton" / filename
    with open(jsonl_file, 'r') as f:
        content = f.read()
    
    lines = content.split('\n')
    # Last line should be empty (after final newline)
    assert lines[-1] == '', "File should end with newline"
    
    # Each non-empty line should be valid JSON
    for i, line in enumerate(lines[:-1]):
        try:
            json.loads(line)
        except json.JSONDecodeError:
            pytest.fail(f"Line {i} is not valid JSON: {line}")


# ============================================================================
# Tests for read_jsonl()
# ============================================================================

def test_read_jsonl_happy_path(tmp_path):
    """read_jsonl successfully reads JSONL file and returns list of dicts."""
    project_dir = tmp_path
    filename = "test.jsonl"
    
    # Create JSONL file
    data_list = [{"id": 1, "val": "a"}, {"id": 2, "val": "b"}, {"id": 3, "val": "c"}]
    for data in data_list:
        append_jsonl(project_dir, filename, data)
    
    result = read_jsonl(project_dir, filename, None)
    
    assert isinstance(result, list), "Should return a list"
    assert len(result) == 3, "Should return 3 items"
    assert result == data_list, "Returned data should match written data"


def test_read_jsonl_file_not_exists(tmp_path):
    """read_jsonl returns empty list when file doesn't exist."""
    project_dir = tmp_path
    filename = "nonexistent.jsonl"
    
    result = read_jsonl(project_dir, filename, None)
    
    assert result == [], "Should return empty list"


def test_read_jsonl_with_last_n(tmp_path):
    """read_jsonl returns only last N items when last_n is specified."""
    project_dir = tmp_path
    filename = "test.jsonl"
    
    # Create JSONL file with 5 entries
    data_list = [{"id": i} for i in range(5)]
    for data in data_list:
        append_jsonl(project_dir, filename, data)
    
    result = read_jsonl(project_dir, filename, 2)
    
    assert len(result) == 2, "Should return 2 items"
    assert result == data_list[-2:], "Should return last 2 items"


def test_read_jsonl_last_n_greater_than_lines(tmp_path):
    """read_jsonl returns all items when last_n is greater than number of lines."""
    project_dir = tmp_path
    filename = "test.jsonl"
    
    # Create JSONL file with 3 entries
    data_list = [{"id": i} for i in range(3)]
    for data in data_list:
        append_jsonl(project_dir, filename, data)
    
    result = read_jsonl(project_dir, filename, 1000)
    
    assert len(result) == 3, "Should return all 3 items"
    assert result == data_list, "Should return all available items"


def test_read_jsonl_skips_empty_lines(tmp_path):
    """read_jsonl skips empty and whitespace-only lines."""
    project_dir = tmp_path
    baton_dir = tmp_path / ".baton"
    baton_dir.mkdir()
    filename = "test.jsonl"
    jsonl_file = baton_dir / filename
    
    # Create JSONL file with empty lines
    with open(jsonl_file, 'w') as f:
        f.write('{"id": 1}\n')
        f.write('\n')
        f.write('  \n')
        f.write('{"id": 2}\n')
        f.write('\n')
        f.write('{"id": 3}\n')
    
    result = read_jsonl(project_dir, filename, None)
    
    assert len(result) == 3, "Should skip empty lines and return 3 items"
    assert result == [{"id": 1}, {"id": 2}, {"id": 3}], "Should return only non-empty items"


def test_read_jsonl_with_path_object(tmp_path):
    """read_jsonl works with Path object as project_dir."""
    project_dir = Path(tmp_path)
    filename = "test.jsonl"
    
    # Create JSONL file
    data_list = [{"id": 1}, {"id": 2}]
    for data in data_list:
        append_jsonl(project_dir, filename, data)
    
    result = read_jsonl(project_dir, filename, None)
    
    assert result == data_list, "Should read data correctly with Path object"


def test_read_jsonl_invalid_json_line(tmp_path):
    """read_jsonl raises JSONDecodeError when a line contains invalid JSON."""
    project_dir = tmp_path
    baton_dir = tmp_path / ".baton"
    baton_dir.mkdir()
    filename = "test.jsonl"
    jsonl_file = baton_dir / filename
    
    # Create JSONL file with invalid JSON
    with open(jsonl_file, 'w') as f:
        f.write('{"id": 1}\n')
        f.write('{invalid json}\n')
        f.write('{"id": 2}\n')
    
    with pytest.raises(JSONDecodeError):
        read_jsonl(project_dir, filename, None)


def test_read_jsonl_permission_denied(tmp_path):
    """read_jsonl raises OSError when file exists but cannot be read."""
    project_dir = tmp_path
    filename = "test.jsonl"
    
    # Create JSONL file
    append_jsonl(project_dir, filename, {"id": 1})
    
    jsonl_file = tmp_path / ".baton" / filename
    # Make file unreadable
    os.chmod(jsonl_file, 0o000)
    
    try:
        with pytest.raises(OSError):
            read_jsonl(project_dir, filename, None)
    finally:
        # Restore permissions for cleanup
        os.chmod(jsonl_file, 0o644)


# ============================================================================
# Integration and Edge Case Tests
# ============================================================================

def test_integration_full_workflow(tmp_path, mock_circuit_state):
    """Integration test: full workflow of state operations."""
    project_dir = tmp_path
    
    # 1. Ensure baton dir
    baton_path = ensure_baton_dir(project_dir)
    assert baton_path.exists()
    
    # 2. Save state
    save_state(mock_circuit_state, project_dir)
    state_file = baton_path / "state.json"
    assert state_file.exists()
    
    # 3. Append JSONL entries
    append_jsonl(project_dir, "log.jsonl", {"event": "start"})
    append_jsonl(project_dir, "log.jsonl", {"event": "process"})
    append_jsonl(project_dir, "log.jsonl", {"event": "end"})
    
    # 4. Read JSONL
    logs = read_jsonl(project_dir, "log.jsonl", None)
    assert len(logs) == 3
    
    # 5. Clear state
    clear_state(project_dir)
    assert not state_file.exists()
    
    # 6. Load state (should return None)
    result = load_state(project_dir)
    assert result is None


def test_edge_case_empty_jsonl_file(tmp_path):
    """Edge case: reading an empty JSONL file."""
    project_dir = tmp_path
    baton_dir = tmp_path / ".baton"
    baton_dir.mkdir()
    filename = "empty.jsonl"
    jsonl_file = baton_dir / filename
    
    # Create empty file
    jsonl_file.touch()
    
    result = read_jsonl(project_dir, filename, None)
    assert result == [], "Should return empty list for empty file"


def test_edge_case_jsonl_with_only_whitespace(tmp_path):
    """Edge case: JSONL file with only whitespace lines."""
    project_dir = tmp_path
    baton_dir = tmp_path / ".baton"
    baton_dir.mkdir()
    filename = "whitespace.jsonl"
    jsonl_file = baton_dir / filename
    
    with open(jsonl_file, 'w') as f:
        f.write('\n')
        f.write('   \n')
        f.write('\t\n')
        f.write('  \t  \n')
    
    result = read_jsonl(project_dir, filename, None)
    assert result == [], "Should return empty list for whitespace-only file"


def test_edge_case_last_n_zero(tmp_path):
    """Edge case: read_jsonl with last_n=0."""
    project_dir = tmp_path
    filename = "test.jsonl"
    
    # Create JSONL file
    for i in range(5):
        append_jsonl(project_dir, filename, {"id": i})
    
    result = read_jsonl(project_dir, filename, 0)
    assert result == [], "Should return empty list when last_n=0"


def test_edge_case_special_characters_in_json(tmp_path):
    """Edge case: JSON data with special characters."""
    project_dir = tmp_path
    filename = "special.jsonl"
    
    special_data = {
        "unicode": "Hello 世界 🌍",
        "quotes": 'He said "hello"',
        "newlines": "line1\nline2",
        "tabs": "col1\tcol2"
    }
    
    append_jsonl(project_dir, filename, special_data)
    result = read_jsonl(project_dir, filename, None)
    
    assert len(result) == 1
    assert result[0] == special_data, "Should preserve special characters"


def test_edge_case_deeply_nested_json(tmp_path):
    """Edge case: Deeply nested JSON structures."""
    project_dir = tmp_path
    filename = "nested.jsonl"
    
    nested_data = {
        "level1": {
            "level2": {
                "level3": {
                    "level4": {
                        "level5": "deep_value"
                    }
                }
            }
        }
    }
    
    append_jsonl(project_dir, filename, nested_data)
    result = read_jsonl(project_dir, filename, None)
    
    assert result[0] == nested_data, "Should handle deeply nested structures"
