"""Tests for deployment providers."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from baton.cli import main as cli_main
from baton.providers import create_provider
from baton.providers.local import LocalProvider
from baton.schemas import CircuitSpec, CollapseLevel, DeploymentTarget, EdgeSpec, NodeSpec, NodeStatus


def _init_project(d: Path) -> None:
    cli_main(["init", str(d)])
    cli_main(["node", "add", "api", "--port", "16001", "--dir", str(d)])
    cli_main(["node", "add", "service", "--port", "16002", "--dir", str(d)])
    cli_main(["edge", "add", "api", "service", "--dir", str(d)])


class TestCreateProvider:
    def test_local(self):
        provider = create_provider("local")
        assert isinstance(provider, LocalProvider)

    def test_unknown(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("azure")


class TestLocalProvider:
    async def test_deploy_and_teardown(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)

        from baton.config import load_circuit
        circuit = load_circuit(d)

        target = DeploymentTarget(
            provider="local",
            config={"project_dir": str(d), "mock": "true"},
        )

        provider = LocalProvider()
        try:
            state = await provider.deploy(circuit, target)
            assert len(state.adapters) == 2
            assert state.collapse_level == CollapseLevel.FULL_MOCK
        finally:
            await provider.teardown(circuit, target)

    async def test_deploy_status(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)

        from baton.config import load_circuit
        circuit = load_circuit(d)

        target = DeploymentTarget(
            provider="local",
            config={"project_dir": str(d)},
        )

        provider = LocalProvider()
        try:
            await provider.deploy(circuit, target)
            status = await provider.status(circuit, target)
            assert status.circuit_name == circuit.name
        finally:
            await provider.teardown(circuit, target)

    async def test_status_no_deploy(self):
        circuit = CircuitSpec(
            name="test",
            nodes=[NodeSpec(name="api", port=16010)],
        )
        target = DeploymentTarget(provider="local")
        provider = LocalProvider()
        status = await provider.status(circuit, target)
        assert status.collapse_level == CollapseLevel.FULL_MOCK
