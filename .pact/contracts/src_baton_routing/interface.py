# === Baton Routing Patterns (src_baton_routing) v1 ===
#  Dependencies: baton.schemas
# Pre-baked routing patterns. Convenience functions that construct RoutingConfig for common use cases including A/B testing, canary deployments, header-based routing, and weighted splits.

# Module invariants:
#   - All functions are pure and idempotent - same inputs always produce same outputs
#   - No validation is performed on input values (ports, percentages, target names)
#   - Percentage calculations assume integer arithmetic (100 - pct)
#   - All functions construct and return new RoutingConfig instances

class RoutingConfig:
    """External type from baton.schemas representing routing configuration"""
    pass

class RoutingTarget:
    """External type from baton.schemas representing a routing target with name, host, port, and optional weight"""
    pass

class RoutingRule:
    """External type from baton.schemas representing a routing rule with header, value, and target"""
    pass

class RoutingStrategy(Enum):
    """External enum from baton.schemas with routing strategy types"""
    WEIGHTED = "WEIGHTED"
    CANARY = "CANARY"
    HEADER = "HEADER"

def ab_split(
    host: str,
    port_a: int,
    port_b: int,
    pct_a: int = 80,
) -> RoutingConfig:
    """
    Two-target weighted split (A/B test). Creates a RoutingConfig with two targets (a and b) where traffic is split according to pct_a percentage.

    Postconditions:
      - Returns RoutingConfig with strategy=WEIGHTED
      - Returns exactly 2 targets named 'a' and 'b'
      - Target 'a' has weight=pct_a
      - Target 'b' has weight=100-pct_a
      - Both targets use the same host
      - Sum of weights equals 100

    Side effects: none
    Idempotent: yes
    """
    ...

def canary(
    host: str,
    port_stable: int,
    port_canary: int,
    canary_pct: int = 10,
) -> RoutingConfig:
    """
    Canary rollout: small percentage to new version. Creates a RoutingConfig with a stable target and a canary target for gradual rollout.

    Postconditions:
      - Returns RoutingConfig with strategy=CANARY
      - Returns exactly 2 targets named 'stable' and 'canary'
      - Target 'stable' has weight=100-canary_pct
      - Target 'canary' has weight=canary_pct
      - Both targets use the same host
      - Sum of weights equals 100

    Side effects: none
    Idempotent: yes
    """
    ...

def header_route(
    targets: list[tuple[str, str, int]],
    header: str,
    rules: list[tuple[str, str]],
    default: str,
) -> RoutingConfig:
    """
    Header-based routing. Creates a RoutingConfig that routes requests based on HTTP header values using specified rules.

    Postconditions:
      - Returns RoutingConfig with strategy=HEADER
      - Returns targets matching the input targets list
      - Returns rules with specified header name and value-target mappings
      - Sets default_target to the specified default value
      - Number of targets equals length of targets input
      - Number of rules equals length of rules input

    Side effects: none
    Idempotent: yes
    """
    ...

def weighted_split(
    targets: list[tuple[str, str, int, int]],
) -> RoutingConfig:
    """
    N-target weighted split. Creates a RoutingConfig with multiple targets where traffic is distributed according to specified weights.

    Postconditions:
      - Returns RoutingConfig with strategy=WEIGHTED
      - Returns targets matching the input targets list with corresponding weights
      - Number of targets equals length of targets input
      - Each target has name, host, port, and weight from corresponding input tuple

    Side effects: none
    Idempotent: yes
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['RoutingConfig', 'RoutingTarget', 'RoutingRule', 'RoutingStrategy', 'ab_split', 'canary', 'header_route', 'weighted_split']
