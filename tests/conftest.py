"""Shared test fixtures for Baton."""

from __future__ import annotations

from pathlib import Path

import pytest

from baton.schemas import CircuitSpec, EdgeSpec, NodeSpec


@pytest.fixture
def sample_circuit() -> CircuitSpec:
    """A 3-node circuit: api -> service -> db."""
    return CircuitSpec(
        name="test",
        nodes=[
            NodeSpec(name="api", port=9080, proxy_mode="http"),
            NodeSpec(name="service", port=9081, proxy_mode="http"),
            NodeSpec(name="db", port=9432, proxy_mode="tcp"),
        ],
        edges=[
            EdgeSpec(source="api", target="service"),
            EdgeSpec(source="service", target="db"),
        ],
    )


@pytest.fixture
def baton_dir(tmp_path: Path) -> Path:
    """Temporary .baton/ directory."""
    d = tmp_path / ".baton"
    d.mkdir()
    return d


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Temporary project directory."""
    return tmp_path
