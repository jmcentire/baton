"""Tests for pre-baked routing patterns."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from baton.routing import ab_split, canary, header_route, weighted_split
from baton.schemas import RoutingStrategy


class TestAbSplit:
    def test_default_split(self):
        cfg = ab_split("127.0.0.1", 8001, 8002)
        assert cfg.strategy == RoutingStrategy.WEIGHTED
        assert len(cfg.targets) == 2
        assert cfg.targets[0].name == "a"
        assert cfg.targets[0].port == 8001
        assert cfg.targets[0].weight == 80
        assert cfg.targets[1].name == "b"
        assert cfg.targets[1].port == 8002
        assert cfg.targets[1].weight == 20

    def test_custom_split(self):
        cfg = ab_split("127.0.0.1", 8001, 8002, pct_a=60)
        assert cfg.targets[0].weight == 60
        assert cfg.targets[1].weight == 40

    def test_invalid_split(self):
        with pytest.raises(ValidationError):
            ab_split("127.0.0.1", 8001, 8002, pct_a=110)


class TestCanary:
    def test_default_canary(self):
        cfg = canary("127.0.0.1", 8001, 8002)
        assert cfg.strategy == RoutingStrategy.CANARY
        assert len(cfg.targets) == 2
        assert cfg.targets[0].name == "stable"
        assert cfg.targets[0].weight == 90
        assert cfg.targets[1].name == "canary"
        assert cfg.targets[1].weight == 10

    def test_custom_canary(self):
        cfg = canary("127.0.0.1", 8001, 8002, canary_pct=5)
        assert cfg.targets[0].weight == 95
        assert cfg.targets[1].weight == 5


class TestHeaderRoute:
    def test_basic(self):
        cfg = header_route(
            targets=[("a", "127.0.0.1", 8001), ("b", "127.0.0.1", 8002)],
            header="X-Cohort",
            rules=[("beta", "b")],
            default="a",
        )
        assert cfg.strategy == RoutingStrategy.HEADER
        assert len(cfg.targets) == 2
        assert len(cfg.rules) == 1
        assert cfg.rules[0].header == "X-Cohort"
        assert cfg.rules[0].value == "beta"
        assert cfg.rules[0].target == "b"
        assert cfg.default_target == "a"

    def test_multiple_rules(self):
        cfg = header_route(
            targets=[
                ("a", "127.0.0.1", 8001),
                ("b", "127.0.0.1", 8002),
                ("c", "127.0.0.1", 8003),
            ],
            header="X-Version",
            rules=[("v2", "b"), ("v3", "c")],
            default="a",
        )
        assert len(cfg.rules) == 2


class TestWeightedSplit:
    def test_three_way(self):
        cfg = weighted_split([
            ("a", "127.0.0.1", 8001, 50),
            ("b", "127.0.0.1", 8002, 30),
            ("c", "127.0.0.1", 8003, 20),
        ])
        assert cfg.strategy == RoutingStrategy.WEIGHTED
        assert len(cfg.targets) == 3
        assert sum(t.weight for t in cfg.targets) == 100

    def test_invalid_weights(self):
        with pytest.raises(ValidationError, match="sum to 100"):
            weighted_split([
                ("a", "127.0.0.1", 8001, 50),
                ("b", "127.0.0.1", 8002, 30),
            ])
