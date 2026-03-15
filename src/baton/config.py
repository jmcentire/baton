"""Configuration loading for Baton.

Reads baton.yaml from a project directory and produces a CircuitSpec.
Supports both topology-first (baton.yaml nodes/edges) and service-first
(baton-service.yaml manifests) workflows.

Also supports full declarative config (CircuitConfig) with routing,
deploy, and security sections via load_circuit_config / save_circuit_config.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from baton.schemas import (
    ArbiterConfig,
    AuditChannelConfig,
    CircuitConfig,
    LedgerConfig,
    CircuitSpec,
    ClusterIdentity,
    ControlAuthConfig,
    DataAccessSpec,
    DeployConfig,
    EdgePolicy,
    EdgeSpec,
    FederationConfig,
    FederationEdge,
    NodeSpec,
    NodeTelemetryConfig,
    ObservabilityConfig,
    RoutingConfig,
    RoutingRule,
    RoutingTarget,
    SecurityConfig,
    TelemetryClassRule,
    TLSConfig,
    TLSMode,
)

CONFIG_FILENAME = "baton.yaml"

# Keys that belong to NodeSpec -- everything else on a node dict is stripped
_NODE_SPEC_KEYS = frozenset(NodeSpec.model_fields.keys())
# Keys that belong to EdgeSpec
_EDGE_SPEC_KEYS = frozenset(EdgeSpec.model_fields.keys()) - {"policy"}


def load_circuit(project_dir: str | Path) -> CircuitSpec:
    """Load CircuitSpec from baton.yaml in the given directory."""
    path = Path(project_dir) / CONFIG_FILENAME
    if not path.exists():
        raise FileNotFoundError(f"No {CONFIG_FILENAME} found in {project_dir}")
    with open(path) as f:
        raw = yaml.safe_load(f)
    if raw is None:
        return CircuitSpec()
    return _parse_circuit(raw)


def save_circuit(circuit: CircuitSpec, project_dir: str | Path) -> None:
    """Save CircuitSpec to baton.yaml in the given directory."""
    path = Path(project_dir) / CONFIG_FILENAME
    data = _serialize_circuit(circuit)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def load_circuit_config(project_dir: str | Path) -> CircuitConfig:
    """Load full CircuitConfig from baton.yaml (includes routing/deploy/security)."""
    path = Path(project_dir) / CONFIG_FILENAME
    if not path.exists():
        raise FileNotFoundError(f"No {CONFIG_FILENAME} found in {project_dir}")
    with open(path) as f:
        raw = yaml.safe_load(f)
    if raw is None:
        return CircuitConfig()
    return _parse_circuit_config(raw)


def save_circuit_config(config: CircuitConfig, project_dir: str | Path) -> None:
    """Save full CircuitConfig to baton.yaml."""
    path = Path(project_dir) / CONFIG_FILENAME
    data = _serialize_circuit_config(config)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def load_circuit_from_services(
    project_dir: str | Path,
    service_dirs: list[str | Path] | None = None,
) -> CircuitSpec:
    """Derive CircuitSpec from service manifests.

    If service_dirs is None, discovers them from baton.yaml's 'services'
    key or by scanning subdirectories for baton-service.yaml files.
    """
    from baton.registry import derive_circuit, load_manifests

    base = Path(project_dir)
    if service_dirs is None:
        service_dirs = _discover_service_dirs(base)

    if not service_dirs:
        raise FileNotFoundError("No service directories found")

    manifests = load_manifests(service_dirs)

    circuit_name = "default"
    config_path = base / CONFIG_FILENAME
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
        circuit_name = raw.get("name", "default")

    return derive_circuit(manifests, circuit_name=circuit_name)


def _discover_service_dirs(project_dir: Path) -> list[Path]:
    """Auto-discover service directories.

    1. Check baton.yaml for a 'services' list of paths.
    2. Otherwise, scan immediate subdirectories for baton-service.yaml.
    """
    from baton.manifest import MANIFEST_FILENAME

    config_path = project_dir / CONFIG_FILENAME
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
        if "services" in raw:
            return [project_dir / s for s in raw["services"]]

    dirs = []
    if project_dir.is_dir():
        for child in sorted(project_dir.iterdir()):
            if child.is_dir() and (child / MANIFEST_FILENAME).exists():
                dirs.append(child)
    return dirs


def add_service_path(project_dir: str | Path, service_path: str) -> None:
    """Add a service directory path to baton.yaml's services list."""
    base = Path(project_dir)
    config_path = base / CONFIG_FILENAME
    if not config_path.exists():
        raise FileNotFoundError(f"No {CONFIG_FILENAME} found in {project_dir}")

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    services = raw.get("services", [])
    if service_path not in services:
        services.append(service_path)
    raw["services"] = services

    with open(config_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False)


# -- Internal parsers --


def _parse_circuit(raw: dict) -> CircuitSpec:
    """Parse raw YAML dict into CircuitSpec.

    Strips keys that don't belong to NodeSpec/EdgeSpec (e.g. routing on nodes,
    policy on edges) so that older code doesn't crash on new config sections.
    """
    nodes = []
    for n in raw.get("nodes", []):
        clean = {k: v for k, v in n.items() if k in _NODE_SPEC_KEYS}
        nodes.append(NodeSpec(**clean))
    edges = []
    for e in raw.get("edges", []):
        clean = {k: v for k, v in e.items() if k in _EDGE_SPEC_KEYS}
        edges.append(EdgeSpec(**clean))
    return CircuitSpec(
        name=raw.get("name", "default"),
        version=raw.get("version", 1),
        nodes=nodes,
        edges=edges,
    )


def _parse_circuit_config(raw: dict) -> CircuitConfig:
    """Parse raw YAML dict into full CircuitConfig."""
    # Parse nodes, extracting routing and telemetry configs
    nodes = []
    routing: dict[str, RoutingConfig] = {}
    node_telemetry: dict[str, NodeTelemetryConfig] = {}
    for n in raw.get("nodes", []):
        # Extract routing from node dict if present
        if "routing" in n:
            routing[n["name"]] = _parse_routing(n["routing"])
        # Extract telemetry from node dict if present
        if "telemetry" in n:
            tel = _parse_node_telemetry(n["telemetry"])
            if tel:
                node_telemetry[n["name"]] = tel
        # Parse data_access nested model
        if "data_access" in n and isinstance(n["data_access"], dict):
            n["data_access"] = DataAccessSpec(**n["data_access"])
        clean = {k: v for k, v in n.items() if k in _NODE_SPEC_KEYS}
        nodes.append(NodeSpec(**clean))

    # Parse edges with optional policy
    edges = []
    for e in raw.get("edges", []):
        policy = None
        if "policy" in e:
            policy = EdgePolicy(**e["policy"])
        clean = {k: v for k, v in e.items() if k in _EDGE_SPEC_KEYS}
        edges.append(EdgeSpec(**clean, policy=policy))

    # Parse top-level routing section (overrides per-node routing)
    raw_routing = raw.get("routing", {})
    for node_name, rcfg in raw_routing.items():
        routing[node_name] = _parse_routing(rcfg)

    # Parse deploy, security, observability, and federation
    deploy = _parse_deploy(raw.get("deploy", {}))
    security = _parse_security(raw.get("security", {}))
    observability = _parse_observability(raw.get("observability", {}))
    federation = _parse_federation(raw.get("federation", {}))
    arbiter = _parse_arbiter(raw.get("arbiter", {}))
    audit_channel = _parse_audit_channel(raw.get("audit_channel", {}))
    ledger = _parse_ledger(raw.get("ledger", {}))

    return CircuitConfig(
        name=raw.get("name", "default"),
        version=raw.get("version", 1),
        nodes=nodes,
        edges=edges,
        routing=routing,
        deploy=deploy,
        security=security,
        observability=observability,
        node_telemetry=node_telemetry,
        federation=federation,
        arbiter=arbiter,
        audit_channel=audit_channel,
        ledger=ledger,
    )


def _parse_routing(raw: dict) -> RoutingConfig:
    """Parse a routing config dict."""
    targets = [RoutingTarget(**t) for t in raw.get("targets", [])]
    rules = [RoutingRule(**r) for r in raw.get("rules", [])]
    return RoutingConfig(
        strategy=raw.get("strategy", "single"),
        targets=targets,
        rules=rules,
        default_target=raw.get("default_target", ""),
        locked=raw.get("locked", False),
    )


def _parse_deploy(raw: dict) -> DeployConfig:
    """Parse deploy section."""
    if not raw:
        return DeployConfig()
    return DeployConfig(**raw)


def _parse_security(raw: dict) -> SecurityConfig:
    """Parse security section."""
    if not raw:
        return SecurityConfig()
    tls_raw = raw.get("tls", {})
    control_raw = raw.get("control", {})
    tls = TLSConfig(**tls_raw) if tls_raw else TLSConfig()
    control = ControlAuthConfig(**control_raw) if control_raw else ControlAuthConfig()
    return SecurityConfig(tls=tls, control=control)


def _parse_observability(raw: dict) -> ObservabilityConfig:
    """Parse observability section."""
    if not raw:
        return ObservabilityConfig()
    return ObservabilityConfig(**raw)


def _parse_node_telemetry(raw: dict) -> NodeTelemetryConfig | None:
    """Parse per-node telemetry config from node dict."""
    if not raw:
        return None
    classes = []
    for c in raw.get("classes", []):
        classes.append(TelemetryClassRule(
            match=c.get("match", ""),
            telemetry_class=c.get("class", c.get("telemetry_class", "")),
            slo_p95_ms=c.get("slo_p95_ms", 0),
            owner=c.get("owner", ""),
        ))
    return NodeTelemetryConfig(classes=classes)


def _parse_federation(raw: dict) -> FederationConfig:
    """Parse federation section."""
    if not raw or not raw.get("enabled"):
        return FederationConfig()

    identity = None
    if "identity" in raw:
        identity = ClusterIdentity(**raw["identity"])

    peers = [ClusterIdentity(**p) for p in raw.get("peers", [])]

    edges = []
    for e in raw.get("edges", []):
        edges.append(FederationEdge(**e))

    return FederationConfig(
        enabled=raw.get("enabled", False),
        identity=identity,
        peers=peers,
        edges=edges,
        heartbeat_interval_s=raw.get("heartbeat_interval_s", 30.0),
        heartbeat_timeout_s=raw.get("heartbeat_timeout_s", 10.0),
        failover_threshold=raw.get("failover_threshold", 3),
    )


def _parse_arbiter(raw: dict) -> ArbiterConfig:
    """Parse arbiter section."""
    if not raw:
        return ArbiterConfig()
    return ArbiterConfig(**raw)


def _parse_audit_channel(raw: dict) -> AuditChannelConfig:
    """Parse audit_channel section."""
    if not raw:
        return AuditChannelConfig()
    return AuditChannelConfig(**raw)


def _parse_ledger(raw: dict) -> LedgerConfig:
    if not raw:
        return LedgerConfig()
    return LedgerConfig(**raw)


# -- Internal serializers --


def _serialize_circuit(circuit: CircuitSpec) -> dict:
    """Convert CircuitSpec to a YAML-serializable dict."""
    data: dict = {
        "name": circuit.name,
        "version": circuit.version,
    }
    if circuit.nodes:
        data["nodes"] = []
        for n in circuit.nodes:
            nd: dict = {"name": n.name, "port": n.port}
            if n.host != "127.0.0.1":
                nd["host"] = n.host
            if n.proxy_mode != "http":
                nd["proxy_mode"] = str(n.proxy_mode)
            if n.contract:
                nd["contract"] = n.contract
            if n.role != "service":
                nd["role"] = str(n.role)
            if n.metadata:
                nd["metadata"] = dict(n.metadata)
            if n.data_access:
                nd["data_access"] = {"reads": list(n.data_access.reads), "writes": list(n.data_access.writes)}
            if n.authority:
                nd["authority"] = list(n.authority)
            if n.openapi_spec:
                nd["openapi_spec"] = n.openapi_spec
            data["nodes"].append(nd)
    if circuit.edges:
        data["edges"] = []
        for e in circuit.edges:
            ed: dict = {"source": e.source, "target": e.target}
            if e.label:
                ed["label"] = e.label
            if e.policy:
                ed["policy"] = _serialize_edge_policy(e.policy)
            if e.data_tiers_in_flight:
                ed["data_tiers_in_flight"] = list(e.data_tiers_in_flight)
            data["edges"].append(ed)
    return data


def _serialize_circuit_config(config: CircuitConfig) -> dict:
    """Convert CircuitConfig to a YAML-serializable dict.

    Injects routing back into node dicts, policy into edge dicts.
    """
    data: dict = {
        "name": config.name,
        "version": config.version,
    }

    if config.nodes:
        data["nodes"] = []
        for n in config.nodes:
            nd: dict = {"name": n.name, "port": n.port}
            if n.host != "127.0.0.1":
                nd["host"] = n.host
            if n.proxy_mode != "http":
                nd["proxy_mode"] = str(n.proxy_mode)
            if n.contract:
                nd["contract"] = n.contract
            if n.role != "service":
                nd["role"] = str(n.role)
            if n.metadata:
                nd["metadata"] = dict(n.metadata)
            if n.data_access:
                nd["data_access"] = {"reads": list(n.data_access.reads), "writes": list(n.data_access.writes)}
            if n.authority:
                nd["authority"] = list(n.authority)
            if n.openapi_spec:
                nd["openapi_spec"] = n.openapi_spec
            # Inject routing into node dict
            if n.name in config.routing:
                nd["routing"] = _serialize_routing(config.routing[n.name])
            # Inject telemetry into node dict
            if n.name in config.node_telemetry:
                nd["telemetry"] = _serialize_node_telemetry(config.node_telemetry[n.name])
            data["nodes"].append(nd)

    if config.edges:
        data["edges"] = []
        for e in config.edges:
            ed: dict = {"source": e.source, "target": e.target}
            if e.label:
                ed["label"] = e.label
            if e.policy:
                ed["policy"] = _serialize_edge_policy(e.policy)
            if e.data_tiers_in_flight:
                ed["data_tiers_in_flight"] = list(e.data_tiers_in_flight)
            data["edges"].append(ed)

    # Deploy section (omit defaults)
    deploy = _serialize_deploy(config.deploy)
    if deploy:
        data["deploy"] = deploy

    # Security section (omit defaults)
    security = _serialize_security(config.security)
    if security:
        data["security"] = security

    # Observability section (omit defaults)
    observability = _serialize_observability(config.observability)
    if observability:
        data["observability"] = observability

    # Federation section (omit if not enabled)
    federation = _serialize_federation(config.federation)
    if federation:
        data["federation"] = federation

    # Arbiter section (omit if not configured)
    arbiter = _serialize_arbiter(config.arbiter)
    if arbiter:
        data["arbiter"] = arbiter

    # Audit channel section (omit if default)
    audit_channel = _serialize_audit_channel(config.audit_channel)
    if audit_channel:
        data["audit_channel"] = audit_channel

    # Ledger section (omit if not configured)
    ledger = _serialize_ledger(config.ledger)
    if ledger:
        data["ledger"] = ledger

    return data


def _serialize_routing(routing: RoutingConfig) -> dict:
    """Serialize a RoutingConfig to dict."""
    d: dict = {"strategy": str(routing.strategy)}
    if routing.targets:
        d["targets"] = []
        for t in routing.targets:
            td: dict = {"name": t.name, "port": t.port, "weight": t.weight}
            if t.host != "127.0.0.1":
                td["host"] = t.host
            d["targets"].append(td)
    if routing.rules:
        d["rules"] = [
            {"header": r.header, "value": r.value, "target": r.target}
            for r in routing.rules
        ]
    if routing.default_target:
        d["default_target"] = routing.default_target
    if routing.locked:
        d["locked"] = True
    return d


def _serialize_edge_policy(policy: EdgePolicy) -> dict:
    """Serialize an EdgePolicy to dict, omitting defaults."""
    d: dict = {}
    if policy.timeout_ms != 30000:
        d["timeout_ms"] = policy.timeout_ms
    if policy.retries != 0:
        d["retries"] = policy.retries
    if policy.retry_backoff_ms != 100:
        d["retry_backoff_ms"] = policy.retry_backoff_ms
    if policy.circuit_breaker_threshold != 0:
        d["circuit_breaker_threshold"] = policy.circuit_breaker_threshold
    return d


def _serialize_deploy(deploy: DeployConfig) -> dict:
    """Serialize DeployConfig, omitting defaults."""
    d: dict = {}
    if deploy.provider != "local":
        d["provider"] = deploy.provider
    if deploy.project:
        d["project"] = deploy.project
    if deploy.region:
        d["region"] = deploy.region
    if deploy.namespace:
        d["namespace"] = deploy.namespace
    if deploy.build:
        d["build"] = deploy.build
    if deploy.image:
        d["image"] = deploy.image
    return d


def _serialize_security(security: SecurityConfig) -> dict:
    """Serialize SecurityConfig, omitting defaults."""
    d: dict = {}
    tls = security.tls
    if tls.mode != TLSMode.OFF or tls.cert or tls.key or tls.auto_rotate:
        td: dict = {}
        if tls.mode != TLSMode.OFF:
            td["mode"] = str(tls.mode)
        if tls.cert:
            td["cert"] = tls.cert
        if tls.key:
            td["key"] = tls.key
        if tls.auto_rotate:
            td["auto_rotate"] = tls.auto_rotate
        if tls.rotate_check_interval_s != 3600.0:
            td["rotate_check_interval_s"] = tls.rotate_check_interval_s
        if tls.warning_days != 30:
            td["warning_days"] = tls.warning_days
        if tls.critical_days != 7:
            td["critical_days"] = tls.critical_days
        d["tls"] = td
    ctrl = security.control
    if ctrl.auth or ctrl.token_env:
        cd: dict = {}
        if ctrl.auth:
            cd["auth"] = ctrl.auth
        if ctrl.token_env:
            cd["token_env"] = ctrl.token_env
        d["control"] = cd
    return d


def _serialize_observability(obs: ObservabilityConfig) -> dict:
    """Serialize ObservabilityConfig, omitting defaults."""
    d: dict = {}
    if obs.enabled:
        d["enabled"] = obs.enabled
    if obs.sink != "jsonl":
        d["sink"] = obs.sink
    if obs.otlp_endpoint:
        d["otlp_endpoint"] = obs.otlp_endpoint
    if obs.otlp_protocol != "grpc":
        d["otlp_protocol"] = obs.otlp_protocol
    if obs.service_name:
        d["service_name"] = obs.service_name
    if obs.trace_sample_rate != 1.0:
        d["trace_sample_rate"] = obs.trace_sample_rate
    return d


def _serialize_node_telemetry(tel: NodeTelemetryConfig) -> dict:
    """Serialize NodeTelemetryConfig."""
    d: dict = {}
    if tel.classes:
        classes = []
        for c in tel.classes:
            cd: dict = {}
            if c.match:
                cd["match"] = c.match
            if c.telemetry_class:
                cd["class"] = c.telemetry_class
            if c.slo_p95_ms:
                cd["slo_p95_ms"] = c.slo_p95_ms
            if c.owner:
                cd["owner"] = c.owner
            classes.append(cd)
        d["classes"] = classes
    return d


def _serialize_federation(federation: FederationConfig) -> dict:
    """Serialize FederationConfig, omitting if disabled."""
    if not federation.enabled:
        return {}
    d: dict = {"enabled": True}
    if federation.identity:
        id_d: dict = {"name": federation.identity.name, "api_endpoint": federation.identity.api_endpoint}
        if federation.identity.region:
            id_d["region"] = federation.identity.region
        if federation.identity.priority:
            id_d["priority"] = federation.identity.priority
        d["identity"] = id_d
    if federation.peers:
        d["peers"] = []
        for p in federation.peers:
            pd: dict = {"name": p.name, "api_endpoint": p.api_endpoint}
            if p.region:
                pd["region"] = p.region
            if p.priority:
                pd["priority"] = p.priority
            d["peers"].append(pd)
    if federation.edges:
        d["edges"] = []
        for e in federation.edges:
            ed: dict = {"source_cluster": e.source_cluster, "target_cluster": e.target_cluster}
            if e.node_mapping:
                ed["node_mapping"] = dict(e.node_mapping)
            d["edges"].append(ed)
    if federation.heartbeat_interval_s != 30.0:
        d["heartbeat_interval_s"] = federation.heartbeat_interval_s
    if federation.heartbeat_timeout_s != 10.0:
        d["heartbeat_timeout_s"] = federation.heartbeat_timeout_s
    if federation.failover_threshold != 3:
        d["failover_threshold"] = federation.failover_threshold
    return d


def _serialize_arbiter(arbiter: ArbiterConfig) -> dict:
    """Serialize ArbiterConfig, omitting defaults."""
    d: dict = {}
    if arbiter.endpoint:
        d["endpoint"] = arbiter.endpoint
    if arbiter.http_endpoint:
        d["http_endpoint"] = arbiter.http_endpoint
    if arbiter.api_endpoint:
        d["api_endpoint"] = arbiter.api_endpoint
    if arbiter.forward_spans:
        d["forward_spans"] = arbiter.forward_spans
    if arbiter.classification_tagging:
        d["classification_tagging"] = arbiter.classification_tagging
    return d


def _serialize_audit_channel(audit_channel: AuditChannelConfig) -> dict:
    """Serialize AuditChannelConfig, omitting defaults."""
    d: dict = {}
    if audit_channel.port != 9000:
        d["port"] = audit_channel.port
    if audit_channel.protocol != "http":
        d["protocol"] = audit_channel.protocol
    return d


def _serialize_ledger(ledger: LedgerConfig) -> dict:
    d: dict = {}
    if ledger.api_endpoint:
        d["api_endpoint"] = ledger.api_endpoint
    if not ledger.mock_from_ledger:
        d["mock_from_ledger"] = ledger.mock_from_ledger
    return d
