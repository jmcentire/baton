"""Tests for Baton data models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from baton.schemas import (
    AdapterState,
    CircuitSpec,
    CircuitState,
    CollapseLevel,
    CustodianAction,
    CustodianEvent,
    DeploymentTarget,
    DependencySpec,
    EdgeSpec,
    HealthCheck,
    HealthVerdict,
    NodeRole,
    NodeSpec,
    NodeStatus,
    ProxyMode,
    RoutingConfig,
    RoutingRule,
    RoutingStrategy,
    RoutingTarget,
    ServiceManifest,
    ServiceSlot,
    SignalRecord,
)


# -- NodeSpec --


class TestNodeSpec:
    def test_valid_node(self):
        n = NodeSpec(name="payments", port=8001)
        assert n.name == "payments"
        assert n.host == "127.0.0.1"
        assert n.port == 8001
        assert n.proxy_mode == ProxyMode.HTTP

    def test_auto_management_port(self):
        n = NodeSpec(name="api", port=8001)
        assert n.management_port == 18001

    def test_auto_management_port_high(self):
        n = NodeSpec(name="api", port=60000)
        # 60000 + 10000 > 65535, so falls back to + 1000
        assert n.management_port == 61000

    def test_explicit_management_port(self):
        n = NodeSpec(name="api", port=8001, management_port=9999)
        assert n.management_port == 9999

    def test_name_must_start_with_letter(self):
        with pytest.raises(ValidationError):
            NodeSpec(name="1bad", port=8001)

    def test_name_allows_hyphens_and_underscores(self):
        n = NodeSpec(name="my-service_v2", port=8001)
        assert n.name == "my-service_v2"

    def test_name_rejects_uppercase(self):
        with pytest.raises(ValidationError):
            NodeSpec(name="MyService", port=8001)

    def test_name_cannot_be_empty(self):
        with pytest.raises(ValidationError):
            NodeSpec(name="", port=8001)

    def test_port_range_low(self):
        with pytest.raises(ValidationError):
            NodeSpec(name="api", port=80)

    def test_port_range_high(self):
        with pytest.raises(ValidationError):
            NodeSpec(name="api", port=70000)

    def test_frozen(self):
        n = NodeSpec(name="api", port=8001)
        with pytest.raises(ValidationError):
            n.port = 9000

    def test_tcp_mode(self):
        n = NodeSpec(name="db", port=5432, proxy_mode="tcp")
        assert n.proxy_mode == ProxyMode.TCP

    def test_metadata(self):
        n = NodeSpec(name="api", port=8001, metadata={"env": "dev"})
        assert n.metadata["env"] == "dev"


# -- EdgeSpec --


class TestEdgeSpec:
    def test_valid_edge(self):
        e = EdgeSpec(source="api", target="service")
        assert e.source == "api"
        assert e.target == "service"
        assert e.label == ""

    def test_with_label(self):
        e = EdgeSpec(source="api", target="service", label="http")
        assert e.label == "http"

    def test_no_self_loop(self):
        with pytest.raises(ValidationError, match="Self-loop"):
            EdgeSpec(source="api", target="api")

    def test_frozen(self):
        e = EdgeSpec(source="api", target="service")
        with pytest.raises(ValidationError):
            e.source = "other"


# -- CircuitSpec --


class TestCircuitSpec:
    def test_empty_circuit(self):
        c = CircuitSpec(name="test")
        assert c.name == "test"
        assert c.nodes == []
        assert c.edges == []

    def test_valid_circuit(self, sample_circuit):
        assert sample_circuit.name == "test"
        assert len(sample_circuit.nodes) == 3
        assert len(sample_circuit.edges) == 2

    def test_duplicate_node_names(self):
        with pytest.raises(ValidationError, match="Duplicate node names"):
            CircuitSpec(
                name="bad",
                nodes=[
                    NodeSpec(name="api", port=8001),
                    NodeSpec(name="api", port=8002),
                ],
            )

    def test_duplicate_ports(self):
        with pytest.raises(ValidationError, match="Duplicate ports"):
            CircuitSpec(
                name="bad",
                nodes=[
                    NodeSpec(name="api", port=8001),
                    NodeSpec(name="service", port=8001),
                ],
            )

    def test_edge_references_missing_source(self):
        with pytest.raises(ValidationError, match="not in nodes"):
            CircuitSpec(
                name="bad",
                nodes=[NodeSpec(name="api", port=8001)],
                edges=[EdgeSpec(source="missing", target="api")],
            )

    def test_edge_references_missing_target(self):
        with pytest.raises(ValidationError, match="not in nodes"):
            CircuitSpec(
                name="bad",
                nodes=[NodeSpec(name="api", port=8001)],
                edges=[EdgeSpec(source="api", target="missing")],
            )

    def test_node_by_name(self, sample_circuit):
        node = sample_circuit.node_by_name("api")
        assert node is not None
        assert node.port == 9080

    def test_node_by_name_missing(self, sample_circuit):
        assert sample_circuit.node_by_name("missing") is None

    def test_neighbors(self, sample_circuit):
        assert sample_circuit.neighbors("api") == ["service"]
        assert sample_circuit.neighbors("service") == ["db"]
        assert sample_circuit.neighbors("db") == []

    def test_dependents(self, sample_circuit):
        assert sample_circuit.dependents("api") == []
        assert sample_circuit.dependents("service") == ["api"]
        assert sample_circuit.dependents("db") == ["service"]

    def test_frozen(self, sample_circuit):
        with pytest.raises(ValidationError):
            sample_circuit.name = "other"


# -- ServiceSlot --


class TestServiceSlot:
    def test_defaults(self):
        s = ServiceSlot()
        assert s.command == ""
        assert s.is_mock is True
        assert s.pid == 0

    def test_live_service(self):
        s = ServiceSlot(command="./run.sh", is_mock=False, pid=1234)
        assert s.is_mock is False
        assert s.pid == 1234


# -- AdapterState --


class TestAdapterState:
    def test_defaults(self):
        a = AdapterState(node_name="api")
        assert a.status == NodeStatus.IDLE
        assert a.adapter_pid == 0
        assert a.consecutive_failures == 0
        assert a.last_health_verdict == HealthVerdict.UNKNOWN

    def test_mutable(self):
        a = AdapterState(node_name="api")
        a.status = NodeStatus.ACTIVE
        a.consecutive_failures = 3
        assert a.status == NodeStatus.ACTIVE
        assert a.consecutive_failures == 3


# -- CircuitState --


class TestCircuitState:
    def test_defaults(self):
        s = CircuitState()
        assert s.circuit_name == "default"
        assert s.collapse_level == CollapseLevel.FULL_MOCK
        assert s.live_nodes == []
        assert s.adapters == {}

    def test_with_adapters(self):
        s = CircuitState(
            adapters={"api": AdapterState(node_name="api", status=NodeStatus.ACTIVE)}
        )
        assert s.adapters["api"].status == NodeStatus.ACTIVE


# -- HealthCheck --


class TestHealthCheck:
    def test_healthy(self):
        h = HealthCheck(node_name="api", verdict=HealthVerdict.HEALTHY, latency_ms=1.5)
        assert h.verdict == HealthVerdict.HEALTHY
        assert h.latency_ms == 1.5

    def test_frozen(self):
        h = HealthCheck(node_name="api", verdict=HealthVerdict.HEALTHY)
        with pytest.raises(ValidationError):
            h.verdict = HealthVerdict.UNHEALTHY


# -- SignalRecord --


class TestSignalRecord:
    def test_inbound(self):
        s = SignalRecord(
            node_name="api",
            direction="inbound",
            method="GET",
            path="/health",
            status_code=200,
        )
        assert s.direction == "inbound"
        assert s.method == "GET"

    def test_frozen(self):
        s = SignalRecord(node_name="api", direction="outbound")
        with pytest.raises(ValidationError):
            s.node_name = "other"


# -- CustodianEvent --


class TestCustodianEvent:
    def test_restart(self):
        e = CustodianEvent(
            node_name="api",
            action=CustodianAction.RESTART_SERVICE,
            reason="3 consecutive failures",
            success=True,
        )
        assert e.action == CustodianAction.RESTART_SERVICE
        assert e.success is True


# -- DeploymentTarget --


class TestDeploymentTarget:
    def test_defaults(self):
        t = DeploymentTarget()
        assert t.provider == "local"
        assert t.region == ""

    def test_gcp(self):
        t = DeploymentTarget(
            provider="gcp", region="us-central1", config={"project": "my-project"}
        )
        assert t.provider == "gcp"
        assert t.config["project"] == "my-project"

    def test_frozen(self):
        t = DeploymentTarget()
        with pytest.raises(ValidationError):
            t.provider = "aws"


# -- Enum values --


class TestEnums:
    def test_node_status_values(self):
        assert NodeStatus.IDLE == "idle"
        assert NodeStatus.FAULTED == "faulted"

    def test_proxy_mode_values(self):
        assert ProxyMode.HTTP == "http"
        assert ProxyMode.TCP == "tcp"

    def test_collapse_level_values(self):
        assert CollapseLevel.FULL_MOCK == "full_mock"
        assert CollapseLevel.FULL_LIVE == "full_live"

    def test_health_verdict_values(self):
        assert HealthVerdict.HEALTHY == "healthy"
        assert HealthVerdict.UNKNOWN == "unknown"

    def test_custodian_action_values(self):
        assert CustodianAction.RESTART_SERVICE == "restart_service"
        assert CustodianAction.ESCALATE == "escalate"

    def test_node_role_values(self):
        assert NodeRole.SERVICE == "service"
        assert NodeRole.INGRESS == "ingress"
        assert NodeRole.EGRESS == "egress"


# -- NodeRole on NodeSpec --


class TestNodeRole:
    def test_default_role(self):
        n = NodeSpec(name="api", port=8001)
        assert n.role == NodeRole.SERVICE

    def test_ingress_role(self):
        n = NodeSpec(name="gateway", port=8001, role="ingress")
        assert n.role == NodeRole.INGRESS

    def test_egress_role(self):
        n = NodeSpec(name="stripe", port=8001, role="egress")
        assert n.role == NodeRole.EGRESS


# -- DependencySpec --


class TestDependencySpec:
    def test_valid(self):
        d = DependencySpec(name="payments")
        assert d.name == "payments"
        assert d.expected_api == ""
        assert d.optional is False

    def test_with_expected_api(self):
        d = DependencySpec(name="db", expected_api="specs/db.yaml")
        assert d.expected_api == "specs/db.yaml"

    def test_optional(self):
        d = DependencySpec(name="cache", optional=True)
        assert d.optional is True

    def test_frozen(self):
        d = DependencySpec(name="payments")
        with pytest.raises(ValidationError):
            d.name = "other"

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            DependencySpec(name="")


# -- ServiceManifest --


class TestServiceManifest:
    def test_minimal(self):
        m = ServiceManifest(name="api")
        assert m.name == "api"
        assert m.version == "0.0.0"
        assert m.role == NodeRole.SERVICE
        assert m.dependencies == []
        assert m.port == 0

    def test_full(self):
        m = ServiceManifest(
            name="payments",
            version="2.0.0",
            api_spec="specs/api.yaml",
            mock_spec="specs/mock.yaml",
            command="./run.sh",
            port=8080,
            proxy_mode="tcp",
            role="egress",
            dependencies=[DependencySpec(name="db")],
            metadata={"team": "platform"},
        )
        assert m.version == "2.0.0"
        assert m.proxy_mode == "tcp"
        assert m.role == NodeRole.EGRESS
        assert len(m.dependencies) == 1
        assert m.metadata["team"] == "platform"

    def test_frozen(self):
        m = ServiceManifest(name="api")
        with pytest.raises(ValidationError):
            m.name = "other"

    def test_name_validation(self):
        with pytest.raises(ValidationError):
            ServiceManifest(name="Bad-Name")
        with pytest.raises(ValidationError):
            ServiceManifest(name="")
        with pytest.raises(ValidationError):
            ServiceManifest(name="1starts-with-num")


# -- Routing Models --


class TestRoutingStrategy:
    def test_values(self):
        assert RoutingStrategy.SINGLE == "single"
        assert RoutingStrategy.WEIGHTED == "weighted"
        assert RoutingStrategy.HEADER == "header"
        assert RoutingStrategy.CANARY == "canary"


class TestRoutingTarget:
    def test_valid(self):
        t = RoutingTarget(name="a", port=8001)
        assert t.name == "a"
        assert t.host == "127.0.0.1"
        assert t.port == 8001
        assert t.weight == 100

    def test_custom_weight(self):
        t = RoutingTarget(name="b", port=8002, weight=30)
        assert t.weight == 30

    def test_frozen(self):
        t = RoutingTarget(name="a", port=8001)
        with pytest.raises(ValidationError):
            t.name = "other"


class TestRoutingRule:
    def test_valid(self):
        r = RoutingRule(header="X-Cohort", value="beta", target="b")
        assert r.header == "X-Cohort"
        assert r.value == "beta"
        assert r.target == "b"

    def test_frozen(self):
        r = RoutingRule(header="X-Cohort", value="beta", target="b")
        with pytest.raises(ValidationError):
            r.header = "other"


class TestRoutingConfig:
    def test_weighted_valid(self):
        cfg = RoutingConfig(
            strategy=RoutingStrategy.WEIGHTED,
            targets=[
                RoutingTarget(name="a", port=8001, weight=80),
                RoutingTarget(name="b", port=8002, weight=20),
            ],
        )
        assert cfg.strategy == RoutingStrategy.WEIGHTED
        assert len(cfg.targets) == 2

    def test_weighted_bad_sum(self):
        with pytest.raises(ValidationError, match="sum to 100"):
            RoutingConfig(
                strategy=RoutingStrategy.WEIGHTED,
                targets=[
                    RoutingTarget(name="a", port=8001, weight=80),
                    RoutingTarget(name="b", port=8002, weight=30),
                ],
            )

    def test_canary_valid(self):
        cfg = RoutingConfig(
            strategy=RoutingStrategy.CANARY,
            targets=[
                RoutingTarget(name="stable", port=8001, weight=90),
                RoutingTarget(name="canary", port=8002, weight=10),
            ],
        )
        assert cfg.strategy == RoutingStrategy.CANARY

    def test_header_valid(self):
        cfg = RoutingConfig(
            strategy=RoutingStrategy.HEADER,
            targets=[
                RoutingTarget(name="a", port=8001),
                RoutingTarget(name="b", port=8002),
            ],
            rules=[RoutingRule(header="X-Cohort", value="beta", target="b")],
            default_target="a",
        )
        assert cfg.strategy == RoutingStrategy.HEADER
        assert cfg.default_target == "a"

    def test_header_requires_rules(self):
        with pytest.raises(ValidationError, match="requires at least one rule"):
            RoutingConfig(
                strategy=RoutingStrategy.HEADER,
                targets=[RoutingTarget(name="a", port=8001)],
                default_target="a",
            )

    def test_header_requires_default(self):
        with pytest.raises(ValidationError, match="requires a default_target"):
            RoutingConfig(
                strategy=RoutingStrategy.HEADER,
                targets=[RoutingTarget(name="a", port=8001)],
                rules=[RoutingRule(header="X-Cohort", value="beta", target="a")],
            )

    def test_duplicate_target_names(self):
        with pytest.raises(ValidationError, match="Duplicate target names"):
            RoutingConfig(
                strategy=RoutingStrategy.WEIGHTED,
                targets=[
                    RoutingTarget(name="a", port=8001, weight=50),
                    RoutingTarget(name="a", port=8002, weight=50),
                ],
            )

    def test_locked(self):
        cfg = RoutingConfig(
            strategy=RoutingStrategy.WEIGHTED,
            targets=[
                RoutingTarget(name="a", port=8001, weight=80),
                RoutingTarget(name="b", port=8002, weight=20),
            ],
            locked=True,
        )
        assert cfg.locked is True

    def test_frozen(self):
        cfg = RoutingConfig(
            strategy=RoutingStrategy.WEIGHTED,
            targets=[
                RoutingTarget(name="a", port=8001, weight=80),
                RoutingTarget(name="b", port=8002, weight=20),
            ],
        )
        with pytest.raises(ValidationError):
            cfg.locked = True
