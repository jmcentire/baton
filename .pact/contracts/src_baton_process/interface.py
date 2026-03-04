# === Baton Process Manager (src_baton_process) v1 ===
#  Dependencies: asyncio, logging, os, signal
# Process management for Baton. Provides functionality to start, stop, and track service subprocesses for nodes. Manages subprocess lifecycle with graceful termination (SIGTERM followed by SIGKILL on timeout).

# Module invariants:
#   - Each node_name maps to at most one ProcessInfo in _processes
#   - _processes keys are always valid node_name strings
#   - ProcessInfo.node_name matches the key in _processes dictionary

class ProcessInfo:
    """Tracked process information for a managed subprocess."""
    command: str                             # required, Shell command executed
    pid: int                                 # required, Process ID
    process: asyncio.subprocess.Process      # required, Subprocess object
    node_name: str = ""                      # optional, Node name this process serves

class ProcessManager:
    """Manages service subprocesses with tracking by node name. Maintains internal dictionary of ProcessInfo keyed by node_name."""
    _processes: dict[str, ProcessInfo]       # required, Internal process tracking dictionary keyed by node_name

def __init__() -> None:
    """
    Initialize a new ProcessManager with an empty process tracking dictionary.

    Postconditions:
      - self._processes is initialized as empty dict[str, ProcessInfo]

    Side effects: mutates_state
    Idempotent: no
    """
    ...

def processes() -> dict[str, ProcessInfo]:
    """
    Property getter that returns a copy of the tracked processes dictionary.

    Postconditions:
      - Returns a new dict containing current processes
      - Returned dict is a copy, not a reference to internal state

    Side effects: none
    Idempotent: no
    """
    ...

def start(
    node_name: str,
    command: str,
    env: dict[str, str] | None = None,
) -> ProcessInfo:
    """
    Start a subprocess for a node using shell command. If a process for the node_name already exists, it is stopped first. Creates subprocess with piped stdout/stderr and optional environment variables.

    Preconditions:
      - command is a valid shell command string

    Postconditions:
      - Subprocess is created and running
      - ProcessInfo is stored in self._processes[node_name]
      - ProcessInfo is returned with valid pid and process object
      - Log entry is written for process start

    Errors:
      - subprocess_creation_failure (OSError or subprocess-related exception): asyncio.create_subprocess_shell fails

    Side effects: mutates_state, logging, network_call
    Idempotent: no
    """
    ...

def stop(
    node_name: str,
    timeout: float = 10.0,
) -> None:
    """
    Stop a subprocess gracefully by sending SIGTERM. If process does not exit within timeout, sends SIGKILL. Removes the process from tracking. Does nothing if node_name is not found or process already exited.

    Postconditions:
      - Process is terminated and removed from self._processes
      - If process exists and is running, SIGTERM is sent
      - If timeout expires, SIGKILL is sent
      - Log entry is written for process stop

    Errors:
      - process_lookup_error (ProcessLookupError): Process already gone when trying to terminate
          handling: Exception is caught and ignored

    Side effects: mutates_state, logging
    Idempotent: no
    """
    ...

def stop_all(
    timeout: float = 10.0,
) -> None:
    """
    Stop all tracked processes by calling stop() for each node_name in the current process dictionary.

    Postconditions:
      - All processes in self._processes are stopped
      - self._processes becomes empty

    Side effects: mutates_state, logging
    Idempotent: no
    """
    ...

def is_running(
    node_name: str,
) -> bool:
    """
    Check if a process for the given node_name is tracked and still running (returncode is None).

    Postconditions:
      - Returns True if process exists and returncode is None
      - Returns False if process not found or has exited

    Side effects: none
    Idempotent: no
    """
    ...

def get_pid(
    node_name: str,
) -> int | None:
    """
    Get the PID for a node's tracked process. Returns None if process is not found.

    Postconditions:
      - Returns int PID if process is tracked
      - Returns None if node_name not found

    Side effects: none
    Idempotent: no
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['ProcessInfo', 'ProcessManager', 'processes', 'start', 'OSError or subprocess-related exception', 'stop', 'ProcessLookupError', 'stop_all', 'is_running', 'get_pid']
