"""Tests for circuit lifecycle orchestration."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from baton.cli import main as cli_main
from baton.config import load_circuit
from baton.lifecycle import LifecycleManager
from baton.schemas import CollapseLevel, NodeStatus


def _init_project(d: Path) -> None:
    """Set up a project directory with a 2-node circuit."""
    cli_main(["init", str(d)])
    cli_main(["node", "add", "api", "--port", "17001", "--dir", str(d)])
    cli_main(["node", "add", "service", "--port", "17002", "--dir", str(d)])
    cli_main(["edge", "add", "api", "service", "--dir", str(d)])


class TestLifecycleUpDown:
    async def test_up_creates_adapters(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        try:
            state = await mgr.up(mock=True)
            assert len(mgr.adapters) == 2
            assert state.collapse_level == CollapseLevel.FULL_MOCK
            assert "api" in state.adapters
            assert "service" in state.adapters
            assert state.adapters["api"].status == NodeStatus.LISTENING
        finally:
            await mgr.down()

    async def test_down_cleans_up(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        await mgr.up(mock=True)
        await mgr.down()
        assert len(mgr.adapters) == 0

    async def test_adapters_respond_503_when_no_backend(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        try:
            await mgr.up(mock=True)
            reader, writer = await asyncio.open_connection("127.0.0.1", 17001)
            writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            assert b"503" in response
            writer.close()
        finally:
            await mgr.down()


class TestLifecycleSlot:
    async def test_slot_service(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        try:
            await mgr.up(mock=True)
            # Start a simple HTTP server as the service
            await mgr.slot(
                "api",
                "python3 -m http.server $BATON_SERVICE_PORT",
            )
            state = mgr.state
            assert state.adapters["api"].status == NodeStatus.ACTIVE
            assert state.adapters["api"].service.is_mock is False
            assert "api" in state.live_nodes
            assert state.collapse_level == CollapseLevel.PARTIAL
        finally:
            await mgr.down()

    async def test_slot_missing_node(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        try:
            await mgr.up(mock=True)
            with pytest.raises(ValueError, match="not found"):
                await mgr.slot("missing", "echo hi")
        finally:
            await mgr.down()


class TestLifecycleSlotMock:
    async def test_slot_mock(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        try:
            await mgr.up(mock=True)
            await mgr.slot(
                "api",
                "python3 -m http.server $BATON_SERVICE_PORT",
            )
            assert mgr.state.collapse_level == CollapseLevel.PARTIAL

            await mgr.slot_mock("api")
            assert mgr.state.adapters["api"].status == NodeStatus.LISTENING
            assert "api" not in mgr.state.live_nodes
            assert mgr.state.collapse_level == CollapseLevel.FULL_MOCK
        finally:
            await mgr.down()


class TestCollapseLevel:
    async def test_all_live(self, project_dir: Path):
        d = project_dir / "p"
        _init_project(d)
        mgr = LifecycleManager(d)
        try:
            await mgr.up(mock=True)
            await mgr.slot("api", "python3 -m http.server $BATON_SERVICE_PORT")
            await mgr.slot("service", "python3 -m http.server $BATON_SERVICE_PORT")
            assert mgr.state.collapse_level == CollapseLevel.FULL_LIVE
        finally:
            await mgr.down()
