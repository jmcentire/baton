# === Baton Schemas (src_baton_schemas) v1 ===
#  Dependencies: pydantic, datetime, enum, typing
# Pydantic v2 data models for Baton circuit topology (frozen), runtime state (mutable), health monitoring, signals, and custodian events. Provides validation logic for circuit definitions, routing configurations, and node specifications.

# Module invariants:
#   - All NodeSpec instances are frozen (immutable) after validation
#   - All EdgeSpec instances are frozen (immutable) after validation
#   - All CircuitSpec instances are frozen (immutable) after validation
#   - All ServiceManifest instances are frozen (immutable) after validation
#   - All RoutingConfig instances are frozen (immutable) after validation
#   - Node names must match pattern ^[a-z][a-z0-9_-]*$
#   - Service names must match pattern ^[a-z][a-z0-9_-]*$
#   - Node ports must be in range 1024-65535
#   - Management ports are auto-computed as port + 10000 (or port + 1000 if overflow)
#   - Routing target weights must be in range 0-100
#   - For WEIGHTED and CANARY strategies, non-zero target weights must sum to 100
#   - For HEADER strategy, at least one rule and a default_target must be specified
#   - No edge can be a self-loop (source == target)
#   - All edge sources and targets must reference existing nodes in the circuit
#   - Egress nodes cannot be sources of edges (they are consumers, not producers)
#   - All node names in a circuit must be unique
#   - All node ports in a circuit must be unique
#   - All routing target names in a config must be unique

class NodeStatus(Enum):
    """Status of a node in the circuit"""
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    ACTIVE = "ACTIVE"
    DRAINING = "DRAINING"
    FAULTED = "FAULTED"

class ProxyMode(Enum):
    """Protocol mode for proxy"""
    HTTP = "HTTP"
    TCP = "TCP"

class NodeRole(Enum):
    """Role classification for nodes"""
    SERVICE = "SERVICE"
    INGRESS = "INGRESS"
    EGRESS = "EGRESS"

class CollapseLevel(Enum):
    """Level of mock vs live service deployment"""
    FULL_MOCK = "FULL_MOCK"
    PARTIAL = "PARTIAL"
    FULL_LIVE = "FULL_LIVE"

class HealthVerdict(Enum):
    """Health check result classification"""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"

class CustodianAction(Enum):
    """Actions the custodian can take"""
    RESTART_SERVICE = "RESTART_SERVICE"
    REPLACE_SERVICE = "REPLACE_SERVICE"
    BOOT_SECONDARY = "BOOT_SECONDARY"
    REROUTE = "REROUTE"
    ESCALATE = "ESCALATE"

class RoutingStrategy(Enum):
    """Routing strategy for traffic distribution"""
    SINGLE = "SINGLE"
    WEIGHTED = "WEIGHTED"
    HEADER = "HEADER"
    CANARY = "CANARY"

class NodeSpec:
    """A named slot in the circuit with a pre-assigned address (frozen)"""
    name: str                                # required, Node name matching pattern ^[a-z][a-z0-9_-]*$
    host: str = None                         # optional, Host address
    port: int                                # required, Port between 1024-65535
    proxy_mode: ProxyMode = None             # optional, Proxy protocol mode
    contract: str = None                     # optional, Contract identifier
    role: NodeRole = None                    # optional, Node role
    management_port: int = None              # optional, Management port (auto-computed if 0)
    metadata: dict[str, str] = None          # optional, Additional metadata

class EdgeSpec:
    """A directed connection between two nodes (frozen)"""
    source: str                              # required, Source node name
    target: str                              # required, Target node name
    label: str = None                        # optional, Edge label

class DependencySpec:
    """A service's declared dependency on another service (frozen)"""
    name: str                                # required, Dependency name
    expected_api: str = None                 # optional, Expected API specification
    optional: bool = None                    # optional, Whether dependency is optional

class CircuitSpec:
    """The full circuit board definition (frozen)"""
    name: str = None                         # optional, Circuit name
    version: int = None                      # optional, Circuit version
    nodes: list[NodeSpec] = None             # optional, List of nodes in circuit
    edges: list[EdgeSpec] = None             # optional, List of edges connecting nodes

class ServiceManifest:
    """Self-description of a service for circuit derivation (frozen)"""
    name: str                                # required, Service name matching pattern ^[a-z][a-z0-9_-]*$
    version: str = None                      # optional, Service version
    api_spec: str = None                     # optional, API specification
    mock_spec: str = None                    # optional, Mock specification
    command: str = None                      # optional, Command to run service
    port: int = None                         # optional, Service port
    proxy_mode: ProxyMode = None             # optional, Proxy mode
    role: NodeRole = None                    # optional, Service role
    dependencies: list[DependencySpec] = None # optional, Service dependencies
    metadata: dict[str, str] = None          # optional, Additional metadata

class RoutingTarget:
    """A backend target for routing (frozen)"""
    name: str                                # required, Target name
    host: str = None                         # optional, Target host
    port: int                                # required, Target port 1-65535
    weight: int = None                       # optional, Routing weight 0-100

class RoutingRule:
    """Route by header value to a named target (frozen)"""
    header: str                              # required, Header name
    value: str                               # required, Header value to match
    target: str                              # required, Target name for this rule

class RoutingConfig:
    """Routing configuration for an adapter (frozen)"""
    strategy: RoutingStrategy = None         # optional, Routing strategy
    targets: list[RoutingTarget] = None      # optional, List of routing targets
    rules: list[RoutingRule] = None          # optional, List of routing rules
    default_target: str = None               # optional, Default target name
    locked: bool = None                      # optional, Whether routing is locked

class ServiceSlot:
    """What is slotted into an adapter (mutable)"""
    command: str = None                      # optional
    is_mock: bool = None                     # optional
    pid: int = None                          # optional
    started_at: str = None                   # optional

class AdapterState:
    """Runtime state of a single adapter (mutable)"""
    node_name: str                           # required
    status: NodeStatus = None                # optional
    adapter_pid: int = None                  # optional
    service: ServiceSlot = None              # optional
    last_health_check: str = None            # optional
    last_health_verdict: HealthVerdict = None # optional
    consecutive_failures: int = None         # optional
    routing_config: dict | None = None       # optional

class CircuitState:
    """Full runtime state persisted to .baton/state.json (mutable)"""
    circuit_name: str = None                 # optional
    collapse_level: CollapseLevel = None     # optional
    live_nodes: list[str] = None             # optional
    adapters: dict[str, AdapterState] = None # optional
    mock_pid: int = None                     # optional
    custodian_pid: int = None                # optional
    started_at: str = None                   # optional
    updated_at: str = None                   # optional

class HealthCheck:
    """Result of a single health check (frozen)"""
    node_name: str                           # required
    verdict: HealthVerdict                   # required
    latency_ms: float = None                 # optional
    detail: str = None                       # optional
    timestamp: str = None                    # optional

class SignalRecord:
    """A recorded request/response through an adapter (frozen)"""
    node_name: str                           # required
    direction: Literal['inbound', 'outbound'] # required
    method: str = None                       # optional
    path: str = None                         # optional
    status_code: int = None                  # optional
    body_bytes: int = None                   # optional
    latency_ms: float = None                 # optional
    timestamp: str = None                    # optional

class CustodianEvent:
    """An event from the custodian's repair playbook (mutable)"""
    node_name: str                           # required
    action: CustodianAction                  # required
    reason: str                              # required
    success: bool = None                     # optional
    detail: str = None                       # optional
    timestamp: str = None                    # optional

class ImageInfo:
    """Metadata for a built container image (mutable)"""
    node_name: str                           # required
    tag: str                                 # required
    built_at: str = None                     # optional
    digest: str = None                       # optional

class DeploymentTarget:
    """Target for circuit deployment (frozen)"""
    provider: str = None                     # optional
    region: str = None                       # optional
    namespace: str = None                    # optional
    config: dict[str, str] = None            # optional

def auto_management_port(
    self: NodeSpec,
) -> NodeSpec:
    """
    Pydantic validator that automatically assigns a management port if it is set to 0. Adds 10000 to the main port, or 1000 if that exceeds 65535.

    Preconditions:
      - self.management_port must be an integer
      - self.port must be valid (1024-65535)

    Postconditions:
      - If self.management_port was 0, it is set to self.port + 10000 (or self.port + 1000 if > 65535)
      - Returns the modified NodeSpec instance

    Side effects: Mutates self.management_port via object.__setattr__
    Idempotent: no
    """
    ...

def no_self_loop(
    self: EdgeSpec,
) -> EdgeSpec:
    """
    Pydantic validator that ensures an edge does not connect a node to itself (no self-loops allowed).

    Preconditions:
      - self.source and self.target must be non-empty strings

    Postconditions:
      - Returns self unchanged if source != target

    Errors:
      - SelfLoopError (ValueError): self.source == self.target
          message: Self-loop not allowed: {source}

    Side effects: none
    Idempotent: no
    """
    ...

def unique_node_names(
    self: CircuitSpec,
) -> CircuitSpec:
    """
    Pydantic validator that ensures all node names in a circuit are unique.

    Preconditions:
      - self.nodes must be a list of NodeSpec instances

    Postconditions:
      - Returns self unchanged if all node names are unique

    Errors:
      - DuplicateNodeNamesError (ValueError): len(names) != len(set(names))
          message: Duplicate node names: {dupes}

    Side effects: none
    Idempotent: no
    """
    ...

def unique_ports(
    self: CircuitSpec,
) -> CircuitSpec:
    """
    Pydantic validator that ensures all node ports in a circuit are unique.

    Preconditions:
      - self.nodes must be a list of NodeSpec instances

    Postconditions:
      - Returns self unchanged if all node ports are unique

    Errors:
      - DuplicatePortsError (ValueError): len(ports) != len(set(ports))
          message: Duplicate ports in circuit

    Side effects: none
    Idempotent: no
    """
    ...

def egress_not_edge_source(
    self: CircuitSpec,
) -> CircuitSpec:
    """
    Pydantic validator that ensures egress nodes (external dependencies) cannot be sources of edges, as they should not be producers.

    Preconditions:
      - self.nodes must be a list of NodeSpec instances
      - self.edges must be a list of EdgeSpec instances

    Postconditions:
      - Returns self unchanged if no egress nodes are edge sources

    Errors:
      - EgressAsSourceError (ValueError): e.source in egress_names for any edge e
          message: Egress node '{source}' cannot be an edge source (egress nodes are external dependencies, not producers)

    Side effects: none
    Idempotent: no
    """
    ...

def edges_reference_existing_nodes(
    self: CircuitSpec,
) -> CircuitSpec:
    """
    Pydantic validator that ensures all edge sources and targets reference actual nodes in the circuit.

    Preconditions:
      - self.nodes must be a list of NodeSpec instances
      - self.edges must be a list of EdgeSpec instances

    Postconditions:
      - Returns self unchanged if all edge sources and targets exist in nodes

    Errors:
      - EdgeSourceNotFoundError (ValueError): e.source not in names for any edge e
          message: Edge source '{source}' not in nodes
      - EdgeTargetNotFoundError (ValueError): e.target not in names for any edge e
          message: Edge target '{target}' not in nodes

    Side effects: none
    Idempotent: no
    """
    ...

def node_by_name(
    self: CircuitSpec,
    name: str,
) -> NodeSpec | None:
    """
    Looks up a node in the circuit by name. Returns None if not found.

    Preconditions:
      - name must be a string

    Postconditions:
      - Returns NodeSpec if found, None otherwise

    Side effects: none
    Idempotent: no
    """
    ...

def neighbors(
    self: CircuitSpec,
    name: str,
) -> list[str]:
    """
    Returns a list of node names that the given node connects TO (outbound edges).

    Preconditions:
      - name must be a string

    Postconditions:
      - Returns list of target node names from edges where source == name

    Side effects: none
    Idempotent: no
    """
    ...

def dependents(
    self: CircuitSpec,
    name: str,
) -> list[str]:
    """
    Returns a list of node names that connect TO the given node (inbound edges).

    Preconditions:
      - name must be a string

    Postconditions:
      - Returns list of source node names from edges where target == name

    Side effects: none
    Idempotent: no
    """
    ...

def ingress_nodes(
    self: CircuitSpec,
) -> list[NodeSpec]:
    """
    Property that returns all nodes with the INGRESS role.

    Postconditions:
      - Returns list of NodeSpec where role == NodeRole.INGRESS

    Side effects: none
    Idempotent: no
    """
    ...

def egress_nodes(
    self: CircuitSpec,
) -> list[NodeSpec]:
    """
    Property that returns all nodes with the EGRESS role.

    Postconditions:
      - Returns list of NodeSpec where role == NodeRole.EGRESS

    Side effects: none
    Idempotent: no
    """
    ...

def weights_sum_to_100(
    self: RoutingConfig,
) -> RoutingConfig:
    """
    Pydantic validator that ensures routing target weights sum to 100 for WEIGHTED and CANARY strategies. Allows rollback configs where some targets have weight=0 as long as non-zero weights sum to 100.

    Preconditions:
      - self.targets must be a list of RoutingTarget instances
      - self.strategy must be a valid RoutingStrategy

    Postconditions:
      - Returns self unchanged if weights are valid for the strategy

    Errors:
      - WeightSumError (ValueError): strategy in (WEIGHTED, CANARY) and non-zero weights don't sum to 100
          message: Weights must sum to 100 for {strategy} strategy, got {total}

    Side effects: none
    Idempotent: no
    """
    ...

def header_requires_rules(
    self: RoutingConfig,
) -> RoutingConfig:
    """
    Pydantic validator that ensures HEADER routing strategy has at least one rule and a default_target.

    Preconditions:
      - self.strategy must be a valid RoutingStrategy
      - self.rules must be a list
      - self.default_target must be a string

    Postconditions:
      - Returns self unchanged if HEADER strategy has rules and default_target

    Errors:
      - NoRulesError (ValueError): strategy == HEADER and not self.rules
          message: Header strategy requires at least one rule
      - NoDefaultTargetError (ValueError): strategy == HEADER and not self.default_target
          message: Header strategy requires a default_target

    Side effects: none
    Idempotent: no
    """
    ...

def no_duplicate_target_names(
    self: RoutingConfig,
) -> RoutingConfig:
    """
    Pydantic validator that ensures all routing target names are unique within a RoutingConfig.

    Preconditions:
      - self.targets must be a list of RoutingTarget instances

    Postconditions:
      - Returns self unchanged if all target names are unique

    Errors:
      - DuplicateTargetNamesError (ValueError): len(names) != len(set(names))
          message: Duplicate target names: {dupes}

    Side effects: none
    Idempotent: no
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['NodeStatus', 'ProxyMode', 'NodeRole', 'CollapseLevel', 'HealthVerdict', 'CustodianAction', 'RoutingStrategy', 'NodeSpec', 'EdgeSpec', 'DependencySpec', 'CircuitSpec', 'ServiceManifest', 'RoutingTarget', 'RoutingRule', 'RoutingConfig', 'ServiceSlot', 'AdapterState', 'CircuitState', 'HealthCheck', 'SignalRecord', 'CustodianEvent', 'ImageInfo', 'DeploymentTarget', 'auto_management_port', 'no_self_loop', 'unique_node_names', 'unique_ports', 'egress_not_edge_source', 'edges_reference_existing_nodes', 'node_by_name', 'neighbors', 'dependents', 'ingress_nodes', 'egress_nodes', 'weights_sum_to_100', 'header_requires_rules', 'no_duplicate_target_names']
