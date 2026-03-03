"""Tests for process management."""

from __future__ import annotations

import asyncio

import pytest

from baton.process import ProcessManager


@pytest.fixture
def pm():
    return ProcessManager()


class TestProcessManager:
    async def test_start_and_stop(self, pm):
        info = await pm.start("api", "sleep 60")
        assert info.pid > 0
        assert pm.is_running("api")
        await pm.stop("api")
        assert not pm.is_running("api")

    async def test_get_pid(self, pm):
        await pm.start("api", "sleep 60")
        pid = pm.get_pid("api")
        assert pid is not None
        assert pid > 0
        await pm.stop("api")

    async def test_get_pid_missing(self, pm):
        assert pm.get_pid("missing") is None

    async def test_is_running_missing(self, pm):
        assert not pm.is_running("missing")

    async def test_stop_missing(self, pm):
        # Should not raise
        await pm.stop("missing")

    async def test_stop_all(self, pm):
        await pm.start("api", "sleep 60")
        await pm.start("db", "sleep 60")
        assert pm.is_running("api")
        assert pm.is_running("db")
        await pm.stop_all()
        assert not pm.is_running("api")
        assert not pm.is_running("db")

    async def test_start_replaces_existing(self, pm):
        info1 = await pm.start("api", "sleep 60")
        pid1 = info1.pid
        info2 = await pm.start("api", "sleep 60")
        pid2 = info2.pid
        assert pid1 != pid2
        assert pm.is_running("api")
        await pm.stop("api")

    async def test_process_with_env(self, pm):
        info = await pm.start("api", "echo $BATON_TEST", env={"BATON_TEST": "hello"})
        assert info.pid > 0
        await info.process.wait()

    async def test_processes_dict(self, pm):
        await pm.start("api", "sleep 60")
        procs = pm.processes
        assert "api" in procs
        await pm.stop_all()

    async def test_short_lived_process(self, pm):
        await pm.start("api", "echo done")
        await asyncio.sleep(0.2)
        assert not pm.is_running("api")
