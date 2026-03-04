# === Local Deployment Provider (src_baton_providers_local) v1 ===
#  Dependencies: asyncio, logging, datetime, pathlib, baton.adapter, baton.collapse, baton.config, baton.lifecycle, baton.schemas
# Deploys circuit nodes as local processes using the LifecycleManager. This is the default provider for development and testing, supporting both mock and live node deployments.

# Module invariants:
#   - logger is module-level logging.Logger instance
#   - When _mgr is not None, it contains a valid LifecycleManager instance
#   - When _mock_server is not None, mock mode is active
#   - _mgr and _mock_server are both None after initialization and after teardown

class LocalProvider:
    """Deploy circuit as local processes with lifecycle management and optional mock server"""
    _mgr: LifecycleManager | None            # required, Lifecycle manager for local processes
    _mock_server: Any | None                 # required, Mock server instance when running in mock mode

def _now_iso() -> str:
    """
    Returns current UTC timestamp in ISO 8601 format

    Postconditions:
      - Returns ISO 8601 formatted UTC timestamp string

    Side effects: Reads system time
    Idempotent: no
    """
    ...

def __init__(
    self: LocalProvider,
) -> None:
    """
    Initialize LocalProvider with null manager and mock server

    Postconditions:
      - self._mgr is None
      - self._mock_server is None

    Side effects: Initializes instance state
    Idempotent: no
    """
    ...

def deploy(
    self: LocalProvider,
    circuit: CircuitSpec,
    target: DeploymentTarget,
) -> CircuitState:
    """
    Deploy circuit locally as processes with optional mock backends. Reads config options: project_dir (default '.'), mock (default 'true'), and live (comma-separated node names)

    Preconditions:
      - target.config is a dictionary-like object supporting .get()

    Postconditions:
      - self._mgr is a LifecycleManager instance
      - Returns CircuitState with adapter information
      - If mock=true: self._mock_server is set, mock backends configured, collapse_level set based on live_names
      - If live_names equals all circuit nodes: collapse_level is FULL_LIVE
      - If live_names is subset: collapse_level is PARTIAL
      - If no live_names: collapse_level is FULL_MOCK
      - state.live_nodes is set to list of live node names when mock=true
      - Logs deployment completion message

    Errors:
      - LifecycleManagerError (Exception): LifecycleManager.up() fails
      - MockServerError (Exception): Mock server start fails when mock=true

    Side effects: Creates LifecycleManager instance, Calls LifecycleManager.up() to start processes, May start mock server, May configure backends on adapters, Mutates NodeStatus for adapters, Logs info message
    Idempotent: no
    """
    ...

def teardown(
    self: LocalProvider,
    circuit: CircuitSpec,
    target: DeploymentTarget,
) -> None:
    """
    Tear down local deployment by stopping mock server and lifecycle manager

    Postconditions:
      - self._mock_server is None
      - self._mgr is None
      - If mock_server exists: it is stopped
      - If lifecycle manager exists: it is stopped via down()
      - Logs teardown completion message

    Errors:
      - MockServerStopError (Exception): Mock server stop fails
      - LifecycleManagerError (Exception): LifecycleManager.down() fails

    Side effects: Stops mock server if present, Calls LifecycleManager.down() if manager exists, Sets instance variables to None, Logs info message
    Idempotent: no
    """
    ...

def status(
    self: LocalProvider,
    circuit: CircuitSpec,
    target: DeploymentTarget,
) -> CircuitState:
    """
    Return current state of local deployment. Returns manager state if available, otherwise creates default state with FULL_MOCK

    Postconditions:
      - If self._mgr exists and has state: returns self._mgr.state
      - Otherwise: returns new CircuitState with circuit_name from circuit.name and collapse_level=FULL_MOCK

    Side effects: none
    Idempotent: no
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['LocalProvider', '_now_iso', 'deploy', 'teardown', 'status']
