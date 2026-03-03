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
        elif args.command in ("up", "down", "slot", "swap", "collapse", "watch"):
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
    return 1


async def _cmd_up(args: argparse.Namespace) -> int:
    from baton.collapse import build_mock_server, compute_mock_backends
    from baton.lifecycle import LifecycleManager

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
    live = set(args.live.split(",")) if args.live else set()
    live.discard("")
    print(f"Collapse requested. Live nodes: {live or 'none'}")
    print("(Full collapse requires a running circuit — use 'baton up --mock' to start)")
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
