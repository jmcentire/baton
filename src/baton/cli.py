"""Baton CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

from baton.circuit import add_edge, add_node, remove_edge, remove_node, set_contract
from baton.config import CONFIG_FILENAME, load_circuit, save_circuit
from baton.schemas import CircuitSpec, NodeStatus
from baton.state import ensure_baton_dir, load_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="baton",
        description="Cloud-agnostic circuit orchestration.",
    )
    sub = parser.add_subparsers(dest="command")

    # baton init
    p_init = sub.add_parser("init", help="Initialize a new circuit")
    p_init.add_argument("dir", nargs="?", default=".", help="Project directory")
    p_init.add_argument("--name", default="default", help="Circuit name")

    # baton node
    p_node = sub.add_parser("node", help="Manage nodes")
    node_sub = p_node.add_subparsers(dest="node_command")

    p_node_add = node_sub.add_parser("add", help="Add a node")
    p_node_add.add_argument("name", help="Node name")
    p_node_add.add_argument("--port", type=int, default=0, help="Port number")
    p_node_add.add_argument("--mode", default="http", choices=["http", "tcp"], help="Proxy mode")
    p_node_add.add_argument("--dir", default=".", help="Project directory")

    p_node_rm = node_sub.add_parser("rm", help="Remove a node")
    p_node_rm.add_argument("name", help="Node name")
    p_node_rm.add_argument("--dir", default=".", help="Project directory")

    # baton edge
    p_edge = sub.add_parser("edge", help="Manage edges")
    edge_sub = p_edge.add_subparsers(dest="edge_command")

    p_edge_add = edge_sub.add_parser("add", help="Add an edge")
    p_edge_add.add_argument("source", help="Source node")
    p_edge_add.add_argument("target", help="Target node")
    p_edge_add.add_argument("--dir", default=".", help="Project directory")

    p_edge_rm = edge_sub.add_parser("rm", help="Remove an edge")
    p_edge_rm.add_argument("source", help="Source node")
    p_edge_rm.add_argument("target", help="Target node")
    p_edge_rm.add_argument("--dir", default=".", help="Project directory")

    # baton contract
    p_contract = sub.add_parser("contract", help="Manage contracts")
    contract_sub = p_contract.add_subparsers(dest="contract_command")

    p_contract_set = contract_sub.add_parser("set", help="Set contract for a node")
    p_contract_set.add_argument("node", help="Node name")
    p_contract_set.add_argument("spec", help="Path to contract spec")
    p_contract_set.add_argument("--dir", default=".", help="Project directory")

    # baton status
    p_status = sub.add_parser("status", help="Show circuit status")
    p_status.add_argument("--dir", default=".", help="Project directory")

    # baton up
    p_up = sub.add_parser("up", help="Boot the circuit")
    p_up.add_argument("--mock", action="store_true", default=True, help="Start with all nodes mocked (default)")
    p_up.add_argument("--services", action="store_true", help="Derive circuit from service manifests")
    p_up.add_argument("--dir", default=".", help="Project directory")

    # baton down
    p_down = sub.add_parser("down", help="Tear down the circuit")
    p_down.add_argument("--dir", default=".", help="Project directory")

    # baton slot
    p_slot = sub.add_parser("slot", help="Slot a service into a node")
    p_slot.add_argument("node", help="Node name")
    p_slot.add_argument("command", nargs="?", help="Command to run (omit for --mock)")
    p_slot.add_argument("--mock", action="store_true", help="Slot a mock instead")
    p_slot.add_argument("--dir", default=".", help="Project directory")

    # baton swap
    p_swap = sub.add_parser("swap", help="Hot-swap a service in a node")
    p_swap.add_argument("node", help="Node name")
    p_swap.add_argument("command", help="Command to run")
    p_swap.add_argument("--dir", default=".", help="Project directory")

    # baton collapse
    p_collapse = sub.add_parser("collapse", help="Collapse circuit to minimal mock")
    p_collapse.add_argument("--live", default="", help="Comma-separated nodes to keep live")
    p_collapse.add_argument("--dir", default=".", help="Project directory")

    # baton watch
    p_watch = sub.add_parser("watch", help="Start the custodian monitor")
    p_watch.add_argument("--dir", default=".", help="Project directory")
    p_watch.add_argument("--interval", type=float, default=5.0, help="Poll interval in seconds")

    # baton service
    p_service = sub.add_parser("service", help="Manage service manifests")
    svc_sub = p_service.add_subparsers(dest="service_command")

    p_svc_register = svc_sub.add_parser("register", help="Register a service")
    p_svc_register.add_argument("path", help="Path to service directory")
    p_svc_register.add_argument("--dir", default=".", help="Project directory")

    p_svc_list = svc_sub.add_parser("list", help="List registered services")
    p_svc_list.add_argument("--dir", default=".", help="Project directory")

    p_svc_derive = svc_sub.add_parser("derive", help="Derive circuit from services")
    p_svc_derive.add_argument("--dir", default=".", help="Project directory")
    p_svc_derive.add_argument("--save", action="store_true", help="Save derived circuit to baton.yaml")

    # baton route
    p_route = sub.add_parser("route", help="Manage A/B routing")
    route_sub = p_route.add_subparsers(dest="route_command")

    p_route_show = route_sub.add_parser("show", help="Show routing config for a node")
    p_route_show.add_argument("node", help="Node name")
    p_route_show.add_argument("--dir", default=".", help="Project directory")

    p_route_ab = route_sub.add_parser("ab", help="A/B split with a new service instance")
    p_route_ab.add_argument("node", help="Node name")
    p_route_ab.add_argument("command", help="Command for instance B")
    p_route_ab.add_argument("--split", default="80/20", help="Weight split A/B (default: 80/20)")
    p_route_ab.add_argument("--dir", default=".", help="Project directory")

    p_route_canary = route_sub.add_parser("canary", help="Canary rollout")
    p_route_canary.add_argument("node", help="Node name")
    p_route_canary.add_argument("command", help="Command for canary instance")
    p_route_canary.add_argument("--pct", type=int, default=10, help="Canary percentage (default: 10)")
    p_route_canary.add_argument("--dir", default=".", help="Project directory")

    p_route_set = route_sub.add_parser("set", help="Set custom routing config")
    p_route_set.add_argument("node", help="Node name")
    p_route_set.add_argument("--strategy", required=True, choices=["weighted", "header"], help="Routing strategy")
    p_route_set.add_argument("--targets", required=True, help="Targets: name:port:weight,... (weight optional for header)")
    p_route_set.add_argument("--header", default="", help="Header name (required for header strategy)")
    p_route_set.add_argument("--rules", default="", help="Rules: value:target,... (for header strategy)")
    p_route_set.add_argument("--default", default="", help="Default target (for header strategy)")
    p_route_set.add_argument("--dir", default=".", help="Project directory")

    p_route_lock = route_sub.add_parser("lock", help="Lock routing config")
    p_route_lock.add_argument("node", help="Node name")
    p_route_lock.add_argument("--dir", default=".", help="Project directory")

    p_route_unlock = route_sub.add_parser("unlock", help="Unlock routing config")
    p_route_unlock.add_argument("node", help="Node name")
    p_route_unlock.add_argument("--dir", default=".", help="Project directory")

    p_route_clear = route_sub.add_parser("clear", help="Clear routing config")
    p_route_clear.add_argument("node", help="Node name")
    p_route_clear.add_argument("--dir", default=".", help="Project directory")

    # baton deploy
    p_deploy = sub.add_parser("deploy", help="Deploy circuit to a provider")
    p_deploy.add_argument("--provider", default="local", choices=["local", "gcp", "aws"], help="Deployment provider")
    p_deploy.add_argument("--project", default="", help="Cloud project ID (for gcp/aws)")
    p_deploy.add_argument("--region", default="", help="Cloud region")
    p_deploy.add_argument("--namespace", default="", help="Namespace prefix")
    p_deploy.add_argument("--mock", action="store_true", default=True, help="Start with mocks (local only)")
    p_deploy.add_argument("--live", default="", help="Comma-separated nodes to keep live")
    p_deploy.add_argument("--image", default="", help="Container image (or template with {node} placeholder)")
    p_deploy.add_argument("--dir", default=".", help="Project directory")

    # baton teardown
    p_teardown = sub.add_parser("teardown", help="Tear down deployed circuit")
    p_teardown.add_argument("--provider", default="local", choices=["local", "gcp", "aws"], help="Deployment provider")
    p_teardown.add_argument("--project", default="", help="Cloud project ID")
    p_teardown.add_argument("--region", default="", help="Cloud region")
    p_teardown.add_argument("--namespace", default="", help="Namespace prefix")
    p_teardown.add_argument("--dir", default=".", help="Project directory")

    # baton deploy-status
    p_deploy_status = sub.add_parser("deploy-status", help="Check deployment status")
    p_deploy_status.add_argument("--provider", default="local", choices=["local", "gcp", "aws"], help="Deployment provider")
    p_deploy_status.add_argument("--project", default="", help="Cloud project ID")
    p_deploy_status.add_argument("--region", default="", help="Cloud region")
    p_deploy_status.add_argument("--namespace", default="", help="Namespace prefix")
    p_deploy_status.add_argument("--dir", default=".", help="Project directory")

    # baton check
    p_check = sub.add_parser("check", help="Run compatibility check")
    p_check.add_argument("--service", default="", help="Check specific service (default: all)")
    p_check.add_argument("--dir", default=".", help="Project directory")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    try:
        if args.command == "init":
            return _cmd_init(args)
        elif args.command == "node":
            return _cmd_node(args)
        elif args.command == "edge":
            return _cmd_edge(args)
        elif args.command == "contract":
            return _cmd_contract(args)
        elif args.command == "status":
            return _cmd_status(args)
        elif args.command == "service":
            return _cmd_service(args)
        elif args.command == "check":
            return _cmd_check(args)
        elif args.command == "route":
            if args.route_command in ("show",):
                return _cmd_route_show(args)
            elif args.route_command in ("ab", "canary", "set", "lock", "unlock", "clear"):
                return asyncio.run(_cmd_async(args))
            else:
                print("Usage: baton route {show|ab|canary|set|lock|unlock|clear}", file=sys.stderr)
                return 1
        elif args.command in ("up", "down", "slot", "swap", "collapse", "watch", "deploy", "teardown", "deploy-status"):
            return asyncio.run(_cmd_async(args))
        else:
            parser.print_help()
            return 1
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 130


async def _cmd_async(args: argparse.Namespace) -> int:
    """Dispatch async commands."""
    from baton.lifecycle import LifecycleManager

    if args.command == "up":
        return await _cmd_up(args)
    elif args.command == "down":
        return await _cmd_down(args)
    elif args.command == "slot":
        return await _cmd_slot(args)
    elif args.command == "swap":
        return await _cmd_swap(args)
    elif args.command == "collapse":
        return await _cmd_collapse(args)
    elif args.command == "watch":
        return await _cmd_watch(args)
    elif args.command == "route":
        return await _cmd_route_async(args)
    elif args.command == "deploy":
        return await _cmd_deploy(args)
    elif args.command == "teardown":
        return await _cmd_teardown(args)
    elif args.command == "deploy-status":
        return await _cmd_deploy_status(args)
    return 1


async def _cmd_up(args: argparse.Namespace) -> int:
    from baton.collapse import build_mock_server, compute_mock_backends
    from baton.lifecycle import LifecycleManager

    if getattr(args, "services", False):
        from baton.config import load_circuit_from_services
        circuit = load_circuit_from_services(args.dir)
        # Save derived circuit so lifecycle can load it
        save_circuit(circuit, args.dir)

    mgr = LifecycleManager(args.dir)
    state = await mgr.up(mock=args.mock)

    if args.mock:
        circuit = load_circuit(args.dir)
        mock_server = build_mock_server(circuit, live_nodes=set(), project_dir=args.dir)
        backends = compute_mock_backends(circuit, live_nodes=set())

        await mock_server.start()
        for node_name, target in backends.items():
            adapter = mgr.adapters.get(node_name)
            if adapter:
                adapter.set_backend(target)
                if state.adapters.get(node_name):
                    state.adapters[node_name].status = NodeStatus.ACTIVE

    print(f"Circuit '{state.circuit_name}' is up ({len(state.adapters)} nodes)")
    for name, a in state.adapters.items():
        print(f"  {name}: {a.status}")

    # Keep running until interrupted
    print("\nPress Ctrl+C to stop")
    try:
        stop_event = asyncio.Event()
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGINT, stop_event.set)
        loop.add_signal_handler(signal.SIGTERM, stop_event.set)
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        if args.mock and mock_server:
            await mock_server.stop()
        await mgr.down()
        print("Circuit is down")

    return 0


async def _cmd_down(args: argparse.Namespace) -> int:
    # For explicit down, we just clear state
    from baton.state import clear_state
    clear_state(args.dir)
    print("Circuit state cleared")
    return 0


async def _cmd_slot(args: argparse.Namespace) -> int:
    if args.mock:
        print("Use 'baton collapse' to mock nodes in a running circuit")
        return 1
    if not args.command:
        print("Error: command required (or use --mock)", file=sys.stderr)
        return 1

    from baton.lifecycle import LifecycleManager
    mgr = LifecycleManager(args.dir)
    state = await mgr.up(mock=False)
    await mgr.slot(args.node, args.command)
    print(f"Slotted service into '{args.node}'")
    return 0


async def _cmd_swap(args: argparse.Namespace) -> int:
    from baton.lifecycle import LifecycleManager
    mgr = LifecycleManager(args.dir)
    state = await mgr.up(mock=False)
    await mgr.swap(args.node, args.command)
    print(f"Swapped service in '{args.node}'")
    return 0


async def _cmd_collapse(args: argparse.Namespace) -> int:
    from baton.collapse import build_mock_server, compute_mock_backends
    from baton.lifecycle import LifecycleManager

    live = set(args.live.split(",")) if args.live else set()
    live.discard("")

    mgr = LifecycleManager(args.dir)
    state = await mgr.up(mock=True)
    circuit = load_circuit(args.dir)

    # Validate live node names
    node_names = {n.name for n in circuit.nodes}
    unknown = live - node_names
    if unknown:
        print(f"Error: unknown nodes: {', '.join(unknown)}", file=sys.stderr)
        await mgr.down()
        return 1

    # Build mock server for non-live nodes
    mock_server = build_mock_server(circuit, live_nodes=live, project_dir=args.dir)
    backends = compute_mock_backends(circuit, live_nodes=live)

    await mock_server.start()
    for node_name, target in backends.items():
        adapter = mgr.adapters.get(node_name)
        if adapter:
            adapter.set_backend(target)
            if state.adapters.get(node_name):
                state.adapters[node_name].status = NodeStatus.ACTIVE

    # Update collapse level
    if live:
        state.collapse_level = "partial"
    else:
        state.collapse_level = "full_mock"
    state.live_nodes = list(live)

    mocked = node_names - live
    print(f"Circuit '{state.circuit_name}' collapsed ({len(live)} live, {len(mocked)} mocked)")
    for name in sorted(live):
        print(f"  {name}: live")
    for name in sorted(mocked):
        print(f"  {name}: mocked")

    print("\nPress Ctrl+C to stop")
    try:
        stop_event = asyncio.Event()
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGINT, stop_event.set)
        loop.add_signal_handler(signal.SIGTERM, stop_event.set)
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await mock_server.stop()
        await mgr.down()
        print("Circuit is down")

    return 0


async def _cmd_watch(args: argparse.Namespace) -> int:
    from baton.custodian import Custodian
    from baton.lifecycle import LifecycleManager

    mgr = LifecycleManager(args.dir)
    state = await mgr.up(mock=True)

    custodian = Custodian(
        mgr.adapters, state, lifecycle=mgr, poll_interval=args.interval
    )
    task = asyncio.create_task(custodian.run())

    print(f"Custodian watching {len(mgr.adapters)} nodes (interval: {args.interval}s)")
    print("Press Ctrl+C to stop")

    try:
        stop_event = asyncio.Event()
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGINT, stop_event.set)
        loop.add_signal_handler(signal.SIGTERM, stop_event.set)
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        custodian.stop()
        await task
        await mgr.down()
        print(f"Custodian stopped ({len(custodian.events)} events)")

    return 0


def _cmd_route_show(args: argparse.Namespace) -> int:
    """Show routing config for a node (reads from persisted state)."""
    state = load_state(args.dir)
    if not state or args.node not in state.adapters:
        print(f"Node '{args.node}' not found in circuit state", file=sys.stderr)
        return 1

    adapter_state = state.adapters[args.node]
    if adapter_state.routing_config:
        import json
        print(json.dumps(adapter_state.routing_config, indent=2))
    else:
        print(f"{args.node}: single backend (no routing config)")
    return 0


async def _cmd_route_async(args: argparse.Namespace) -> int:
    """Dispatch async route subcommands."""
    from baton.lifecycle import LifecycleManager

    if args.route_command == "ab":
        return await _cmd_route_ab(args)
    elif args.route_command == "canary":
        return await _cmd_route_canary(args)
    elif args.route_command == "set":
        return await _cmd_route_set(args)
    elif args.route_command == "lock":
        return await _cmd_route_lock(args)
    elif args.route_command == "unlock":
        return await _cmd_route_unlock(args)
    elif args.route_command == "clear":
        return await _cmd_route_clear(args)
    return 1


async def _cmd_route_ab(args: argparse.Namespace) -> int:
    from baton.lifecycle import LifecycleManager

    parts = args.split.split("/")
    if len(parts) != 2:
        print("Error: --split must be in A/B format (e.g. 80/20)", file=sys.stderr)
        return 1
    try:
        pct_a, pct_b = int(parts[0]), int(parts[1])
    except ValueError:
        print("Error: --split values must be integers", file=sys.stderr)
        return 1

    mgr = LifecycleManager(args.dir)
    await mgr.up(mock=False)

    # Reuse existing service as instance A, start command as instance B
    await mgr.route_ab(
        args.node,
        args.command,
        split=(pct_a, pct_b),
    )
    print(f"A/B routing configured for '{args.node}' ({pct_a}/{pct_b})")
    return 0


async def _cmd_route_canary(args: argparse.Namespace) -> int:
    from baton.lifecycle import LifecycleManager

    mgr = LifecycleManager(args.dir)
    await mgr.up(mock=False)

    # Reuse existing service as stable, start command as canary
    await mgr.route_ab(
        args.node,
        args.command,
        split=(100 - args.pct, args.pct),
    )
    print(f"Canary routing configured for '{args.node}' ({args.pct}% canary)")
    return 0


async def _cmd_route_set(args: argparse.Namespace) -> int:
    from baton.lifecycle import LifecycleManager
    from baton.schemas import RoutingConfig, RoutingRule, RoutingStrategy, RoutingTarget

    mgr = LifecycleManager(args.dir)
    await mgr.up(mock=False)

    # Parse targets: name:port:weight or name:port
    targets = []
    for part in args.targets.split(","):
        fields = part.strip().split(":")
        if len(fields) == 3:
            targets.append(RoutingTarget(name=fields[0], port=int(fields[1]), weight=int(fields[2])))
        elif len(fields) == 2:
            targets.append(RoutingTarget(name=fields[0], port=int(fields[1])))
        else:
            print(f"Error: invalid target '{part}'", file=sys.stderr)
            return 1

    rules = []
    if args.rules:
        for part in args.rules.split(","):
            fields = part.strip().split(":")
            if len(fields) != 2:
                print(f"Error: invalid rule '{part}'", file=sys.stderr)
                return 1
            rules.append(RoutingRule(header=args.header, value=fields[0], target=fields[1]))

    config = RoutingConfig(
        strategy=RoutingStrategy(args.strategy),
        targets=targets,
        rules=rules,
        default_target=getattr(args, "default", ""),
    )
    mgr.set_routing(args.node, config)
    print(f"Routing config set for '{args.node}' (strategy: {args.strategy})")
    return 0


async def _cmd_route_lock(args: argparse.Namespace) -> int:
    from baton.lifecycle import LifecycleManager

    mgr = LifecycleManager(args.dir)
    await mgr.up(mock=False)
    mgr.lock_routing(args.node)
    print(f"Routing config locked for '{args.node}'")
    return 0


async def _cmd_route_unlock(args: argparse.Namespace) -> int:
    from baton.lifecycle import LifecycleManager

    mgr = LifecycleManager(args.dir)
    await mgr.up(mock=False)
    mgr.unlock_routing(args.node)
    print(f"Routing config unlocked for '{args.node}'")
    return 0


async def _cmd_route_clear(args: argparse.Namespace) -> int:
    from baton.lifecycle import LifecycleManager

    mgr = LifecycleManager(args.dir)
    await mgr.up(mock=False)
    adapter = mgr.adapters.get(args.node)
    if adapter is None:
        print(f"Node '{args.node}' not found", file=sys.stderr)
        return 1
    adapter.clear_routing()
    if mgr.state and args.node in mgr.state.adapters:
        mgr.state.adapters[args.node].routing_config = None
    print(f"Routing config cleared for '{args.node}'")
    return 0


def _build_deploy_target(args: argparse.Namespace) -> "DeploymentTarget":
    from baton.schemas import DeploymentTarget

    config: dict[str, str] = {"project_dir": str(Path(args.dir).resolve())}
    if hasattr(args, "project") and args.project:
        config["project"] = args.project
    if hasattr(args, "mock") and args.mock:
        config["mock"] = "true"
    if hasattr(args, "live") and args.live:
        config["live"] = args.live
    if hasattr(args, "image") and args.image:
        config["image_template"] = args.image

    return DeploymentTarget(
        provider=args.provider,
        region=getattr(args, "region", "") or "",
        namespace=getattr(args, "namespace", "") or "",
        config=config,
    )


async def _cmd_deploy(args: argparse.Namespace) -> int:
    from baton.providers import create_provider

    circuit = load_circuit(args.dir)
    target = _build_deploy_target(args)
    provider = create_provider(args.provider)

    state = await provider.deploy(circuit, target)

    print(f"Deployed '{circuit.name}' via {args.provider} ({len(state.adapters)} nodes)")
    for name, a in state.adapters.items():
        print(f"  {name}: {a.status}")

    if args.provider == "local":
        print("\nPress Ctrl+C to stop")
        try:
            stop_event = asyncio.Event()
            loop = asyncio.get_event_loop()
            loop.add_signal_handler(signal.SIGINT, stop_event.set)
            loop.add_signal_handler(signal.SIGTERM, stop_event.set)
            await stop_event.wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await provider.teardown(circuit, target)
            print("Deployment torn down")

    return 0


async def _cmd_teardown(args: argparse.Namespace) -> int:
    from baton.providers import create_provider

    circuit = load_circuit(args.dir)
    target = _build_deploy_target(args)
    provider = create_provider(args.provider)

    await provider.teardown(circuit, target)
    print(f"Torn down '{circuit.name}' via {args.provider}")
    return 0


async def _cmd_deploy_status(args: argparse.Namespace) -> int:
    from baton.providers import create_provider

    circuit = load_circuit(args.dir)
    target = _build_deploy_target(args)
    provider = create_provider(args.provider)

    state = await provider.status(circuit, target)

    print(f"Deployment: {circuit.name} via {args.provider}")
    print(f"  Collapse: {state.collapse_level}")
    print(f"  Live:     {', '.join(state.live_nodes) or 'none'}")
    for name, a in state.adapters.items():
        svc = a.service.command if a.service.command else "—"
        print(f"  {name}: {a.status} ({svc})")

    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    project_dir = Path(args.dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    config_path = project_dir / CONFIG_FILENAME
    if config_path.exists():
        print(f"{CONFIG_FILENAME} already exists in {project_dir}")
        return 1
    circuit = CircuitSpec(name=args.name)
    save_circuit(circuit, project_dir)
    ensure_baton_dir(project_dir)
    print(f"Initialized circuit '{args.name}' in {project_dir}")
    return 0


def _cmd_node(args: argparse.Namespace) -> int:
    if args.node_command == "add":
        circuit = load_circuit(args.dir)
        circuit = add_node(circuit, args.name, port=args.port, proxy_mode=args.mode)
        save_circuit(circuit, args.dir)
        node = circuit.node_by_name(args.name)
        print(f"Added node '{args.name}' on port {node.port}")
        return 0
    elif args.node_command == "rm":
        circuit = load_circuit(args.dir)
        circuit = remove_node(circuit, args.name)
        save_circuit(circuit, args.dir)
        print(f"Removed node '{args.name}'")
        return 0
    else:
        print("Usage: baton node {add|rm}", file=sys.stderr)
        return 1


def _cmd_edge(args: argparse.Namespace) -> int:
    if args.edge_command == "add":
        circuit = load_circuit(args.dir)
        circuit = add_edge(circuit, args.source, args.target)
        save_circuit(circuit, args.dir)
        print(f"Added edge {args.source} -> {args.target}")
        return 0
    elif args.edge_command == "rm":
        circuit = load_circuit(args.dir)
        circuit = remove_edge(circuit, args.source, args.target)
        save_circuit(circuit, args.dir)
        print(f"Removed edge {args.source} -> {args.target}")
        return 0
    else:
        print("Usage: baton edge {add|rm}", file=sys.stderr)
        return 1


def _cmd_contract(args: argparse.Namespace) -> int:
    if args.contract_command == "set":
        circuit = load_circuit(args.dir)
        circuit = set_contract(circuit, args.node, args.spec)
        save_circuit(circuit, args.dir)
        print(f"Set contract for '{args.node}' to {args.spec}")
        return 0
    else:
        print("Usage: baton contract {set}", file=sys.stderr)
        return 1


def _cmd_service(args: argparse.Namespace) -> int:
    if args.service_command == "register":
        from baton.manifest import load_manifest
        from baton.config import add_service_path

        # Validate the manifest
        load_manifest(args.path)
        add_service_path(args.dir, args.path)
        print(f"Registered service from '{args.path}'")
        return 0

    elif args.service_command == "list":
        from baton.config import _discover_service_dirs
        from baton.manifest import load_manifest

        dirs = _discover_service_dirs(Path(args.dir))
        if not dirs:
            print("No services registered")
            return 0

        print(f"  {'Name':<20} {'Version':<12} {'Role':<10} {'Dependencies'}")
        print(f"  {'─'*20} {'─'*12} {'─'*10} {'─'*30}")
        for d in dirs:
            m = load_manifest(d)
            deps = ", ".join(dep.name for dep in m.dependencies) or "—"
            print(f"  {m.name:<20} {m.version:<12} {m.role:<10} {deps}")
        return 0

    elif args.service_command == "derive":
        from baton.config import load_circuit_from_services, save_circuit

        circuit = load_circuit_from_services(args.dir)
        print(f"Derived circuit '{circuit.name}' ({len(circuit.nodes)} nodes, {len(circuit.edges)} edges)")
        for n in circuit.nodes:
            role_tag = f" [{n.role}]" if n.role != "service" else ""
            print(f"  {n.name}{role_tag} :{n.port}")
        for e in circuit.edges:
            print(f"  {e.source} -> {e.target}")

        if args.save:
            save_circuit(circuit, args.dir)
            print(f"\nSaved to {CONFIG_FILENAME}")
        return 0

    else:
        print("Usage: baton service {register|list|derive}", file=sys.stderr)
        return 1


def _cmd_check(args: argparse.Namespace) -> int:
    from baton.compat import check_compatibility
    from baton.config import _discover_service_dirs
    from baton.manifest import load_manifest

    dirs = _discover_service_dirs(Path(args.dir))
    if not dirs:
        print("No services registered")
        return 1

    manifests = [load_manifest(d) for d in dirs]
    by_name = {m.name: m for m in manifests}

    if args.service:
        if args.service not in by_name:
            print(f"Service '{args.service}' not found", file=sys.stderr)
            return 1
        providers = [by_name[args.service]]
    else:
        providers = manifests

    all_compatible = True
    for provider in providers:
        report = check_compatibility(provider, manifests, base_dir=args.dir)
        if report.issues:
            all_compatible = False
            for issue in report.issues:
                print(f"  [{issue.severity.upper()}] {issue.consumer} -> {issue.provider}: "
                      f"{issue.method} {issue.path}")
                print(f"         {issue.detail}")
        else:
            print(f"  {provider.name}: compatible")

    return 0 if all_compatible else 1


def _cmd_status(args: argparse.Namespace) -> int:
    circuit = load_circuit(args.dir)
    state = load_state(args.dir)

    print(f"Circuit: {circuit.name} (v{circuit.version})")
    print(f"Nodes:   {len(circuit.nodes)}")
    print(f"Edges:   {len(circuit.edges)}")

    if state:
        print(f"State:   {state.collapse_level}")
        if state.live_nodes:
            print(f"Live:    {', '.join(state.live_nodes)}")

    if circuit.nodes:
        print()
        header = f"  {'Name':<20} {'Port':<8} {'Mode':<6}"
        if state:
            header += f" {'Status':<12} {'Health'}"
        else:
            header += f" {'Contract'}"
        print(header)
        print(f"  {'─'*20} {'─'*8} {'─'*6} {'─'*30}")
        for n in circuit.nodes:
            line = f"  {n.name:<20} {n.port:<8} {n.proxy_mode:<6}"
            if state and n.name in state.adapters:
                a = state.adapters[n.name]
                line += f" {a.status:<12} {a.last_health_verdict}"
            else:
                contract = n.contract or "—"
                line += f" {contract}"
            print(line)

    if circuit.edges:
        print()
        print("  Edges:")
        for e in circuit.edges:
            label = f" ({e.label})" if e.label else ""
            print(f"    {e.source} -> {e.target}{label}")

    return 0
