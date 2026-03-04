"""Tests for GCP Cloud Run deployment provider."""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from baton.schemas import (
    CircuitSpec,
    DeploymentTarget,
    EdgeSpec,
    NodeSpec,
    NodeStatus,
)


def _make_circuit() -> CircuitSpec:
    return CircuitSpec(
        name="test",
        nodes=[
            NodeSpec(name="api", port=9080),
            NodeSpec(name="svc", port=9081),
        ],
        edges=[EdgeSpec(source="api", target="svc")],
    )


def _make_target(**kwargs) -> DeploymentTarget:
    defaults = {
        "provider": "gcp",
        "config": {"project": "my-project"},
        "region": "us-central1",
    }
    defaults.update(kwargs)
    return DeploymentTarget(**defaults)


def _mock_gcp_modules():
    """Create mock google.cloud.run_v2 and google.iam.v1 modules."""
    # Create mock module hierarchy
    google = types.ModuleType("google")
    google_cloud = types.ModuleType("google.cloud")
    run_v2 = types.ModuleType("google.cloud.run_v2")
    google_iam = types.ModuleType("google.iam")
    google_iam_v1 = types.ModuleType("google.iam.v1")
    policy_pb2 = types.ModuleType("google.iam.v1.policy_pb2")

    # Mock run_v2 classes
    run_v2.Service = MagicMock
    run_v2.RevisionTemplate = MagicMock
    run_v2.Container = MagicMock
    run_v2.ContainerPort = MagicMock
    run_v2.EnvVar = MagicMock

    # Mock ServicesAsyncClient
    mock_client = AsyncMock()
    run_v2.ServicesAsyncClient = MagicMock(return_value=mock_client)

    # Mock policy_pb2
    policy_pb2.Policy = MagicMock
    policy_pb2.Binding = MagicMock

    google.cloud = google_cloud
    google_cloud.run_v2 = run_v2
    google.iam = google_iam
    google_iam.v1 = google_iam_v1
    google_iam_v1.policy_pb2 = policy_pb2

    return {
        "google": google,
        "google.cloud": google_cloud,
        "google.cloud.run_v2": run_v2,
        "google.iam": google_iam,
        "google.iam.v1": google_iam_v1,
        "google.iam.v1.policy_pb2": policy_pb2,
    }, mock_client


class TestServiceId:
    def test_basic(self):
        from baton.providers.gcp import _service_id
        assert _service_id("myapp", "api", "") == "myapp-api"

    def test_with_namespace(self):
        from baton.providers.gcp import _service_id
        assert _service_id("myapp", "api", "prod") == "prod-myapp-api"

    def test_underscores_replaced(self):
        from baton.providers.gcp import _service_id
        assert _service_id("my_app", "my_api", "") == "my-app-my-api"


class TestGCPDeploy:
    async def test_deploy_no_project_raises(self):
        from baton.providers.gcp import GCPProvider

        modules, _ = _mock_gcp_modules()
        with patch.dict(sys.modules, modules):
            provider = GCPProvider()
            target = DeploymentTarget(
                provider="gcp", config={}, region="us-central1",
            )
            with pytest.raises(ValueError, match="requires 'project'"):
                await provider.deploy(_make_circuit(), target)

    async def test_deploy_creates_services(self):
        from baton.providers.gcp import GCPProvider

        modules, mock_client = _mock_gcp_modules()

        # Mock create_service -> returns operation with result
        mock_operation = AsyncMock()
        mock_result = MagicMock()
        mock_result.uri = "https://api-xyz.run.app"
        mock_operation.result = AsyncMock(return_value=mock_result)
        mock_client.create_service = AsyncMock(return_value=mock_operation)
        mock_client.set_iam_policy = AsyncMock()
        mock_client.update_service = AsyncMock(return_value=mock_operation)

        with patch.dict(sys.modules, modules):
            provider = GCPProvider()
            state = await provider.deploy(_make_circuit(), _make_target())

            assert "api" in state.adapters
            assert "svc" in state.adapters
            assert state.adapters["api"].status == NodeStatus.ACTIVE
            assert mock_client.create_service.call_count == 2

    async def test_deploy_handles_already_exists(self):
        from baton.providers.gcp import GCPProvider

        modules, mock_client = _mock_gcp_modules()

        mock_operation = AsyncMock()
        mock_result = MagicMock()
        mock_result.uri = "https://api-xyz.run.app"
        mock_operation.result = AsyncMock(return_value=mock_result)

        # First call raises "already exists", second succeeds
        mock_client.create_service = AsyncMock(
            side_effect=Exception("Service already exists")
        )
        mock_client.update_service = AsyncMock(return_value=mock_operation)
        mock_client.set_iam_policy = AsyncMock()

        with patch.dict(sys.modules, modules):
            provider = GCPProvider()
            state = await provider.deploy(_make_circuit(), _make_target())

            assert state.adapters["api"].status == NodeStatus.ACTIVE
            assert mock_client.update_service.call_count >= 2

    async def test_deploy_handles_error(self):
        from baton.providers.gcp import GCPProvider

        modules, mock_client = _mock_gcp_modules()

        mock_client.create_service = AsyncMock(
            side_effect=Exception("Permission denied")
        )
        mock_client.set_iam_policy = AsyncMock()

        with patch.dict(sys.modules, modules):
            provider = GCPProvider()
            state = await provider.deploy(_make_circuit(), _make_target())

            assert state.adapters["api"].status == NodeStatus.FAULTED


class TestGCPTeardown:
    async def test_teardown(self):
        from baton.providers.gcp import GCPProvider

        modules, mock_client = _mock_gcp_modules()

        mock_operation = AsyncMock()
        mock_operation.result = AsyncMock()
        mock_client.delete_service = AsyncMock(return_value=mock_operation)

        with patch.dict(sys.modules, modules):
            provider = GCPProvider()
            await provider.teardown(_make_circuit(), _make_target())
            assert mock_client.delete_service.call_count == 2

    async def test_teardown_no_project_raises(self):
        from baton.providers.gcp import GCPProvider

        modules, _ = _mock_gcp_modules()
        with patch.dict(sys.modules, modules):
            provider = GCPProvider()
            target = DeploymentTarget(provider="gcp", config={})
            with pytest.raises(ValueError, match="requires 'project'"):
                await provider.teardown(_make_circuit(), target)


class TestGCPStatus:
    async def test_status_all_ready(self):
        from baton.providers.gcp import GCPProvider

        modules, mock_client = _mock_gcp_modules()

        mock_condition = MagicMock()
        mock_condition.state.value = 4  # CONDITION_SUCCEEDED

        # Create separate condition mocks for each type
        cond_routes = MagicMock()
        cond_routes.type_ = "RoutesReady"
        cond_routes.state.value = 4

        cond_config = MagicMock()
        cond_config.type_ = "ConfigurationsReady"
        cond_config.state.value = 4

        mock_svc = MagicMock()
        mock_svc.uri = "https://api-xyz.run.app"
        mock_svc.conditions = [cond_routes, cond_config]

        mock_client.get_service = AsyncMock(return_value=mock_svc)

        with patch.dict(sys.modules, modules):
            provider = GCPProvider()
            state = await provider.status(_make_circuit(), _make_target())

            assert state.adapters["api"].status == NodeStatus.ACTIVE
            assert "api" in state.live_nodes

    async def test_status_not_ready(self):
        from baton.providers.gcp import GCPProvider

        modules, mock_client = _mock_gcp_modules()

        mock_svc = MagicMock()
        mock_svc.uri = "https://api-xyz.run.app"
        mock_svc.conditions = []  # No conditions = not ready

        mock_client.get_service = AsyncMock(return_value=mock_svc)

        with patch.dict(sys.modules, modules):
            provider = GCPProvider()
            state = await provider.status(_make_circuit(), _make_target())

            assert state.adapters["api"].status == NodeStatus.LISTENING

    async def test_status_service_not_found(self):
        from baton.providers.gcp import GCPProvider

        modules, mock_client = _mock_gcp_modules()
        mock_client.get_service = AsyncMock(side_effect=Exception("not found"))

        with patch.dict(sys.modules, modules):
            provider = GCPProvider()
            state = await provider.status(_make_circuit(), _make_target())

            assert state.adapters["api"].status == NodeStatus.IDLE
