"""Process management for Baton.

Start, stop, and track service processes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import signal
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ProcessInfo:
    """Tracked process information."""

    command: str
    pid: int
    process: asyncio.subprocess.Process
    node_name: str = ""


_ENV_VAR_RE = re.compile(r"\$([A-Z_][A-Z0-9_]*)")
_SHELL_META_RE = re.compile(r"[;&|`$()\{}<>!]")


def _safe_expand_command(command: str, env: dict[str, str]) -> list[str]:
    """Expand $VAR references from env dict, reject shell metacharacters, tokenize.

    Raises ValueError if the expanded command contains disallowed shell metacharacters.
    """
    def _replacer(m: re.Match) -> str:
        return env.get(m.group(1), m.group(0))

    expanded = _ENV_VAR_RE.sub(_replacer, command)

    # After expansion, reject remaining shell metacharacters
    remaining = _SHELL_META_RE.search(expanded)
    if remaining:
        raise ValueError(
            f"Command contains disallowed shell metacharacter: '{remaining.group()}'"
        )

    return shlex.split(expanded)


class ProcessManager:
    """Manages service subprocesses."""

    def __init__(self):
        self._processes: dict[str, ProcessInfo] = {}  # key = node_name

    @property
    def processes(self) -> dict[str, ProcessInfo]:
        return dict(self._processes)

    async def start(
        self,
        node_name: str,
        command: str,
        env: dict[str, str] | None = None,
    ) -> ProcessInfo:
        """Start a subprocess for a node.

        Args:
            node_name: The node this process serves.
            command: Shell command to run.
            env: Additional environment variables.
        """
        if node_name in self._processes:
            await self.stop(node_name)

        proc_env = dict(os.environ)
        if env:
            proc_env.update(env)

        args = _safe_expand_command(command, proc_env)
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=proc_env,
        )

        info = ProcessInfo(
            command=command,
            pid=proc.pid,
            process=proc,
            node_name=node_name,
        )
        self._processes[node_name] = info
        logger.info(f"Started process for [{node_name}]: pid={proc.pid} cmd={command}")
        return info

    async def stop(self, node_name: str, timeout: float = 10.0) -> None:
        """Stop a subprocess gracefully (SIGTERM, then SIGKILL after timeout)."""
        info = self._processes.pop(node_name, None)
        if info is None:
            return
        proc = info.process
        if proc.returncode is not None:
            return  # already exited

        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"Process [{node_name}] pid={info.pid} did not exit, sending SIGKILL")
                proc.kill()
                await proc.wait()
        except ProcessLookupError:
            pass  # already gone
        logger.info(f"Stopped process for [{node_name}]: pid={info.pid}")

    async def stop_all(self, timeout: float = 10.0) -> None:
        """Stop all tracked processes."""
        names = list(self._processes.keys())
        for name in names:
            await self.stop(name, timeout=timeout)

    def is_running(self, node_name: str) -> bool:
        """Check if a process is still running."""
        info = self._processes.get(node_name)
        if info is None:
            return False
        return info.process.returncode is None

    def get_pid(self, node_name: str) -> int | None:
        """Get the PID for a node's process."""
        info = self._processes.get(node_name)
        if info is None:
            return None
        return info.pid
