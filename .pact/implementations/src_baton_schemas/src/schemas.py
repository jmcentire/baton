"""All Pydantic v2 data models for Baton.

Circuit topology (frozen), runtime state (mutable), health, signals, custodian events.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# -- Enums --


class NodeStatus(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    ACTIVE = "active"
    DRAINING = "draining"
    FAULTED = "faulted"


class ProxyMode(StrEnum):
    HTTP = "http"
    TCP = "tcp"


class NodeRole(StrEnum):
    SERVICE = "service"
    INGRESS = "ingress"
    EGRESS = "egress"


class CollapseLevel(StrEnum):
    FULL_MOCK = "full_mock"
    PARTIAL = "partial"
    FULL_LIVE = "full_live"


class HealthVerdict(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class CustodianAction(StrEnum):
    RESTART_SERVICE = "restart_service"
    REPLACE_SERVICE = "replace_service"
    BOOT_SECONDARY = "boot_secondary"
    REROUTE = "reroute"
    ESCALATE = "escalate"


class RoutingStrategy(StrEnum):
    SINGLE = "single"
    WEIGHTED = "weighted"
    HEADER = "header"
    CANARY = "canary"


# -- Circuit Definition (frozen) --


class NodeSpec(BaseModel):
    """A named slot in the circuit with a pre-assigned address."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_-]*$")
    host: str = "127.0.0.1"
    port: int = Field(ge=1024, le=65535)
    proxy_mode: ProxyMode = ProxyMode.HTTP
    contract: str = ""
    role: NodeRole = NodeRole.SERVICE
    management_port: int = 0
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def auto_management_port(self) -> NodeSpec:
        if self.management_port == 0:
            mgmt = self.port + 10000
            if mgmt > 65535:
                mgmt = self.port + 1000
            object.__setattr__(self, "management_port", mgmt)
        return self


class EdgeSpec(BaseModel):
    """A directed connection between two nodes."""

    model_config = ConfigDict(frozen=True)

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    label: str = ""

    @model_validator(mode="after")
    def no_self_loop(self) -> EdgeSpec:
        if self.source == self.target:
            raise ValueError(f"Self-loop not allowed: {self.source}")
        return self


class DependencySpec(BaseModel):
    """A service's declared dependency on another service."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    expected_api: str = ""
    optional: bool = False


class CircuitSpec(BaseModel):
    """The full circuit board definition."""

    model_config = ConfigDict(frozen=True)

    name: str = "default"
    version: int = 1
    nodes: list[NodeSpec] = Field(default_factory=list)
    edges: list[EdgeSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_node_names(self) -> CircuitSpec:
        names = [n.name for n in self.nodes]
        if len(names) != len(set(names)):
            dupes = [n for n in names if names.count(n) > 1]
            raise ValueError(f"Duplicate node names: {set(dupes)}")
        return self

    @model_validator(mode="after")
    def unique_ports(self) -> CircuitSpec:
        ports = [n.port for n in self.nodes]
        if len(ports) != len(set(ports)):
            raise ValueError("Duplicate ports in circuit")
        return self

    @model_validator(mode="after")
    def egress_not_edge_source(self) -> CircuitSpec:
        egress_names = {n.name for n in self.nodes if n.role == NodeRole.EGRESS}
        for e in self.edges:
            if e.source in egress_names:
                raise ValueError(
                    f"Egress node '{e.source}' cannot be an edge source "
                    f"(egress nodes are external dependencies, not producers)"
                )
        return self

    @model_validator(mode="after")
    def edges_reference_existing_nodes(self) -> CircuitSpec:
        names = {n.name for n in self.nodes}
        for e in self.edges:
            if e.source not in names:
                raise ValueError(f"Edge source '{e.source}' not in nodes")
            if e.target not in names:
                raise ValueError(f"Edge target '{e.target}' not in nodes")
        return self

    def node_by_name(self, name: str) -> NodeSpec | None:
        for n in self.nodes:
            if n.name == name:
                return n
        return None

    def neighbors(self, name: str) -> list[str]:
        """Nodes that this node connects TO."""
        return [e.target for e in self.edges if e.source == name]

    def dependents(self, name: str) -> list[str]:
        """Nodes that connect TO this node."""
        return [e.source for e in self.edges if e.target == name]

    @property
    def ingress_nodes(self) -> list[NodeSpec]:
        """Nodes with ingress role."""
        return [n for n in self.nodes if n.role == NodeRole.INGRESS]

    @property
    def egress_nodes(self) -> list[NodeSpec]:
        """Nodes with egress role."""
        return [n for n in self.nodes if n.role == NodeRole.EGRESS]


# -- Service Manifest (frozen) --


class ServiceManifest(BaseModel):
    """Self-description of a service for circuit derivation."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_-]*$")
    version: str = "0.0.0"
    api_spec: str = ""
    mock_spec: str = ""
    command: str = ""
    port: int = Field(default=0, ge=0, le=65535)
    proxy_mode: ProxyMode = ProxyMode.HTTP
    role: NodeRole = NodeRole.SERVICE
    dependencies: list[DependencySpec] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


# -- Routing (frozen) --


class RoutingTarget(BaseModel):
    """A backend target for routing."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    host: str = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    weight: int = Field(default=100, ge=0, le=100)


class RoutingRule(BaseModel):
    """Route by header value to a named target."""

    model_config = ConfigDict(frozen=True)

    header: str = Field(min_length=1)
    value: str = Field(min_length=1)
    target: str = Field(min_length=1)


class RoutingConfig(BaseModel):
    """Routing configuration for an adapter."""

    model_config = ConfigDict(frozen=True)

    strategy: RoutingStrategy = RoutingStrategy.SINGLE
    targets: list[RoutingTarget] = Field(default_factory=list)
    rules: list[RoutingRule] = Field(default_factory=list)
    default_target: str = ""
    locked: bool = False

    @model_validator(mode="after")
    def weights_sum_to_100(self) -> RoutingConfig:
        if self.strategy in (RoutingStrategy.WEIGHTED, RoutingStrategy.CANARY):
            total = sum(t.weight for t in self.targets)
            if total != 100:
                # Allow rollback configs where some targets have weight=0
                non_zero = [t for t in self.targets if t.weight > 0]
                non_zero_total = sum(t.weight for t in non_zero)
                if non_zero_total != 100:
                    raise ValueError(
                        f"Weights must sum to 100 for {self.strategy} strategy, got {total}"
                    )
        return self

    @model_validator(mode="after")
    def header_requires_rules(self) -> RoutingConfig:
        if self.strategy == RoutingStrategy.HEADER:
            if not self.rules:
                raise ValueError("Header strategy requires at least one rule")
            if not self.default_target:
                raise ValueError("Header strategy requires a default_target")
        return self

    @model_validator(mode="after")
    def no_duplicate_target_names(self) -> RoutingConfig:
        names = [t.name for t in self.targets]
        if len(names) != len(set(names)):
            dupes = [n for n in names if names.count(n) > 1]
            raise ValueError(f"Duplicate target names: {set(dupes)}")
        return self


# -- Runtime State (mutable) --


class ServiceSlot(BaseModel):
    """What is slotted into an adapter."""

    command: str = ""
    is_mock: bool = True
    pid: int = 0
    started_at: str = ""


class AdapterState(BaseModel):
    """Runtime state of a single adapter."""

    node_name: str
    status: NodeStatus = NodeStatus.IDLE
    adapter_pid: int = 0
    service: ServiceSlot = Field(default_factory=ServiceSlot)
    last_health_check: str = ""
    last_health_verdict: HealthVerdict = HealthVerdict.UNKNOWN
    consecutive_failures: int = 0
    routing_config: dict | None = None


class CircuitState(BaseModel):
    """Full runtime state -- persisted to .baton/state.json."""

    circuit_name: str = "default"
    collapse_level: CollapseLevel = CollapseLevel.FULL_MOCK
    live_nodes: list[str] = Field(default_factory=list)
    adapters: dict[str, AdapterState] = Field(default_factory=dict)
    mock_pid: int = 0
    custodian_pid: int = 0
    started_at: str = ""
    updated_at: str = ""


# -- Health & Signals --


class HealthCheck(BaseModel):
    """Result of a single health check."""

    model_config = ConfigDict(frozen=True)

    node_name: str
    verdict: HealthVerdict
    latency_ms: float = 0.0
    detail: str = ""
    timestamp: str = ""


class SignalRecord(BaseModel):
    """A recorded request/response through an adapter."""

    model_config = ConfigDict(frozen=True)

    node_name: str
    direction: Literal["inbound", "outbound"]
    method: str = ""
    path: str = ""
    status_code: int = 0
    body_bytes: int = 0
    latency_ms: float = 0.0
    timestamp: str = ""


# -- Custodian Events --


class CustodianEvent(BaseModel):
    """An event from the custodian's repair playbook."""

    node_name: str
    action: CustodianAction
    reason: str
    success: bool = False
    detail: str = ""
    timestamp: str = ""


# -- Image Building --


class ImageInfo(BaseModel):
    """Metadata for a built container image."""

    node_name: str
    tag: str
    built_at: str = ""
    digest: str = ""


# -- Deployment --


class DeploymentTarget(BaseModel):
    """Target for circuit deployment."""

    model_config = ConfigDict(frozen=True)

    provider: str = "local"
    region: str = ""
    namespace: str = ""
    config: dict[str, str] = Field(default_factory=dict)
