"""Tests for state persistence."""

from __future__ import annotations

from pathlib import Path

from baton.schemas import AdapterState, CircuitState, CollapseLevel, NodeStatus
from baton.state import clear_state, ensure_baton_dir, load_state, save_state


class TestEnsureBatonDir:
    def test_creates_dir(self, project_dir: Path):
        d = ensure_baton_dir(project_dir)
        assert d.exists()
        assert d.is_dir()
        assert d.name == ".baton"

    def test_idempotent(self, project_dir: Path):
        d1 = ensure_baton_dir(project_dir)
        d2 = ensure_baton_dir(project_dir)
        assert d1 == d2


class TestSaveLoadState:
    def test_roundtrip_empty(self, project_dir: Path):
        state = CircuitState(circuit_name="test")
        save_state(state, project_dir)
        loaded = load_state(project_dir)
        assert loaded is not None
        assert loaded.circuit_name == "test"
        assert loaded.collapse_level == CollapseLevel.FULL_MOCK

    def test_roundtrip_with_adapters(self, project_dir: Path):
        state = CircuitState(
            circuit_name="test",
            collapse_level=CollapseLevel.PARTIAL,
            live_nodes=["api"],
            adapters={
                "api": AdapterState(
                    node_name="api",
                    status=NodeStatus.ACTIVE,
                    adapter_pid=1234,
                )
            },
        )
        save_state(state, project_dir)
        loaded = load_state(project_dir)
        assert loaded is not None
        assert loaded.live_nodes == ["api"]
        assert loaded.adapters["api"].status == NodeStatus.ACTIVE
        assert loaded.adapters["api"].adapter_pid == 1234

    def test_load_missing(self, project_dir: Path):
        assert load_state(project_dir) is None


class TestClearState:
    def test_clear_existing(self, project_dir: Path):
        state = CircuitState(circuit_name="test")
        save_state(state, project_dir)
        assert load_state(project_dir) is not None
        clear_state(project_dir)
        assert load_state(project_dir) is None

    def test_clear_missing(self, project_dir: Path):
        # Should not raise
        clear_state(project_dir)
