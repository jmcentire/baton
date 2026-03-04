"""Tests for process management."""

from __future__ import annotations

import asyncio

import pytest

from baton.process import ProcessManager, _safe_expand_command


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
        stdout, _ = await info.process.communicate()
        assert b"hello" in stdout

    async def test_processes_dict(self, pm):
        await pm.start("api", "sleep 60")
        procs = pm.processes
        assert "api" in procs
        await pm.stop_all()

    async def test_short_lived_process(self, pm):
        info = await pm.start("api", "echo done")
        await info.process.wait()
        assert not pm.is_running("api")


class TestSafeExpandCommand:
    def test_simple_command(self):
        result = _safe_expand_command("echo hello", {})
        assert result == ["echo", "hello"]

    def test_env_var_expansion(self):
        result = _safe_expand_command(
            "python3 -m http.server $BATON_PORT",
            {"BATON_PORT": "8080"},
        )
        assert result == ["python3", "-m", "http.server", "8080"]

    def test_unexpanded_var_rejected(self):
        # $MISSING_VAR is not in env so it remains as-is with $, which is rejected
        with pytest.raises(ValueError, match="disallowed shell metacharacter"):
            _safe_expand_command("echo $MISSING_VAR", {})

    def test_rejects_semicolon_injection(self):
        with pytest.raises(ValueError, match="disallowed shell metacharacter"):
            _safe_expand_command("echo hello; rm -rf /", {})

    def test_rejects_pipe_injection(self):
        with pytest.raises(ValueError, match="disallowed shell metacharacter"):
            _safe_expand_command("echo hello | cat", {})

    def test_rejects_ampersand(self):
        with pytest.raises(ValueError, match="disallowed shell metacharacter"):
            _safe_expand_command("sleep 60 &", {})

    def test_rejects_backtick(self):
        with pytest.raises(ValueError, match="disallowed shell metacharacter"):
            _safe_expand_command("echo `whoami`", {})

    def test_rejects_subshell(self):
        with pytest.raises(ValueError, match="disallowed shell metacharacter"):
            _safe_expand_command("echo $(whoami)", {})

    def test_normal_command_with_flags(self):
        result = _safe_expand_command("python3 -m http.server 8080", {})
        assert result == ["python3", "-m", "http.server", "8080"]

    def test_quoted_arguments(self):
        result = _safe_expand_command('echo "hello world"', {})
        assert result == ["echo", "hello world"]
