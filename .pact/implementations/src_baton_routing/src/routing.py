"""Pre-baked routing patterns.

Convenience functions that construct RoutingConfig for common use cases.
"""

from __future__ import annotations

from baton.schemas import (
    RoutingConfig,
    RoutingRule,
    RoutingStrategy,
    RoutingTarget,
)


def ab_split(
    host: str,
    port_a: int,
    port_b: int,
    pct_a: int = 80,
) -> RoutingConfig:
    """Two-target weighted split (A/B test)."""
    return RoutingConfig(
        strategy=RoutingStrategy.WEIGHTED,
        targets=[
            RoutingTarget(name="a", host=host, port=port_a, weight=pct_a),
            RoutingTarget(name="b", host=host, port=port_b, weight=100 - pct_a),
        ],
    )


def canary(
    host: str,
    port_stable: int,
    port_canary: int,
    canary_pct: int = 10,
) -> RoutingConfig:
    """Canary rollout: small percentage to new version."""
    return RoutingConfig(
        strategy=RoutingStrategy.CANARY,
        targets=[
            RoutingTarget(name="stable", host=host, port=port_stable, weight=100 - canary_pct),
            RoutingTarget(name="canary", host=host, port=port_canary, weight=canary_pct),
        ],
    )


def header_route(
    targets: list[tuple[str, str, int]],
    header: str,
    rules: list[tuple[str, str]],
    default: str,
) -> RoutingConfig:
    """Header-based routing.

    Args:
        targets: List of (name, host, port) tuples.
        header: Header name to match on.
        rules: List of (header_value, target_name) tuples.
        default: Name of the default target.
    """
    return RoutingConfig(
        strategy=RoutingStrategy.HEADER,
        targets=[
            RoutingTarget(name=name, host=host, port=port)
            for name, host, port in targets
        ],
        rules=[
            RoutingRule(header=header, value=value, target=target)
            for value, target in rules
        ],
        default_target=default,
    )


def weighted_split(
    targets: list[tuple[str, str, int, int]],
) -> RoutingConfig:
    """N-target weighted split.

    Args:
        targets: List of (name, host, port, weight) tuples.
    """
    return RoutingConfig(
        strategy=RoutingStrategy.WEIGHTED,
        targets=[
            RoutingTarget(name=name, host=host, port=port, weight=weight)
            for name, host, port, weight in targets
        ],
    )
