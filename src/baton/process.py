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
    _log_tasks: list = field(default_factory=list, repr=False)


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
        log_handler: "Callable[[str, str, str], None] | None" = None,
    ) -> ProcessInfo:
        """Start a subprocess for a node.

        Args:
            node_name: The node this process serves.
            command: Shell command to run.
            env: Additional environment variables.
            log_handler: Optional callback(node_name, stream_name, line) for log capture.
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

        if log_handler and proc.stdout:
            task_out = asyncio.create_task(
                self._stream_lines(proc.stdout, node_name, "stdout", log_handler)
            )
            info._log_tasks.append(task_out)
        if log_handler and proc.stderr:
            task_err = asyncio.create_task(
                self._stream_lines(proc.stderr, node_name, "stderr", log_handler)
            )
            info._log_tasks.append(task_err)

        logger.info(f"Started process for [{node_name}]: pid={proc.pid} cmd={command}")
        return info

    async def stop(self, node_name: str, timeout: float = 10.0) -> None:
        """Stop a subprocess gracefully (SIGTERM, then SIGKILL after timeout)."""
        info = self._processes.pop(node_name, None)
        if info is None:
            return
        # Cancel log reading tasks
        for task in info._log_tasks:
            task.cancel()
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

    @staticmethod
    async def _stream_lines(
        stream: asyncio.StreamReader,
        node_name: str,
        stream_name: str,
        handler: "Callable[[str, str, str], None]",
    ) -> None:
        """Read lines from a stream and pass to handler."""
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\n\r")
                if text:
                    handler(node_name, stream_name, text)
        except (asyncio.CancelledError, Exception):
            pass
