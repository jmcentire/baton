"""Deployment provider protocol and factory."""

from __future__ import annotations

from typing import Protocol

from baton.schemas import CircuitSpec, CircuitState, DeploymentTarget


class DeploymentProvider(Protocol):
    """Protocol for cloud deployment providers."""

    async def deploy(self, circuit: CircuitSpec, target: DeploymentTarget) -> CircuitState:
        ...

    async def teardown(self, circuit: CircuitSpec, target: DeploymentTarget) -> None:
        ...

    async def status(self, circuit: CircuitSpec, target: DeploymentTarget) -> CircuitState:
        ...


def create_provider(name: str) -> DeploymentProvider:
    if name == "local":
        from baton.providers.local import LocalProvider
        return LocalProvider()
    elif name == "gcp":
        from baton.providers.gcp import GCPProvider
        return GCPProvider()
    elif name == "aws":
        from baton.providers.aws import AWSProvider
        return AWSProvider()
    else:
        raise ValueError(f"Unknown provider: {name}. Available: local, gcp, aws")
