# === Baton State Persistence (src_baton_state) v1 ===
#  Dependencies: json, pathlib, baton.schemas
# Manages state persistence for Baton by handling the .baton/ directory structure, saving/loading CircuitState as JSON, and managing JSONL append/read operations for logs and tracking data.

# Module invariants:
#   - BATON_DIR constant is '.baton'
#   - STATE_FILE constant is 'state.json'
#   - All file operations use the .baton/ subdirectory within project_dir
#   - JSON serialization uses 2-space indentation for state files
#   - JSONL format: one JSON object per line with trailing newline

PathLike = str | Path

def ensure_baton_dir(
    project_dir: str | Path,
) -> Path:
    """
    Creates the .baton/ directory if it doesn't exist and returns its path

    Postconditions:
      - .baton/ directory exists at project_dir/.baton/
      - All parent directories are created if needed
      - Returns Path object pointing to .baton/ directory

    Errors:
      - OSError (OSError): Insufficient permissions or invalid path

    Side effects: Creates directory on filesystem if it doesn't exist
    Idempotent: no
    """
    ...

def save_state(
    state: CircuitState,
    project_dir: str | Path,
) -> None:
    """
    Saves CircuitState object to .baton/state.json as formatted JSON

    Preconditions:
      - state must be a valid CircuitState with model_dump() method

    Postconditions:
      - .baton/state.json exists with indented JSON content
      - File content is the result of state.model_dump() serialized

    Errors:
      - OSError (OSError): File write permission denied or disk full
      - AttributeError (AttributeError): state object doesn't have model_dump() method
      - TypeError (TypeError): state.model_dump() returns non-serializable data

    Side effects: Creates/overwrites .baton/state.json file
    Idempotent: no
    """
    ...

def load_state(
    project_dir: str | Path,
) -> CircuitState | None:
    """
    Loads CircuitState from .baton/state.json or returns None if file doesn't exist

    Postconditions:
      - Returns CircuitState instance if file exists and is valid JSON
      - Returns None if file doesn't exist

    Errors:
      - JSONDecodeError (json.JSONDecodeError): state.json contains invalid JSON
      - ValidationError (ValidationError): JSON doesn't match CircuitState schema
      - OSError (OSError): File exists but cannot be read

    Side effects: none
    Idempotent: no
    """
    ...

def clear_state(
    project_dir: str | Path,
) -> None:
    """
    Removes the state.json file if it exists

    Postconditions:
      - .baton/state.json does not exist after function completes

    Errors:
      - OSError (OSError): File exists but cannot be deleted due to permissions

    Side effects: Deletes .baton/state.json if present
    Idempotent: no
    """
    ...

def append_jsonl(
    project_dir: str | Path,
    filename: str,
    data: dict,
) -> None:
    """
    Appends a single JSON object as a line to a JSONL file in .baton/ directory

    Postconditions:
      - data is appended as JSON followed by newline to .baton/<filename>
      - .baton/ directory exists

    Errors:
      - OSError (OSError): Cannot write to file due to permissions or disk space
      - TypeError (TypeError): data contains non-JSON-serializable objects

    Side effects: Creates or appends to .baton/<filename>
    Idempotent: no
    """
    ...

def read_jsonl(
    project_dir: str | Path,
    filename: str,
    last_n: int | None = None,
) -> list[dict]:
    """
    Reads JSONL file from .baton/ directory, optionally returning only the last N lines

    Postconditions:
      - Returns empty list if file doesn't exist
      - Returns list of parsed JSON objects from non-empty lines
      - If last_n is specified, returns at most last_n items
      - Empty/whitespace lines are skipped

    Errors:
      - JSONDecodeError (json.JSONDecodeError): A line contains invalid JSON
      - OSError (OSError): File exists but cannot be read

    Side effects: none
    Idempotent: no
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['PathLike', 'ensure_baton_dir', 'save_state', 'load_state', 'ValidationError', 'clear_state', 'append_jsonl', 'read_jsonl']
