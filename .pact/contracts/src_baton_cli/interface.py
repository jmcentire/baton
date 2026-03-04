# === Baton CLI Entry Point (src_baton_cli) v1 ===
#  Dependencies: argparse, asyncio, signal, sys, pathlib, baton.circuit, baton.config, baton.schemas, baton.state, baton.lifecycle, baton.collapse, baton.custodian, baton.providers, baton.signals, baton.telemetry, baton.dashboard, baton.dashboard_server, baton.image, baton.manifest, baton.compat
# Command-line interface for the Baton cloud-agnostic circuit orchestration system. Provides commands for initializing circuits, managing nodes and edges, controlling lifecycle (up/down/slot/swap), routing configuration, deployment to providers, telemetry/metrics/signals, and compatibility checking.

# Module invariants:
#   - CONFIG_FILENAME is 'baton.yaml'
#   - Exit code 0 indicates success
#   - Exit code 1 indicates error or validation failure
#   - Exit code 130 indicates KeyboardInterrupt
#   - All async commands are dispatched through _cmd_async or specific async dispatchers
#   - All file operations use args.dir as project directory base
#   - Lifecycle manager is started with up() before node operations
#   - Circuit config changes are immediately saved to filesystem

def main(
    argv: list[str] | None = None,
) -> int:
    """
    Main CLI entry point that parses command-line arguments and dispatches to appropriate subcommand handlers. Returns exit code (0 for success, non-zero for errors).

    Postconditions:
      - Returns 0 on successful command execution
      - Returns 1 on command parsing errors, validation errors, or missing command
      - Returns 130 on KeyboardInterrupt

    Errors:
      - ValueError (ValueError): Invalid argument values or command configuration
          exit_code: 1
      - FileNotFoundError (FileNotFoundError): Required configuration files or directories not found
          exit_code: 1
      - KeyboardInterrupt (KeyboardInterrupt): User interrupts with Ctrl+C
          exit_code: 130

    Side effects: Prints help or error messages to stdout/stderr, Invokes subcommand handlers that may modify filesystem, start processes, or make network calls
    Idempotent: no
    """
    ...

def _cmd_async(
    args: argparse.Namespace,
) -> int:
    """
    Async dispatcher that routes async commands (up, down, slot, swap, collapse, watch, route, deploy, teardown, deploy-status, dashboard, image) to their handlers.

    Preconditions:
      - args.command is one of: up, down, slot, swap, collapse, watch, route, deploy, teardown, deploy-status, dashboard, image

    Postconditions:
      - Returns exit code from delegated command handler
      - Returns 1 if command not recognized

    Side effects: Delegates to async command handlers
    Idempotent: no
    """
    ...

def _cmd_up(
    args: argparse.Namespace,
) -> int:
    """
    Boots the circuit, optionally deriving from service manifests, starting mocked backends, and keeping the circuit running until interrupted.

    Postconditions:
      - Circuit is running with adapters started
      - If args.mock is True, mock server is running
      - Returns 0 after circuit is stopped

    Side effects: Loads or derives circuit configuration, Starts LifecycleManager and adapters, Starts mock server if mock=True, Blocks until SIGINT/SIGTERM or KeyboardInterrupt, Stops mock server and lifecycle manager on exit
    Idempotent: no
    """
    ...

def _cmd_down(
    args: argparse.Namespace,
) -> int:
    """
    Tears down the circuit by clearing persisted state.

    Postconditions:
      - Circuit state is cleared from filesystem
      - Returns 0

    Side effects: Removes circuit state files
    Idempotent: no
    """
    ...

def _cmd_slot(
    args: argparse.Namespace,
) -> int:
    """
    Slots a service into a node by starting a command. Requires non-mock mode and a command argument.

    Preconditions:
      - args.mock is False or user is directed to use 'baton collapse'
      - args.command is provided if args.mock is False

    Postconditions:
      - Service is slotted into node
      - Returns 0 on success
      - Returns 1 if mock mode or no command

    Errors:
      - MockModeError (ValueError): args.mock is True
          exit_code: 1
      - NoCommandError (ValueError): args.command is None or empty when not in mock mode
          exit_code: 1

    Side effects: Starts lifecycle manager, Slots service into node
    Idempotent: no
    """
    ...

def _cmd_swap(
    args: argparse.Namespace,
) -> int:
    """
    Hot-swaps a service in a node with a new command.

    Postconditions:
      - Service in node is swapped to new command
      - Returns 0

    Side effects: Starts lifecycle manager, Swaps service in node
    Idempotent: no
    """
    ...

def _cmd_collapse(
    args: argparse.Namespace,
) -> int:
    """
    Collapses circuit to minimal mock, keeping specified nodes live. Validates live nodes, strips egress nodes, starts mock server, and waits for interrupt.

    Postconditions:
      - Circuit is running with specified nodes live and others mocked
      - Returns 0 after shutdown
      - Returns 1 if unknown nodes specified

    Errors:
      - UnknownNodeError (ValueError): Live nodes specified that don't exist in circuit
          exit_code: 1

    Side effects: Starts lifecycle manager, Starts mock server, Updates adapter backends, Blocks until interrupt, Stops mock server and lifecycle on exit
    Idempotent: no
    """
    ...

def _cmd_watch(
    args: argparse.Namespace,
) -> int:
    """
    Starts the custodian monitor that watches node health at specified poll interval until interrupted.

    Postconditions:
      - Custodian monitor runs until interrupted
      - Returns 0 after shutdown

    Side effects: Starts lifecycle manager, Starts custodian monitor task, Blocks until interrupt, Stops custodian and lifecycle on exit
    Idempotent: no
    """
    ...

def _cmd_route_show(
    args: argparse.Namespace,
) -> int:
    """
    Displays routing configuration for a node by reading from persisted state. Synchronous command.

    Postconditions:
      - Prints routing config as JSON or single backend message
      - Returns 0 if node found
      - Returns 1 if node not found

    Errors:
      - NodeNotFoundError (ValueError): Node not found in circuit state
          exit_code: 1

    Side effects: Reads state from filesystem
    Idempotent: no
    """
    ...

def _cmd_route_async(
    args: argparse.Namespace,
) -> int:
    """
    Async dispatcher for route subcommands: ab, canary, set, lock, unlock, clear.

    Preconditions:
      - args.route_command is one of: ab, canary, set, lock, unlock, clear

    Postconditions:
      - Returns exit code from delegated route handler
      - Returns 1 if route_command not recognized

    Side effects: Delegates to route command handlers
    Idempotent: no
    """
    ...

def _cmd_route_ab(
    args: argparse.Namespace,
) -> int:
    """
    Configures A/B routing split for a node. Parses split ratio (e.g., '80/20'), starts lifecycle manager, and configures weighted routing.

    Preconditions:
      - args.split is in 'A/B' format with integer values

    Postconditions:
      - A/B routing configured for node
      - Returns 0 on success
      - Returns 1 if split format invalid

    Errors:
      - InvalidSplitFormatError (ValueError): args.split not in A/B format or non-integer values
          exit_code: 1

    Side effects: Starts lifecycle manager, Configures routing
    Idempotent: no
    """
    ...

def _cmd_route_canary(
    args: argparse.Namespace,
) -> int:
    """
    Configures canary deployment with optional auto-promotion based on error rate and latency thresholds. If --promote is set, starts canary controller and waits for result.

    Postconditions:
      - Canary routing configured
      - If promote=True, canary controller runs until completion
      - Returns 0

    Side effects: Starts lifecycle manager, Configures canary routing, If promote=True, starts canary controller task
    Idempotent: no
    """
    ...

def _cmd_route_set(
    args: argparse.Namespace,
) -> int:
    """
    Sets custom routing configuration (weighted or header-based) for a node. Parses targets and rules from command-line strings.

    Preconditions:
      - args.strategy is 'weighted' or 'header'
      - args.targets format is 'name:port:weight,...' or 'name:port,...'

    Postconditions:
      - Routing config set for node
      - Returns 0 on success
      - Returns 1 if target or rule parsing fails

    Errors:
      - InvalidTargetFormatError (ValueError): Target string not in valid format
          exit_code: 1
      - InvalidRuleFormatError (ValueError): Rule string not in valid format
          exit_code: 1

    Side effects: Starts lifecycle manager, Sets routing config
    Idempotent: no
    """
    ...

def _cmd_route_lock(
    args: argparse.Namespace,
) -> int:
    """
    Locks routing configuration for a node to prevent changes.

    Postconditions:
      - Routing config locked for node
      - Returns 0

    Side effects: Starts lifecycle manager, Locks routing
    Idempotent: no
    """
    ...

def _cmd_route_unlock(
    args: argparse.Namespace,
) -> int:
    """
    Unlocks routing configuration for a node to allow changes.

    Postconditions:
      - Routing config unlocked for node
      - Returns 0

    Side effects: Starts lifecycle manager, Unlocks routing
    Idempotent: no
    """
    ...

def _cmd_route_clear(
    args: argparse.Namespace,
) -> int:
    """
    Clears routing configuration for a node, reverting to single backend.

    Postconditions:
      - Routing config cleared for node
      - Returns 0 on success
      - Returns 1 if node not found

    Errors:
      - NodeNotFoundError (ValueError): Node not found in lifecycle manager adapters
          exit_code: 1

    Side effects: Starts lifecycle manager, Clears routing config
    Idempotent: no
    """
    ...

def _build_deploy_target(
    args: argparse.Namespace,
) -> DeploymentTarget:
    """
    Constructs a DeploymentTarget from parsed arguments, extracting provider, region, namespace, and config dictionary.

    Postconditions:
      - Returns DeploymentTarget with populated config dictionary

    Side effects: None - pure transformation
    Idempotent: no
    """
    ...

def _cmd_deploy(
    args: argparse.Namespace,
) -> int:
    """
    Deploys circuit to a provider (local, gcp, aws). Loads circuit, creates provider, deploys, and for local provider waits for interrupt.

    Postconditions:
      - Circuit deployed to provider
      - If provider is local, blocks until interrupted then tears down
      - Returns 0

    Side effects: Loads circuit configuration, Creates provider instance, Deploys circuit via provider, For local provider, blocks until interrupt then tears down
    Idempotent: no
    """
    ...

def _cmd_teardown(
    args: argparse.Namespace,
) -> int:
    """
    Tears down a deployed circuit from a provider.

    Postconditions:
      - Circuit torn down from provider
      - Returns 0

    Side effects: Loads circuit configuration, Creates provider instance, Tears down circuit via provider
    Idempotent: no
    """
    ...

def _cmd_deploy_status(
    args: argparse.Namespace,
) -> int:
    """
    Checks and displays deployment status for a circuit on a provider.

    Postconditions:
      - Deployment status printed to stdout
      - Returns 0

    Side effects: Loads circuit configuration, Queries provider for status, Prints status information
    Idempotent: no
    """
    ...

def _cmd_signals(
    args: argparse.Namespace,
) -> int:
    """
    Shows request signals from signal history. Can filter by node, path, and display last N records or per-path statistics.

    Postconditions:
      - Signal data printed to stdout
      - Returns 0 if signals found
      - Returns 1 if no signals found

    Errors:
      - NoSignalsFoundError (ValueError): No signal data found
          exit_code: 1

    Side effects: Loads signal history from filesystem, Computes statistics if --stats flag set, Prints signal records or statistics
    Idempotent: no
    """
    ...

def _cmd_metrics(
    args: argparse.Namespace,
) -> int:
    """
    Shows persistent metrics from telemetry collector. Can filter by node, show last N snapshots, or output in Prometheus format.

    Postconditions:
      - Metrics data printed to stdout
      - Returns 0 if metrics found
      - Returns 1 if no metrics found

    Errors:
      - NoMetricsFoundError (ValueError): No metrics data found
          exit_code: 1

    Side effects: Loads metrics history from filesystem, Formats as Prometheus or JSON, Prints metrics data
    Idempotent: no
    """
    ...

def _cmd_dashboard(
    args: argparse.Namespace,
) -> int:
    """
    Shows aggregated circuit metrics. Can serve interactive dashboard on HTTP server or collect snapshot and display as JSON/table.

    Postconditions:
      - If --serve, dashboard server runs until interrupted
      - Otherwise, snapshot printed to stdout
      - Returns 0 on success
      - Returns 1 if no circuit state found for non-serve mode

    Errors:
      - NoStateFoundError (ValueError): No circuit state found in non-serve mode
          exit_code: 1

    Side effects: Loads circuit and state, Starts lifecycle manager, If --serve, starts HTTP server and signal aggregator, Collects metrics snapshot, Prints formatted output
    Idempotent: no
    """
    ...

def _cmd_image_list(
    args: argparse.Namespace,
) -> int:
    """
    Lists built container images with node name, tag, and build timestamp.

    Postconditions:
      - Image list printed to stdout
      - Returns 0

    Side effects: Loads image metadata from filesystem, Prints formatted table
    Idempotent: no
    """
    ...

def _cmd_image_async(
    args: argparse.Namespace,
) -> int:
    """
    Async dispatcher for image subcommands: build, push.

    Preconditions:
      - args.image_command is 'build' or 'push'

    Postconditions:
      - Returns exit code from delegated image handler
      - Returns 1 if image_command not recognized

    Side effects: Delegates to image command handlers
    Idempotent: no
    """
    ...

def _cmd_image_build(
    args: argparse.Namespace,
) -> int:
    """
    Builds a container image for a node. Requires --node and either --path or node metadata with service_dir.

    Preconditions:
      - args.node is provided
      - args.path is provided or node metadata contains service_dir

    Postconditions:
      - Container image built
      - Image info printed to stdout
      - Returns 0 on success
      - Returns 1 if --node or service_dir missing

    Errors:
      - MissingNodeError (ValueError): --node not provided
          exit_code: 1
      - MissingPathError (ValueError): --path not provided and node metadata lacks service_dir
          exit_code: 1

    Side effects: Loads circuit configuration, Invokes Docker/container build, Saves image metadata
    Idempotent: no
    """
    ...

def _cmd_image_push(
    args: argparse.Namespace,
) -> int:
    """
    Pushes a container image to registry. Requires --tag or --node (to look up tag from metadata).

    Preconditions:
      - args.tag is provided or args.node is provided and has built image

    Postconditions:
      - Image pushed to registry
      - Returns 0 on success
      - Returns 1 if tag cannot be resolved

    Errors:
      - MissingTagError (ValueError): --tag or --node required and cannot be resolved
          exit_code: 1

    Side effects: Loads image metadata, Pushes image to container registry
    Idempotent: no
    """
    ...

def _cmd_init(
    args: argparse.Namespace,
) -> int:
    """
    Initializes a new circuit by creating project directory, circuit config file, and baton state directory.

    Postconditions:
      - Project directory created if it doesn't exist
      - Circuit config file (baton.yaml) created
      - Baton state directory created
      - Returns 0 on success
      - Returns 1 if config file already exists

    Errors:
      - ConfigExistsError (ValueError): baton.yaml already exists in project directory
          exit_code: 1

    Side effects: Creates project directory, Writes circuit config file, Creates baton state directory
    Idempotent: no
    """
    ...

def _cmd_node(
    args: argparse.Namespace,
) -> int:
    """
    Manages circuit nodes: add or remove. Loads circuit, applies operation, and saves updated circuit.

    Preconditions:
      - args.node_command is 'add' or 'rm'

    Postconditions:
      - Circuit updated with node added or removed
      - Updated circuit saved to filesystem
      - Returns 0 on success
      - Returns 1 if node_command invalid

    Errors:
      - InvalidNodeCommandError (ValueError): node_command not in {add, rm}
          exit_code: 1

    Side effects: Loads circuit from filesystem, Modifies circuit structure, Saves circuit to filesystem
    Idempotent: no
    """
    ...

def _cmd_edge(
    args: argparse.Namespace,
) -> int:
    """
    Manages circuit edges: add or remove. Loads circuit, applies operation, and saves updated circuit.

    Preconditions:
      - args.edge_command is 'add' or 'rm'

    Postconditions:
      - Circuit updated with edge added or removed
      - Updated circuit saved to filesystem
      - Returns 0 on success
      - Returns 1 if edge_command invalid

    Errors:
      - InvalidEdgeCommandError (ValueError): edge_command not in {add, rm}
          exit_code: 1

    Side effects: Loads circuit from filesystem, Modifies circuit edges, Saves circuit to filesystem
    Idempotent: no
    """
    ...

def _cmd_contract(
    args: argparse.Namespace,
) -> int:
    """
    Sets contract for a node. Loads circuit, applies contract spec path, and saves updated circuit.

    Preconditions:
      - args.contract_command is 'set'

    Postconditions:
      - Contract set for node
      - Updated circuit saved to filesystem
      - Returns 0 on success
      - Returns 1 if contract_command invalid

    Errors:
      - InvalidContractCommandError (ValueError): contract_command not 'set'
          exit_code: 1

    Side effects: Loads circuit from filesystem, Updates node contract, Saves circuit to filesystem
    Idempotent: no
    """
    ...

def _cmd_service(
    args: argparse.Namespace,
) -> int:
    """
    Manages service manifests: register, list, or derive circuit from services.

    Preconditions:
      - args.service_command is one of: register, list, derive

    Postconditions:
      - For register: service path added to registry
      - For list: service manifests listed to stdout
      - For derive: circuit derived and optionally saved
      - Returns 0 on success
      - Returns 1 if service_command invalid

    Errors:
      - InvalidServiceCommandError (ValueError): service_command not in {register, list, derive}
          exit_code: 1

    Side effects: For register: validates and registers service manifest, For list: loads and displays service manifests, For derive: loads manifests, derives circuit, optionally saves
    Idempotent: no
    """
    ...

def _cmd_check(
    args: argparse.Namespace,
) -> int:
    """
    Runs compatibility check on service manifests. Checks contracts between services and reports issues.

    Postconditions:
      - Compatibility report printed to stdout
      - Returns 0 if all compatible
      - Returns 1 if issues found or no services registered

    Errors:
      - NoServicesError (ValueError): No services registered
          exit_code: 1
      - ServiceNotFoundError (ValueError): Specified service not found
          exit_code: 1
      - IncompatibilityError (ValueError): Compatibility issues found
          exit_code: 1

    Side effects: Loads service manifests, Runs compatibility checks, Prints issues or success message
    Idempotent: no
    """
    ...

def _cmd_status(
    args: argparse.Namespace,
) -> int:
    """
    Shows circuit status including nodes, edges, and runtime state if available.

    Postconditions:
      - Circuit status printed to stdout
      - Returns 0

    Side effects: Loads circuit configuration, Loads runtime state if available, Prints formatted status
    Idempotent: no
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['main', 'KeyboardInterrupt', '_cmd_async', '_cmd_up', '_cmd_down', '_cmd_slot', '_cmd_swap', '_cmd_collapse', '_cmd_watch', '_cmd_route_show', '_cmd_route_async', '_cmd_route_ab', '_cmd_route_canary', '_cmd_route_set', '_cmd_route_lock', '_cmd_route_unlock', '_cmd_route_clear', '_build_deploy_target', '_cmd_deploy', '_cmd_teardown', '_cmd_deploy_status', '_cmd_signals', '_cmd_metrics', '_cmd_dashboard', '_cmd_image_list', '_cmd_image_async', '_cmd_image_build', '_cmd_image_push', '_cmd_init', '_cmd_node', '_cmd_edge', '_cmd_contract', '_cmd_service', '_cmd_check', '_cmd_status']
