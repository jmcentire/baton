# === Circuit Lifecycle Orchestration (src_baton_lifecycle) v1 ===
#  Dependencies: asyncio, logging, datetime, pathlib, baton.adapter, baton.adapter_control, baton.config, baton.process, baton.schemas, baton.state, baton.routing, baton.canary
# Manages the circuit lifecycle through states: init -> up -> [slot/swap] -> down. Orchestrates adapters, processes, and routing configurations for service deployment, including live services, mocks, A/B testing, and canary deployments.

# Module invariants:
#   - Logger is configured as 'baton.lifecycle'
#   - Port allocation: service_port = node.port + 20000 or node.port + 5000 if > 65535
#   - Process naming: base name, __a/__b for A/B, __stable/__canary for canary, __swap for swap
#   - State is persisted after mutations
#   - Adapters and controls are managed in parallel dictionaries keyed by node name

class LifecycleManager:
    """Orchestrates the circuit lifecycle with adapters, controls, processes, and state management."""
    project_dir: Path                        # required, Project directory path
    _adapters: dict[str, Adapter]            # required, Map of node name to adapter instances
    _controls: dict[str, AdapterControlServer] # required, Map of node name to control server instances
    _process_mgr: ProcessManager             # required, Process manager for service lifecycle
    _circuit: CircuitSpec | None             # required, Circuit specification
    _state: CircuitState | None              # required, Current circuit state

def _now_iso() -> str:
    """
    Returns the current UTC timestamp in ISO format.

    Postconditions:
      - Returns ISO 8601 formatted UTC timestamp string

    Side effects: reads system clock
    Idempotent: no
    """
    ...

def __init__(
    self: LifecycleManager,
    project_dir: str | Path,
) -> None:
    """
    Initialize the LifecycleManager with a project directory.

    Postconditions:
      - self.project_dir is set to Path(project_dir)
      - self._adapters is empty dict
      - self._controls is empty dict
      - self._process_mgr is initialized
      - self._circuit is None
      - self._state is None

    Side effects: none
    Idempotent: no
    """
    ...

def adapters(
    self: LifecycleManager,
) -> dict[str, Adapter]:
    """
    Property that returns a copy of the adapters dictionary.

    Postconditions:
      - Returns a shallow copy of self._adapters

    Side effects: none
    Idempotent: no
    """
    ...

def state(
    self: LifecycleManager,
) -> CircuitState | None:
    """
    Property that returns the current circuit state.

    Postconditions:
      - Returns self._state

    Side effects: none
    Idempotent: no
    """
    ...

def up(
    self: LifecycleManager,
    mock: bool = True,
) -> CircuitState:
    """
    Boot the circuit by starting all adapters and control servers. Initializes circuit state and saves it.

    Preconditions:
      - project_dir must be valid

    Postconditions:
      - Circuit configuration is loaded
      - Baton directory is ensured
      - All nodes have started adapters and control servers
      - Circuit state is created and saved
      - Returns the initialized CircuitState

    Side effects: Loads circuit configuration from project_dir, Creates baton directory if not exists, Starts adapter and control server for each node, Saves state to disk, Logs warning if no ingress nodes defined, Logs info about circuit startup
    Idempotent: no
    """
    ...

def down(
    self: LifecycleManager,
) -> None:
    """
    Tear down the circuit by stopping all adapters, control servers, and processes.

    Postconditions:
      - All processes are stopped
      - All control servers are stopped
      - All adapters are drained and stopped
      - Adapters and controls dictionaries are cleared
      - State is updated and saved if exists

    Side effects: Stops all managed processes, Stops all control servers, Drains and stops all adapters, Clears adapters and controls, Updates and saves state, Logs info message
    Idempotent: no
    """
    ...

def slot(
    self: LifecycleManager,
    node_name: str,
    command: str,
    env: dict[str, str] | None = None,
) -> None:
    """
    Slot a live service into a node's adapter by starting a process and configuring the backend.

    Preconditions:
      - node_name must exist in running circuit
      - adapter routing must not be locked
      - node must not be an egress node

    Postconditions:
      - Service process is started
      - Adapter backend is configured to point to service
      - State is updated with service information
      - Node is marked as live

    Errors:
      - node_not_found (ValueError): node_name not in self._adapters
          message: Node '{node_name}' not found in running circuit
      - routing_locked (RuntimeError): adapter.routing and adapter.routing.locked
          message: Cannot slot into '{node_name}': routing config is locked
      - egress_node (ValueError): node.role == NodeRole.EGRESS
          message: Cannot slot a live service into egress node

    Side effects: Starts a service process, Configures adapter backend, Updates circuit state, Saves state to disk, Logs info message
    Idempotent: no
    """
    ...

def swap(
    self: LifecycleManager,
    node_name: str,
    command: str,
    env: dict[str, str] | None = None,
) -> None:
    """
    Hot-swap a service by starting a new instance, draining connections, switching, and stopping the old instance.

    Preconditions:
      - node_name must exist in running circuit
      - adapter routing must not be locked

    Postconditions:
      - New service process is started
      - Old connections are drained
      - Adapter backend points to new service
      - Old process is stopped
      - State is updated with new service information

    Errors:
      - node_not_found (ValueError): node_name not in self._adapters
          message: Node '{node_name}' not found in running circuit
      - routing_locked (RuntimeError): adapter.routing and adapter.routing.locked
          message: Cannot swap in '{node_name}': routing config is locked

    Side effects: Starts new service process, Drains adapter connections, Stops old service process, Updates adapter backend, Updates and saves circuit state, Logs info message
    Idempotent: no
    """
    ...

def slot_mock(
    self: LifecycleManager,
    node_name: str,
) -> None:
    """
    Replace a live service with nothing (adapter returns 503).

    Preconditions:
      - node_name must exist in running circuit

    Postconditions:
      - Service process is stopped
      - Adapter backend is cleared
      - Node is marked as LISTENING
      - Node is removed from live_nodes
      - State is updated and saved

    Errors:
      - node_not_found (ValueError): node_name not in self._adapters
          message: Node '{node_name}' not found in running circuit

    Side effects: Stops service process, Clears adapter backend, Updates circuit state, Saves state to disk
    Idempotent: no
    """
    ...

def slot_ab(
    self: LifecycleManager,
    node_name: str,
    command_a: str,
    command_b: str,
    split: tuple[int, int] = (80, 20),
) -> None:
    """
    Start two instances (A and B) and configure weighted routing for A/B testing.

    Preconditions:
      - node_name must exist in running circuit
      - adapter routing must not be locked

    Postconditions:
      - Two service processes are started
      - Weighted routing is configured
      - State is updated with A/B configuration
      - Node is marked as live

    Errors:
      - node_not_found (ValueError): node_name not in self._adapters
          message: Node '{node_name}' not found in running circuit
      - routing_locked (RuntimeError): adapter.routing and adapter.routing.locked
          message: Cannot slot_ab into '{node_name}': routing config is locked

    Side effects: Starts two service processes, Configures weighted routing, Updates circuit state, Saves state to disk, Logs info message
    Idempotent: no
    """
    ...

def route_ab(
    self: LifecycleManager,
    node_name: str,
    command_b: str,
    split: tuple[int, int] = (80, 20),
) -> None:
    """
    Add a second instance to an existing service and configure weighted routing. Reuses the running service as instance A.

    Preconditions:
      - node_name must exist in running circuit
      - adapter routing must not be locked
      - A service must already be running on the node

    Postconditions:
      - Instance B is started
      - Existing service is renamed to instance A
      - Weighted routing is configured
      - State is updated with routing configuration

    Errors:
      - node_not_found (ValueError): node_name not in self._adapters
          message: Node '{node_name}' not found in running circuit
      - routing_locked (RuntimeError): adapter.routing and adapter.routing.locked
          message: Cannot route_ab on '{node_name}': routing config is locked
      - no_service_running (ValueError): not self._process_mgr.is_running(node_name) and not adapter.backend.is_configured
          message: No service running on '{node_name}'. Use 'baton slot' first

    Side effects: Starts instance B process, Renames existing process to __a, Configures weighted routing, Updates circuit state, Saves state to disk, Logs info message
    Idempotent: no
    """
    ...

def set_routing(
    self: LifecycleManager,
    node_name: str,
    config: RoutingConfig,
) -> None:
    """
    Set routing configuration on a node's adapter.

    Preconditions:
      - node_name must exist in running circuit

    Postconditions:
      - Routing config is set on adapter
      - State is updated if node exists in state

    Errors:
      - node_not_found (ValueError): node_name not in self._adapters
          message: Node '{node_name}' not found in running circuit

    Side effects: Sets routing on adapter, Updates circuit state, Saves state to disk
    Idempotent: no
    """
    ...

def lock_routing(
    self: LifecycleManager,
    node_name: str,
) -> None:
    """
    Lock routing config to prevent changes. Bypasses adapter lock via direct assignment.

    Preconditions:
      - node_name must exist in running circuit
      - Node must have routing config

    Postconditions:
      - Routing config is locked
      - State is updated with locked config

    Errors:
      - node_not_found (ValueError): node_name not in self._adapters
          message: Node '{node_name}' not found in running circuit
      - no_routing_config (ValueError): adapter.routing is None
          message: No routing config to lock on '{node_name}'

    Side effects: Locks routing config via direct attribute assignment, Updates circuit state, Saves state to disk
    Idempotent: no
    """
    ...

def unlock_routing(
    self: LifecycleManager,
    node_name: str,
) -> None:
    """
    Unlock routing config to allow changes.

    Preconditions:
      - node_name must exist in running circuit
      - Node must have routing config

    Postconditions:
      - Routing config is unlocked
      - State is updated with unlocked config

    Errors:
      - node_not_found (ValueError): node_name not in self._adapters
          message: Node '{node_name}' not found in running circuit
      - no_routing_config (ValueError): adapter.routing is None
          message: No routing config to unlock on '{node_name}'

    Side effects: Unlocks routing config via direct attribute assignment, Updates circuit state, Saves state to disk
    Idempotent: no
    """
    ...

def start_canary(
    self: LifecycleManager,
    node_name: str,
    command: str,
    canary_pct: int = 10,
    controller_opts: dict = None,
) -> CanaryController:
    """
    Start a canary deployment with automatic promotion/rollback. Starts the canary instance and returns a running CanaryController.

    Preconditions:
      - node_name must exist in running circuit
      - adapter routing must not be locked
      - A stable service must already be running

    Postconditions:
      - Canary service is started
      - Canary routing is configured
      - CanaryController is created and returned
      - State is updated

    Errors:
      - node_not_found (ValueError): node_name not in self._adapters
          message: Node '{node_name}' not found in running circuit
      - routing_locked (RuntimeError): adapter.routing and adapter.routing.locked
          message: Cannot start canary on '{node_name}': routing config is locked
      - no_stable_service (ValueError): not self._process_mgr.is_running(node_name) and not adapter.backend.is_configured
          message: No service running on '{node_name}'. Use 'baton slot' first

    Side effects: Starts canary service process, Renames existing process to __stable, Configures canary routing, Updates circuit state, Saves state to disk
    Idempotent: no
    """
    ...

def restart_service(
    self: LifecycleManager,
    node_name: str,
) -> None:
    """
    Restart the service in a node (used by custodian).

    Preconditions:
      - node_name must exist in state
      - Node must have a non-mock service with command

    Postconditions:
      - Service is restarted via slot()

    Side effects: Calls slot() to restart service
    Idempotent: no
    """
    ...

def _compute_collapse_level(
    self: LifecycleManager,
) -> CollapseLevel:
    """
    Compute the collapse level based on live vs total nodes.

    Postconditions:
      - Returns FULL_MOCK if no state or circuit
      - Returns FULL_MOCK if no live nodes
      - Returns FULL_LIVE if all nodes are live
      - Returns PARTIAL if some nodes are live

    Side effects: none
    Idempotent: no
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['LifecycleManager', '_now_iso', 'adapters', 'state', 'up', 'down', 'slot', 'swap', 'slot_mock', 'slot_ab', 'route_ab', 'set_routing', 'lock_routing', 'unlock_routing', 'start_canary', 'restart_service', '_compute_collapse_level']
