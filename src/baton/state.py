"""State persistence for Baton.

Manages the .baton/ directory: CircuitState as JSON, PID tracking.
"""

from __future__ import annotations

import json
from pathlib import Path

from baton.schemas import CircuitState

BATON_DIR = ".baton"
STATE_FILE = "state.json"


def ensure_baton_dir(project_dir: str | Path) -> Path:
    """Create .baton/ directory if it doesn't exist. Return its path."""
    d = Path(project_dir) / BATON_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_state(state: CircuitState, project_dir: str | Path) -> None:
    """Save CircuitState to .baton/state.json."""
    d = ensure_baton_dir(project_dir)
    path = d / STATE_FILE
    with open(path, "w") as f:
        json.dump(state.model_dump(), f, indent=2)


def load_state(project_dir: str | Path) -> CircuitState | None:
    """Load CircuitState from .baton/state.json. Returns None if not found."""
    path = Path(project_dir) / BATON_DIR / STATE_FILE
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    return CircuitState(**data)


def clear_state(project_dir: str | Path) -> None:
    """Remove state file."""
    path = Path(project_dir) / BATON_DIR / STATE_FILE
    if path.exists():
        path.unlink()
