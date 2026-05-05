"""Baton CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

from baton.circuit import add_edge, add_node, remove_edge, remove_node, set_contract
from baton.config import CONFIG_FILENAME, load_circuit, load_circuit_config, save_circuit, save_circuit_config, _serialize_circuit_config
from baton.schemas import CircuitSpec, NodeStatus
from baton.state import ensure_baton_dir, load_circuit_spec, load_state


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
    p_init.add_argument("--constrain-dir", default="", help="Generate from Constrain component_map.yaml")

    # baton node
    p_node = sub.add_parser("node", help="Manage nodes")
    node_sub = p_node.add_subparsers(dest="node_command")

    p_node_add = node_sub.add_parser("add", help="Add a node")
    p_node_add.add_argument("name", help="Node name")
    p_node_add.add_argument("--port", type=int, default=0, help="Port number")
    p_node_add.add_argument("--mode", default="http", choices=["http", "tcp", "grpc", "protobuf", "soap"], help="Proxy mode")
    p_node_add.add_argument("--role", default="service", choices=["service", "ingress", "egress"], help="Node role")
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
    p_slot.add_argument("service_cmd", nargs="?", help="Command to run (omit for --mock)")
    p_slot.add_argument("--mock", action="store_true", help="Slot a mock instead")
    p_slot.add_argument("--skip-validate", action="store_true", help="Skip runtime interface validation")
    p_slot.add_argument("--force", action="store_true", help="Force slot even with low Arbiter trust")
    p_slot.add_argument("--dir", default=".", help="Project directory")

    # baton swap
    p_swap = sub.add_parser("swap", help="Hot-swap a service in a node")
    p_swap.add_argument("node", help="Node name")
    p_swap.add_argument("service_cmd", help="Command to run")
    p_swap.add_argument("--skip-validate", action="store_true", help="Skip runtime interface validation")
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
    p_route_canary.add_argument("--promote", action="store_true", help="Enable auto-promotion/rollback")
    p_route_canary.add_argument("--error-threshold", type=float, default=5.0, help="Max canary error rate %% (default: 5.0)")
    p_route_canary.add_argument("--latency-threshold", type=float, default=500.0, help="Max canary p99 ms (default: 500)")
    p_route_canary.add_argument("--eval-interval", type=float, default=30.0, help="Seconds between evaluations (default: 30)")
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
    p_deploy.add_argument("--build", action="store_true", help="Build images before deploying")
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

    # baton image
    p_image = sub.add_parser("image", help="Build and manage container images")
    image_sub = p_image.add_subparsers(dest="image_command")

    p_image_build = image_sub.add_parser("build", help="Build a container image")
    p_image_build.add_argument("--node", default="", help="Node name")
    p_image_build.add_argument("--tag", default="", help="Image tag")
    p_image_build.add_argument("--path", default="", help="Service directory path")
    p_image_build.add_argument("--dir", default=".", help="Project directory")

    p_image_push = image_sub.add_parser("push", help="Push a container image")
    p_image_push.add_argument("--node", default="", help="Node name (looks up tag from images.json)")
    p_image_push.add_argument("--tag", default="", help="Image tag to push")
    p_image_push.add_argument("--dir", default=".", help="Project directory")

    p_image_list = image_sub.add_parser("list", help="List built images")
    p_image_list.add_argument("--dir", default=".", help="Project directory")

    # baton dashboard
    p_dashboard = sub.add_parser(
        "dashboard",
        help="Show aggregated circuit metrics (development aid — use OTLP export for production observability)",
        description="Show aggregated circuit metrics (development aid — use OTLP export for production observability)",
    )
    p_dashboard.add_argument("--json", action="store_true", help="Output as JSON")
    p_dashboard.add_argument("--serve", action="store_true", help="Start interactive dashboard server")
    p_dashboard.add_argument("--host", default="127.0.0.1", help="Dashboard server host (default: 127.0.0.1)")
    p_dashboard.add_argument("--port", type=int, default=9900, help="Dashboard server port (default: 9900)")
    p_dashboard.add_argument("--dir", default=".", help="Project directory")

    # baton signals
    p_signals = sub.add_parser("signals", help="Show request signals")
    p_signals.add_argument("--node", default="", help="Filter by node name")
    p_signals.add_argument("--path", default="", help="Filter by path pattern")
    p_signals.add_argument("--last", type=int, default=20, help="Show last N signals")
    p_signals.add_argument("--stats", action="store_true", help="Show per-path statistics")
    p_signals.add_argument("--dir", default=".", help="Project directory")

    # baton metrics
    p_metrics = sub.add_parser("metrics", help="Show persistent metrics")
    p_metrics.add_argument("--node", default="", help="Filter by node name")
    p_metrics.add_argument("--last", type=int, default=1, help="Show last N snapshots")
    p_metrics.add_argument("--prometheus", action="store_true", help="Prometheus text format")
    p_metrics.add_argument("--dir", default=".", help="Project directory")

    # baton check
    p_check = sub.add_parser("check", help="Run compatibility check")
    p_check.add_argument("--service", default="", help="Check specific service (default: all)")
    p_check.add_argument("--dir", default=".", help="Project directory")

    # baton apply
    p_apply = sub.add_parser("apply", help="Apply declarative config (converge desired vs running)")
    p_apply.add_argument("--dir", default=".", help="Project directory")
    p_apply.add_argument("--dry-run", action="store_true", help="Show what would change without applying")

    # baton export
    p_export = sub.add_parser("export", help="Export running state as YAML config")
    p_export.add_argument("--dir", default=".", help="Project directory")
    p_export.add_argument("--output", default="", help="Output file (default: stdout)")

    # baton federation
    p_fed = sub.add_parser("federation", help="Multi-cluster federation")
    fed_sub = p_fed.add_subparsers(dest="federation_command")

    p_fed_status = fed_sub.add_parser("status", help="Show federation status")
    p_fed_status.add_argument("--dir", default=".", help="Project directory")
    p_fed_status.add_argument("--json", action="store_true", dest="json_output", help="JSON output")

    p_fed_peers = fed_sub.add_parser("peers", help="Show peer cluster states")
    p_fed_peers.add_argument("--dir", default=".", help="Project directory")
    p_fed_peers.add_argument("--json", action="store_true", dest="json_output", help="JSON output")

    # baton certs
    p_certs = sub.add_parser("certs", help="Certificate management")
    certs_sub = p_certs.add_subparsers(dest="certs_command")

    p_certs_status = certs_sub.add_parser("status", help="Show certificate status")
    p_certs_status.add_argument("--dir", default=".", help="Project directory")
    p_certs_status.add_argument("--json", action="store_true", dest="json_output", help="JSON output")

    p_certs_rotate = certs_sub.add_parser("rotate", help="Force certificate rotation")
    p_certs_rotate.add_argument("--dir", default=".", help="Project directory")

    # baton dora
    p_dora = sub.add_parser("dora", help="Show DORA metrics (deployment frequency, lead time, CFR, MTTR)")
    p_dora.add_argument("--window", type=int, default=168, help="Time window in hours (default: 168 = 1 week)")
    p_dora.add_argument("--json", action="store_true", dest="json_output", help="Output as JSON")
    p_dora.add_argument("--dir", default=".", help="Project directory")

    # baton logs
    p_logs = sub.add_parser("logs", help="Show service logs")
    p_logs.add_argument("--node", default="", help="Filter by node")
    p_logs.add_argument("--level", default="", help="Minimum severity level (debug/info/warning/error/critical)")
    p_logs.add_argument("--last", type=int, default=50, help="Number of entries (default: 50)")
    p_logs.add_argument("--dir", default=".", help="Project directory")

    # baton taint
    p_taint = sub.add_parser("taint", help="Taint analysis / canary data boundary verification")
    taint_sub = p_taint.add_subparsers(dest="taint_command")

    p_taint_seed = taint_sub.add_parser("seed", help="Seed canary data into services")
    p_taint_seed.add_argument("--node", default="", help="Seed only this node (default: all)")
    p_taint_seed.add_argument("--dir", default=".", help="Project directory")

    p_taint_status = taint_sub.add_parser("status", help="Show active canary data and violations")
    p_taint_status.add_argument("--dir", default=".", help="Project directory")

    p_taint_violations = taint_sub.add_parser("violations", help="List all taint violations")
    p_taint_violations.add_argument("--dir", default=".", help="Project directory")

    p_taint_clear = taint_sub.add_parser("clear", help="Remove all canary data")
    p_taint_clear.add_argument("--dir", default=".", help="Project directory")

    # baton trust
    p_trust = sub.add_parser("trust", help="Show Arbiter trust score for a node")
    p_trust.add_argument("node", help="Node name")
    p_trust.add_argument("--dir", default=".", help="Project directory")

    # baton audit
    p_audit = sub.add_parser("audit", help="Show recent audit events for a node")
    p_audit.add_argument("node", help="Node name")
    p_audit.add_argument("--last", type=int, default=20, help="Number of entries")
    p_audit.add_argument("--dir", default=".", help="Project directory")

    # baton arbiter
    p_arbiter = sub.add_parser("arbiter", help="Arbiter integration")
    arbiter_sub = p_arbiter.add_subparsers(dest="arbiter_command")
    p_arb_status = arbiter_sub.add_parser("status", help="Show Arbiter connectivity")
    p_arb_status.add_argument("--dir", default=".", help="Project directory")

    # baton test
    p_test = sub.add_parser("test", help="Run circuit tests")
    p_test.add_argument("--canary", action="store_true", help="Run canary injection test")
    p_test.add_argument("--tiers", default="", help="Comma-separated tiers (e.g. PII,FINANCIAL)")
    p_test.add_argument("--duration", default="60", help="Soak duration (e.g. 60s, 5m, 1h)")
    p_test.add_argument("--run-id", default="", help="Run identifier")
    p_test.add_argument("--ledger-mocks", action="store_true", help="Use Ledger for mock data")
    p_test.add_argument("--dir", default=".", help="Project directory")

    # baton sync-ledger
    p_sync_ledger = sub.add_parser("sync-ledger", help="Sync egress nodes from Ledger")
    p_sync_ledger.add_argument("--dir", default=".", help="Project directory")

    # baton migrate-config
    p_migrate = sub.add_parser("migrate-config", help="Migrate baton.yaml from v1 to v2 schema")
    p_migrate.add_argument("--config", default="baton.yaml", help="Path to baton.yaml (default: baton.yaml)")
    p_migrate.add_argument("--output", default="", help="Output path (default: overwrite input)")
    p_migrate.add_argument("--dry-run", action="store_true", help="Print migrated config without writing")

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
        elif args.command == "metrics":
            return _cmd_metrics(args)
        elif args.command == "signals":
            return _cmd_signals(args)
        elif args.command == "route":
            if args.route_command in ("show",):
                return _cmd_route_show(args)
            elif args.route_command in ("ab", "canary", "set", "lock", "unlock", "clear"):
                return asyncio.run(_cmd_async(args))
            else:
                print("Usage: baton route {show|ab|canary|set|lock|unlock|clear}", file=sys.stderr)
                return 1
        elif args.command == "image":
            if args.image_command == "list":
                return _cmd_image_list(args)
            elif args.image_command in ("build", "push"):
                return asyncio.run(_cmd_async(args))
            else:
                print("Usage: baton image {build|push|list}", file=sys.stderr)
                return 1
        elif args.command == "apply":
            if args.dry_run:
                return _cmd_apply_dry_run(args)
            return asyncio.run(_cmd_async(args))
        elif args.command == "export":
            return _cmd_export(args)
        elif args.command == "federation":
            return _cmd_federation(args)
        elif args.command == "certs":
            return _cmd_certs(args)
        elif args.command == "dora":
            return _cmd_dora(args)
        elif args.command == "logs":
            return _cmd_logs(args)
        elif args.command == "taint":
            return _cmd_taint(args)
        elif args.command == "trust":
            return asyncio.run(_cmd_trust(args))
        elif args.command == "audit":
            return _cmd_audit(args)
        elif args.command == "arbiter":
            return asyncio.run(_cmd_arbiter(args))
        elif args.command == "test":
            return asyncio.run(_cmd_test(args))
        elif args.command == "sync-ledger":
            return asyncio.run(_cmd_sync_ledger(args))
        elif args.command == "migrate-config":
            return _cmd_migrate_config(args)
        elif args.command in ("up", "down", "slot", "swap", "collapse", "watch", "deploy", "teardown", "deploy-status", "dashboard"):
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
    elif args.command == "dashboard":
        return await _cmd_dashboard(args)
    elif args.command == "image":
        return await _cmd_image_async(args)
    elif args.command == "apply":
        return await _cmd_apply(args)
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

    # Show entry points for ingress nodes
    circuit_info = load_circuit(args.dir)
    if circuit_info.ingress_nodes:
        print("\nEntry points:")
        for n in circuit_info.ingress_nodes:
            print(f"  {n.name}: {n.host}:{n.port}")

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
    import os

    from baton.state import clear_state, load_state

    state = load_state(args.dir)
    if state and state.owner_pid:
        # Signal the owning process (baton up / baton apply) to shut down gracefully.
        # Its finally block will drain adapters, stop control servers, and kill processes.
        pid = state.owner_pid
        try:
            os.kill(pid, signal.SIGTERM)
            # Wait briefly for the owner to clean up
            for _ in range(20):
                await asyncio.sleep(0.25)
                try:
                    os.kill(pid, 0)  # check if still alive
                except OSError:
                    break  # process exited
            else:
                # Still alive after 5s -- force kill
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            print(f"Stopped circuit owner process (pid {pid})")
        except OSError:
            # Process already gone -- fall through to clear stale state
            pass

    clear_state(args.dir)
    print("Circuit state cleared")
    return 0


async def _cmd_slot(args: argparse.Namespace) -> int:
    if args.mock:
        print("Use 'baton collapse' to mock nodes in a running circuit")
        return 1
    if not args.service_cmd:
        print("Error: command required (or use --mock)", file=sys.stderr)
        return 1

    from baton.collapse import build_mock_server, compute_mock_backends
    from baton.lifecycle import LifecycleManager

    mgr = LifecycleManager(args.dir)
    state = await mgr.up(mock=False)

    # Wire mocks for all nodes except the one being slotted
    circuit = load_circuit(args.dir)
    live_nodes: set[str] = {args.node}
    mock_server = build_mock_server(circuit, live_nodes=live_nodes, project_dir=args.dir)
    backends = compute_mock_backends(circuit, live_nodes=live_nodes)
    await mock_server.start()
    for node_name, target in backends.items():
        adapter = mgr.adapters.get(node_name)
        if adapter:
            adapter.set_backend(target)
            if state.adapters.get(node_name):
                state.adapters[node_name].status = NodeStatus.ACTIVE

    skip = getattr(args, "skip_validate", False)
    force = getattr(args, "force", False)
    await mgr.slot(args.node, args.service_cmd, validate=not skip, force=force)
    print(f"Slotted service into '{args.node}'")

    # Block until interrupted so adapters stay alive
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    print("Press Ctrl+C to stop")
    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        await mock_server.stop()
        await mgr.down()
        print("Circuit is down")
    return 0


async def _cmd_swap(args: argparse.Namespace) -> int:
    from baton.lifecycle import LifecycleManager
    mgr = LifecycleManager(args.dir)
    state = await mgr.up(mock=False)
    skip = getattr(args, "skip_validate", False)
    await mgr.swap(args.node, args.service_cmd, validate=not skip)
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

    # Egress nodes cannot be live — strip silently
    egress_names = {n.name for n in circuit.egress_nodes}
    stripped = live & egress_names
    if stripped:
        print(f"Note: egress nodes always mocked: {', '.join(stripped)}")
    live -= egress_names

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

    if getattr(args, "promote", False):
        controller = await mgr.start_canary(
            args.node,
            args.command,
            canary_pct=args.pct,
            error_threshold=args.error_threshold,
            latency_threshold=args.latency_threshold,
            eval_interval=args.eval_interval,
        )
        print(f"Canary controller started for '{args.node}' ({args.pct}% initial)")
        print("Evaluating canary health and auto-promoting...")

        task = asyncio.create_task(controller.run())
        try:
            await task
        except asyncio.CancelledError:
            controller.stop()

        print(f"Canary result: {controller.outcome}")
        return 0
    else:
        # Static canary split without auto-promotion
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
    if hasattr(args, "build") and args.build:
        config["build"] = "true"

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


def _cmd_signals(args: argparse.Namespace) -> int:
    import json as json_mod
    from baton.signals import SignalAggregator

    node = args.node or None
    records = SignalAggregator.load_history(
        args.dir, node=node, last_n=args.last
    )
    if not records:
        print("No signal data found.", file=sys.stderr)
        return 1

    if args.path:
        records = [r for r in records if args.path in r.get("path", "")]

    if getattr(args, "stats", False):
        # Compute per-path statistics from loaded records
        from collections import defaultdict
        path_data: dict[str, dict] = {}
        for r in records:
            p = r.get("path", "")
            if p not in path_data:
                path_data[p] = {"count": 0, "errors": 0, "latencies": []}
            path_data[p]["count"] += 1
            path_data[p]["latencies"].append(r.get("latency_ms", 0))
            if r.get("status_code", 0) >= 400:
                path_data[p]["errors"] += 1

        print(f"{'Path':<30} {'Count':>6} {'Avg(ms)':>8} {'Err%':>6}")
        print(f"{'─'*30} {'─'*6} {'─'*8} {'─'*6}")
        for p, d in sorted(path_data.items()):
            avg = sum(d["latencies"]) / len(d["latencies"]) if d["latencies"] else 0
            err = d["errors"] / d["count"] * 100 if d["count"] else 0
            print(f"{p:<30} {d['count']:>6} {avg:>7.1f} {err:>5.1f}%")
    else:
        for r in records:
            ts = r.get("timestamp", "")[:19]
            method = r.get("method", "")
            path = r.get("path", "")
            status = r.get("status_code", 0)
            latency = r.get("latency_ms", 0)
            node_name = r.get("node_name", "")
            print(f"{ts}  {node_name:<12} {method:<6} {path:<20} {status:>3}  {latency:.0f}ms")
    return 0


def _cmd_metrics(args: argparse.Namespace) -> int:
    import json as json_mod
    from baton.telemetry import TelemetryCollector

    node = args.node or None
    records = TelemetryCollector.load_history(
        args.dir, node=node, last_n=args.last
    )
    if not records:
        print("No metrics data found. Run 'baton up' with telemetry first.", file=sys.stderr)
        return 1

    if getattr(args, "prometheus", False):
        from baton.dashboard import DashboardSnapshot, NodeSnapshot
        # Reconstruct snapshot from latest record
        latest = records[-1]
        nodes_data = latest.get("nodes", {})
        if node and "node" in latest:
            nodes_data = {node: latest["node"]}
        snapshot = DashboardSnapshot(
            timestamp=latest.get("timestamp", ""),
            nodes={
                name: NodeSnapshot(name=name, **{
                    k: v for k, v in data.items() if k != "name"
                })
                for name, data in nodes_data.items()
            },
        )
        print(TelemetryCollector.format_prometheus(snapshot), end="")
    else:
        print(json_mod.dumps(records, indent=2))
    return 0


def _cmd_dora(args: argparse.Namespace) -> int:
    import json as json_mod
    from baton.dora import compute_dora, format_dora

    metrics = compute_dora(args.dir, window_hours=args.window)

    if getattr(args, "json_output", False):
        print(json_mod.dumps(metrics.to_dict(), indent=2))
    else:
        print(format_dora(metrics))
    return 0


def _cmd_logs(args: argparse.Namespace) -> int:
    from baton.service_log import ServiceLogCollector

    records = ServiceLogCollector.load_history(
        args.dir,
        node=args.node or None,
        severity=args.level or None,
        last_n=args.last,
    )
    if not records:
        print("No service logs found")
        return 0

    for r in records:
        sev = r.get("severity", "info").upper()
        node = r.get("node_name", "?")
        ts = r.get("timestamp", "")[:19]  # Trim to seconds
        stream = r.get("stream", "")
        msg = r.get("message", "")
        print(f"[{ts}] [{sev:<8}] [{node}:{stream}] {msg}")

    return 0


async def _cmd_dashboard(args: argparse.Namespace) -> int:
    import json as json_mod
    from baton.dashboard import collect, format_table
    from baton.lifecycle import LifecycleManager

    circuit = load_circuit(args.dir)

    if getattr(args, "serve", False):
        from baton.dashboard_server import DashboardServer
        from baton.signals import SignalAggregator

        mgr = LifecycleManager(args.dir)
        state = await mgr.up(mock=True)

        sig_agg = SignalAggregator(mgr.adapters, args.dir, flush_interval=2.0)
        sig_task = asyncio.create_task(sig_agg.run())

        # Resolve static dir: docs/ui/ relative to package or project
        static_dir = Path(__file__).resolve().parent.parent.parent / "docs" / "ui"
        if not static_dir.exists():
            static_dir = None

        server = DashboardServer(
            adapters=mgr.adapters,
            state=state,
            circuit=circuit,
            signal_aggregator=sig_agg,
            static_dir=static_dir,
            host=args.host,
            port=args.port,
        )
        await server.start()
        print(f"Dashboard server running on http://{args.host}:{args.port}")
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
            sig_agg.stop()
            await sig_task
            await server.stop()
            await mgr.down()
            print("Dashboard stopped")
        return 0

    state = load_state(args.dir)
    if not state:
        print("No circuit state found. Run 'baton up' first.", file=sys.stderr)
        return 1

    mgr = LifecycleManager(args.dir)
    await mgr.up(mock=True)
    try:
        snapshot = await collect(mgr.adapters, state, circuit)
        if getattr(args, "json", False):
            import dataclasses
            print(json_mod.dumps(dataclasses.asdict(snapshot), indent=2))
        else:
            print(format_table(snapshot))
    finally:
        await mgr.down()
    return 0


def _cmd_image_list(args: argparse.Namespace) -> int:
    from baton.image import ImageBuilder
    builder = ImageBuilder(args.dir)
    images = builder.list_images()
    if not images:
        print("No images built yet.")
        return 0
    print(f"  {'Node':<20} {'Tag':<40} {'Built At':<25}")
    print(f"  {'─'*20} {'─'*40} {'─'*25}")
    for img in images:
        print(f"  {img.node_name:<20} {img.tag:<40} {img.built_at[:19]:<25}")
    return 0


async def _cmd_image_async(args: argparse.Namespace) -> int:
    from baton.image import ImageBuilder

    if args.image_command == "build":
        return await _cmd_image_build(args)
    elif args.image_command == "push":
        return await _cmd_image_push(args)
    return 1


async def _cmd_image_build(args: argparse.Namespace) -> int:
    from baton.image import ImageBuilder

    if not args.node:
        print("Error: --node is required", file=sys.stderr)
        return 1

    service_dir = args.path
    if not service_dir:
        # Try to find service_dir from circuit metadata
        try:
            circuit = load_circuit(args.dir)
            node = circuit.node_by_name(args.node)
            if node and node.metadata.get("service_dir"):
                service_dir = node.metadata["service_dir"]
        except Exception:
            pass

    if not service_dir:
        print("Error: --path is required (or set service_dir in node metadata)", file=sys.stderr)
        return 1

    builder = ImageBuilder(args.dir)
    info = await builder.build(args.node, service_dir, tag=args.tag)
    print(f"Built image: {info.tag}")
    if info.digest:
        print(f"  Digest: {info.digest}")
    return 0


async def _cmd_image_push(args: argparse.Namespace) -> int:
    from baton.image import ImageBuilder

    tag = args.tag
    if not tag and args.node:
        builder = ImageBuilder(args.dir)
        images = builder.list_images()
        for img in images:
            if img.node_name == args.node:
                tag = img.tag
                break

    if not tag:
        print("Error: --tag or --node required", file=sys.stderr)
        return 1

    builder = ImageBuilder(args.dir)
    pushed = await builder.push(tag)
    print(f"Pushed: {pushed}")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    project_dir = Path(args.dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    if args.constrain_dir:
        from baton.constrain import generate_and_save
        output = generate_and_save(
            args.constrain_dir, args.dir,
            circuit_name=args.name,
        )
        print(f"Generated {output} from Constrain component_map")
        return 0
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
        circuit = add_node(circuit, args.name, port=args.port, proxy_mode=args.mode, role=args.role)
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
        header = f"  {'Name':<20} {'Role':<10} {'Port':<8} {'Mode':<6}"
        if state:
            header += f" {'Status':<12} {'Health'}"
        else:
            header += f" {'Contract'}"
        print(header)
        print(f"  {'─'*20} {'─'*10} {'─'*8} {'─'*6} {'─'*30}")
        for n in circuit.nodes:
            role = f"[{n.role}]" if n.role != "service" else ""
            line = f"  {n.name:<20} {role:<10} {n.port:<8} {n.proxy_mode:<6}"
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


# -- Apply / Export --


def _cmd_apply_dry_run(args: argparse.Namespace) -> int:
    """Show what baton apply would do without actually doing it."""
    from baton.lifecycle import _compute_convergence_actions

    project_dir = Path(args.dir)
    config = load_circuit_config(project_dir)
    desired = config.to_circuit_spec()
    current_state = load_state(project_dir)

    # Load the previously-applied circuit spec (persisted in .baton/)
    current_circuit = load_circuit_spec(project_dir)

    actions = _compute_convergence_actions(config, desired, current_state, current_circuit)

    if not actions:
        print("No changes needed. Circuit is already converged.")
        return 0

    print("Convergence plan:")
    for action_type, data in actions:
        if action_type == "boot":
            print(f"  BOOT: Start circuit '{config.name}' with {len(config.nodes)} nodes")
            for n in config.nodes:
                print(f"    - {n.name} :{n.port} ({n.proxy_mode}, {n.role})")
            if config.routing:
                for name, rc in config.routing.items():
                    print(f"    - routing[{name}]: {rc.strategy}")
        elif action_type == "reboot":
            print("  REBOOT: Topology changed, will tear down and reboot")
        elif action_type == "add_node":
            n = data["node"]
            print(f"  ADD NODE: {n.name} :{n.port} ({n.proxy_mode}, {n.role})")
        elif action_type == "remove_node":
            print(f"  REMOVE NODE: {data['node_name']}")
        elif action_type == "add_edge":
            print(f"  ADD EDGE: {data['source']} -> {data['target']}")
        elif action_type == "remove_edge":
            print(f"  REMOVE EDGE: {data['source']} -> {data['target']}")
        elif action_type == "update_routing":
            rc = data["routing_config"]
            print(f"  UPDATE ROUTING: {data['node_name']} -> {rc.strategy}")
        elif action_type == "clear_routing":
            print(f"  CLEAR ROUTING: {data['node_name']}")

    if config.deploy.provider != "local":
        print(f"\n  Provider: {config.deploy.provider}")
        if config.deploy.project:
            print(f"  Project: {config.deploy.project}")
        if config.deploy.region:
            print(f"  Region: {config.deploy.region}")

    if config.security.tls.mode != "off":
        print(f"\n  Note: TLS mode is '{config.security.tls.mode}'")

    return 0


async def _cmd_apply(args: argparse.Namespace) -> int:
    """Apply declarative config -- converge desired vs running state."""
    from baton.collapse import build_mock_server, compute_mock_backends
    from baton.lifecycle import LifecycleManager

    project_dir = Path(args.dir)
    config = load_circuit_config(project_dir)

    if config.security.tls.mode != "off":
        print(f"Note: TLS mode is '{config.security.tls.mode}'", file=sys.stderr)

    mgr = LifecycleManager(project_dir)
    state = await mgr.apply(config)

    # Wire mock backends for nodes without live services
    mock_server = None
    circuit = config.to_circuit_spec()
    live_nodes = set(state.live_nodes)
    unmocked = {
        name for name, a in state.adapters.items()
        if name not in live_nodes and a.status == NodeStatus.LISTENING
    }
    if unmocked:
        mock_server = build_mock_server(circuit, live_nodes=live_nodes, project_dir=str(project_dir))
        backends = compute_mock_backends(circuit, live_nodes=live_nodes)

        await mock_server.start()
        for node_name, target in backends.items():
            adapter = mgr._adapters.get(node_name)
            if adapter:
                adapter.set_backend(target)
                if state.adapters.get(node_name):
                    state.adapters[node_name].status = NodeStatus.ACTIVE

    print(f"Circuit '{config.name}' applied ({len(state.adapters)} nodes)")

    # Only block on Ctrl+C for local provider
    if config.deploy.provider == "local":
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)

        try:
            await stop.wait()
        except asyncio.CancelledError:
            pass
        finally:
            if mock_server:
                await mock_server.stop()
            await mgr.down()
            print("\nCircuit torn down.")

    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    """Export running state as YAML config."""
    import yaml as _yaml

    project_dir = Path(args.dir)

    # Load existing config as base
    try:
        config = load_circuit_config(project_dir)
    except FileNotFoundError:
        print(f"Error: No {CONFIG_FILENAME} found in {project_dir}", file=sys.stderr)
        return 1

    # Overlay runtime routing from state
    current_state = load_state(project_dir)
    routing = dict(config.routing)
    if current_state:
        from baton.schemas import RoutingConfig as RC
        for name, adapter in current_state.adapters.items():
            if adapter.routing_config is not None:
                routing[name] = RC(**adapter.routing_config)

    # Build new config with runtime routing
    from baton.schemas import CircuitConfig as CC
    exported = CC(
        name=config.name,
        version=config.version,
        nodes=list(config.nodes),
        edges=list(config.edges),
        routing=routing,
        deploy=config.deploy,
        security=config.security,
    )

    data = _serialize_circuit_config(exported)
    output = _yaml.dump(data, default_flow_style=False, sort_keys=False)

    if args.output:
        Path(args.output).write_text(output)
        print(f"Exported to {args.output}")
    else:
        print(output, end="")

    return 0


def _cmd_federation(args: argparse.Namespace) -> int:
    """Handle federation status/peers commands."""
    import json as _json

    if not getattr(args, "federation_command", None):
        print("Usage: baton federation {status|peers}", file=sys.stderr)
        return 1

    project_dir = Path(args.dir)

    try:
        config = load_circuit_config(project_dir)
    except FileNotFoundError:
        print(f"Error: No {CONFIG_FILENAME} found in {project_dir}", file=sys.stderr)
        return 1

    fed = config.federation
    if fed is None or not fed.enabled:
        if getattr(args, "json_output", False):
            print(_json.dumps({"enabled": False}))
        else:
            print("Federation: not configured")
        return 0

    if args.federation_command == "status":
        identity = fed.identity
        data = {
            "enabled": True,
            "cluster": identity.name if identity else "",
            "endpoint": identity.api_endpoint if identity else "",
            "region": identity.region if identity else "",
            "peer_count": len(fed.peers),
            "edge_count": len(fed.edges),
            "heartbeat_interval_s": fed.heartbeat_interval_s,
            "failover_threshold": fed.failover_threshold,
        }
        if getattr(args, "json_output", False):
            print(_json.dumps(data, indent=2))
        else:
            print(f"Federation: enabled")
            print(f"  Cluster: {data['cluster']}")
            print(f"  Endpoint: {data['endpoint']}")
            if data["region"]:
                print(f"  Region: {data['region']}")
            print(f"  Peers: {data['peer_count']}")
            print(f"  Edges: {data['edge_count']}")
            print(f"  Heartbeat: every {data['heartbeat_interval_s']}s")
            print(f"  Failover threshold: {data['failover_threshold']} failures")
        return 0

    elif args.federation_command == "peers":
        peers = []
        for p in fed.peers:
            peers.append({
                "name": p.name,
                "endpoint": p.api_endpoint,
                "region": p.region,
                "priority": p.priority,
            })
        if getattr(args, "json_output", False):
            print(_json.dumps({"peers": peers}, indent=2))
        else:
            if not peers:
                print("No peers configured")
            else:
                print(f"Peers ({len(peers)}):")
                for p in peers:
                    region = f" ({p['region']})" if p["region"] else ""
                    print(f"  {p['name']}: {p['endpoint']}{region} [priority={p['priority']}]")
        return 0

    return 1


def _cmd_certs(args: argparse.Namespace) -> int:
    """Handle certs status/rotate commands."""
    import json as _json

    if not getattr(args, "certs_command", None):
        print("Usage: baton certs {status|rotate}", file=sys.stderr)
        return 1

    project_dir = Path(args.dir)

    try:
        config = load_circuit_config(project_dir)
    except FileNotFoundError:
        print(f"Error: No {CONFIG_FILENAME} found in {project_dir}", file=sys.stderr)
        return 1

    tls = config.security.tls

    if args.certs_command == "status":
        if not tls.cert:
            if getattr(args, "json_output", False):
                print(_json.dumps({"configured": False}))
            else:
                print("TLS: no certificate configured")
            return 0

        data: dict = {
            "configured": True,
            "cert_path": tls.cert,
            "key_path": tls.key,
            "mode": str(tls.mode),
            "auto_rotate": tls.auto_rotate,
        }

        # Try to parse the certificate
        cert_path = project_dir / tls.cert if not Path(tls.cert).is_absolute() else Path(tls.cert)
        try:
            from baton.certs import parse_certificate
            info = parse_certificate(cert_path)
            data["subject"] = info.subject
            data["issuer"] = info.issuer
            data["not_before"] = info.not_before
            data["not_after"] = info.not_after
            data["san"] = info.san
            data["fingerprint_sha256"] = info.fingerprint_sha256
            data["days_until_expiry"] = info.days_until_expiry
            data["expired"] = info.is_expired
        except FileNotFoundError:
            data["error"] = f"Certificate file not found: {cert_path}"
        except Exception as e:
            data["error"] = str(e)

        if getattr(args, "json_output", False):
            print(_json.dumps(data, indent=2))
        else:
            print(f"TLS Certificate:")
            print(f"  Path: {tls.cert}")
            print(f"  Mode: {tls.mode}")
            print(f"  Auto-rotate: {tls.auto_rotate}")
            if "error" in data:
                print(f"  Error: {data['error']}")
            elif "subject" in data:
                print(f"  Subject: {data['subject']}")
                print(f"  Issuer: {data['issuer']}")
                print(f"  Valid: {data['not_before']} to {data['not_after']}")
                if data["san"]:
                    print(f"  SAN: {', '.join(data['san'])}")
                print(f"  Expiry: {data['days_until_expiry']} days")
                if data["expired"]:
                    print(f"  WARNING: Certificate is expired!")
        return 0

    elif args.certs_command == "rotate":
        if not tls.cert or not tls.key:
            print("Error: No cert/key configured in security.tls", file=sys.stderr)
            return 1

        cert_path = project_dir / tls.cert if not Path(tls.cert).is_absolute() else Path(tls.cert)
        key_path = project_dir / tls.key if not Path(tls.key).is_absolute() else Path(tls.key)

        try:
            import ssl as _ssl
            from baton.certs import CertificateRotator
            ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
            rotator = CertificateRotator(ctx, cert_path, key_path)
            success = rotator.rotate()
            if success:
                print("Certificate rotated successfully")
                return 0
            else:
                print("Error: Certificate rotation failed", file=sys.stderr)
                return 1
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    return 1


def _cmd_taint(args: argparse.Namespace) -> int:
    import json as _json
    from baton.state import read_jsonl
    from baton.taint import TAINT_FILE, VIOLATIONS_FILE

    if args.taint_command == "status":
        canaries = read_jsonl(args.dir, TAINT_FILE)
        violations = read_jsonl(args.dir, VIOLATIONS_FILE)
        print(f"Active canary data:  {len(canaries)}")
        print(f"Violations detected: {len(violations)}")
        if canaries:
            print()
            print(f"  {'Category':<15} {'Fingerprint':<12} {'Seed Node':<15} {'Value'}")
            print(f"  {'─'*15} {'─'*12} {'─'*15} {'─'*30}")
            for c in canaries:
                print(f"  {c.get('category',''):<15} {c.get('fingerprint',''):<12} "
                      f"{c.get('seed_node',''):<15} {c.get('value','')}")
        return 0

    elif args.taint_command == "violations":
        violations = read_jsonl(args.dir, VIOLATIONS_FILE)
        if not violations:
            print("No taint violations detected")
            return 0
        print(f"Taint violations: {len(violations)}")
        print()
        for v in violations:
            print(f"  [{v.get('severity', 'critical').upper()}] "
                  f"Fingerprint {v.get('fingerprint', '')} ({v.get('category', '')})")
            print(f"    Seeded in:    {v.get('seed_node', '')}")
            print(f"    Observed at:  {v.get('observed_node', '')} ({v.get('observed_in', '')})")
            print(f"    Allowed:      {v.get('allowed_nodes', [])}")
            print(f"    Timestamp:    {v.get('timestamp', '')}")
            print()
        return 0

    elif args.taint_command == "seed":
        from baton.taint import CanaryGenerator
        from baton.state import append_jsonl, ensure_baton_dir

        ensure_baton_dir(args.dir)
        circuit = load_circuit(args.dir)
        generator = CanaryGenerator()

        nodes = circuit.nodes
        if args.node:
            nodes = [n for n in nodes if n.name == args.node]
            if not nodes:
                print(f"Error: node '{args.node}' not found", file=sys.stderr)
                return 1

        count = 0
        for node in nodes:
            canaries = generator.generate_set(node.name)
            neighbors = set(circuit.neighbors(node.name))
            dependents = set(circuit.dependents(node.name))
            allowed = {node.name} | neighbors | dependents
            for datum in canaries:
                entry = datum.to_dict()
                entry["allowed_nodes"] = sorted(allowed)
                append_jsonl(args.dir, TAINT_FILE, entry)
                count += 1

        print(f"Seeded {count} canary data points across {len(nodes)} node(s)")
        return 0

    elif args.taint_command == "clear":
        baton_dir = Path(args.dir) / ".baton"
        for f in (TAINT_FILE, VIOLATIONS_FILE):
            p = baton_dir / f
            if p.exists():
                p.unlink()
        print("Cleared all canary data and violations")
        return 0

    else:
        print("Usage: baton taint {seed|status|violations|clear}", file=sys.stderr)
        return 1


async def _cmd_trust(args: argparse.Namespace) -> int:
    from baton.arbiter import ArbiterClient
    config = load_circuit_config(args.dir)
    if not config.arbiter.api_endpoint:
        print("Arbiter not configured (no arbiter.api_endpoint in baton.yaml)")
        return 1
    client = ArbiterClient(config.arbiter.api_endpoint)
    trust = await client.get_trust_score(args.node)
    if trust is None:
        print(f"Could not reach Arbiter at {config.arbiter.api_endpoint}")
        return 1
    auth_str = " (authoritative)" if trust.authoritative else ""
    print(f"Node:    {trust.node_name}")
    print(f"Score:   {trust.score:.2f}")
    print(f"Level:   {trust.level}{auth_str}")
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    from baton.state import read_jsonl
    records = read_jsonl(args.dir, "service_events.jsonl", last_n=args.last)
    node_records = [r for r in records if r.get("node_name") == args.node]
    if not node_records:
        print(f"No audit events for '{args.node}'")
        return 0
    for r in node_records:
        ts = r.get("timestamp", "")[:19]
        event_type = r.get("type", "")
        msg = r.get("message", "")
        print(f"[{ts}] {event_type}: {msg}")
    return 0


async def _cmd_arbiter(args: argparse.Namespace) -> int:
    if args.arbiter_command == "status":
        from baton.arbiter import ArbiterClient
        config = load_circuit_config(args.dir)
        if not config.arbiter.api_endpoint:
            print("Arbiter not configured")
            return 0
        client = ArbiterClient(config.arbiter.api_endpoint)
        reachable = await client.is_reachable()
        print(f"Endpoint:    {config.arbiter.api_endpoint}")
        print(f"OTLP:        {config.arbiter.endpoint or 'not configured'}")
        print(f"Reachable:   {'yes' if reachable else 'no'}")
        print(f"Forward:     {'enabled' if config.arbiter.forward_spans else 'disabled'}")
        print(f"Classify:    {'enabled' if config.arbiter.classification_tagging else 'disabled'}")
        return 0
    else:
        print("Usage: baton arbiter {status}", file=sys.stderr)
        return 1


async def _cmd_sync_ledger(args: argparse.Namespace) -> int:
    config = load_circuit_config(args.dir)
    if not config.ledger.api_endpoint:
        print("Ledger not configured (no ledger.api_endpoint in baton.yaml)")
        return 1
    from baton.ledger import LedgerClient
    client = LedgerClient(config.ledger.api_endpoint)
    egress_nodes = await client.get_egress_export()
    if not egress_nodes:
        print("No egress nodes from Ledger (or Ledger unreachable)")
        return 1
    # Add egress nodes to circuit
    from baton.circuit import add_node
    circuit = load_circuit(args.dir)
    added = 0
    for en in egress_nodes:
        if not en.name:
            continue
        # Check if already exists
        if circuit.node_by_name(en.name):
            continue
        port = en.port or (max(n.port for n in circuit.nodes) + 1 if circuit.nodes else 8001)
        circuit = add_node(circuit, en.name, port=port, role="egress")
        added += 1
    if added:
        save_circuit(circuit, args.dir)
    print(f"Synced {len(egress_nodes)} egress nodes from Ledger ({added} new)")
    return 0


async def _cmd_test(args: argparse.Namespace) -> int:
    if not args.canary:
        print("Usage: baton test --canary [--tiers PII,FINANCIAL] [--duration 60s]")
        return 1

    from baton.canary_test import run_canary_test
    circuit = load_circuit(args.dir)

    # Parse duration
    duration_str = args.duration.strip()
    if duration_str.endswith("h"):
        duration_s = float(duration_str[:-1]) * 3600
    elif duration_str.endswith("m"):
        duration_s = float(duration_str[:-1]) * 60
    elif duration_str.endswith("s"):
        duration_s = float(duration_str[:-1])
    else:
        duration_s = float(duration_str)

    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()] if args.tiers else None
    node_names = [n.name for n in circuit.nodes]
    neighbors = {
        n.name: set(circuit.neighbors(n.name)) | set(circuit.dependents(n.name))
        for n in circuit.nodes
    }

    # Arbiter client if configured
    arbiter_client = None
    try:
        config = load_circuit_config(args.dir)
        if config.arbiter.api_endpoint:
            from baton.arbiter import ArbiterClient
            arbiter_client = ArbiterClient(config.arbiter.api_endpoint)
    except FileNotFoundError:
        pass

    print(f"Starting canary soak test ({duration_s:.0f}s)...")
    result = await run_canary_test(
        project_dir=Path(args.dir),
        circuit_nodes=node_names,
        circuit_neighbors=neighbors,
        duration_s=duration_s,
        tiers=tiers,
        run_id=args.run_id,
        arbiter_client=arbiter_client,
    )
    print(result.format_report())
    return 0 if result.violations_found == 0 else 1


def _cmd_migrate_config(args: argparse.Namespace) -> int:
    from baton.migrate import run_migrate

    config_path = Path(args.config)
    output_path = Path(args.output) if args.output else None
    return run_migrate(config_path, output_path=output_path, dry_run=args.dry_run)
