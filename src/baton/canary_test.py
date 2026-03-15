"""Canary injection test mode.

Orchestrates a soak test: seeds canary data, runs circuit for a duration,
and reports taint violations. Optionally fetches corpus from Arbiter.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from baton.taint import CanaryGenerator, TaintRegistry, TaintScanner, TaintViolation

logger = logging.getLogger(__name__)


@dataclass
class CanaryTestResult:
    """Result of a canary soak test."""
    run_id: str = ""
    duration_s: float = 0.0
    canaries_seeded: int = 0
    violations_found: int = 0
    violations: list[dict] = field(default_factory=list)
    tiers_tested: list[str] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "duration_s": round(self.duration_s, 1),
            "canaries_seeded": self.canaries_seeded,
            "violations_found": self.violations_found,
            "violations": self.violations,
            "tiers_tested": self.tiers_tested,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    def format_report(self) -> str:
        lines = [
            f"Canary Test Report",
            f"=" * 40,
            f"Run ID:           {self.run_id}",
            f"Duration:         {self.duration_s:.1f}s",
            f"Canaries seeded:  {self.canaries_seeded}",
            f"Tiers tested:     {', '.join(self.tiers_tested) or 'all'}",
            f"Violations found: {self.violations_found}",
        ]
        if self.violations:
            lines.append("")
            for v in self.violations:
                lines.append(
                    f"  [{v.get('severity', 'critical').upper()}] "
                    f"{v.get('category', '')} fingerprint {v.get('fingerprint', '')} "
                    f"leaked from {v.get('seed_node', '')} to {v.get('observed_node', '')}"
                )
        return "\n".join(lines)


async def run_canary_test(
    project_dir: Path,
    circuit_nodes: list[str],
    circuit_neighbors: dict[str, set[str]],
    duration_s: float = 60.0,
    tiers: list[str] | None = None,
    run_id: str = "",
    arbiter_client=None,
) -> CanaryTestResult:
    """Run a canary soak test.

    Seeds canary data into the circuit, waits for the specified duration,
    then collects and reports any taint violations.

    Args:
        project_dir: Baton project directory
        circuit_nodes: List of node names in the circuit
        circuit_neighbors: {node: set of allowed neighbor nodes}
        duration_s: How long to run the soak test
        tiers: Classification tiers to test (e.g. ["PII", "FINANCIAL"])
        run_id: Optional run identifier
        arbiter_client: Optional ArbiterClient for corpus/results
    """
    import secrets
    if not run_id:
        run_id = secrets.token_hex(8)

    result = CanaryTestResult(
        run_id=run_id,
        tiers_tested=tiers or [],
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    registry = TaintRegistry(project_dir=project_dir)
    scanner = TaintScanner(registry)

    # Try to get corpus from Arbiter if available
    arbiter_corpus = []
    if arbiter_client and tiers:
        arbiter_corpus = await arbiter_client.get_canary_corpus(tiers, run_id)

    # Seed canary data
    generator = CanaryGenerator()
    categories = None
    if tiers:
        # Map tiers to canary categories
        tier_to_cat = {
            "PII": ["ssn", "email", "phone", "name"],
            "FINANCIAL": ["credit_card"],
        }
        categories = set()
        for tier in tiers:
            cats = tier_to_cat.get(tier.upper(), [])
            categories.update(cats)
        if not categories:
            categories = None  # Fall back to all

    for node_name in circuit_nodes:
        if categories:
            canaries = [generator.generate(cat, node_name) for cat in categories]
        else:
            canaries = generator.generate_set(node_name)

        allowed = {node_name} | circuit_neighbors.get(node_name, set())
        for datum in canaries:
            registry.register(datum, allowed)
            result.canaries_seeded += 1

    scanner.rebuild_pattern()
    logger.info(f"Canary test {run_id}: seeded {result.canaries_seeded} canaries, soaking for {duration_s}s")

    # Soak: wait for the specified duration
    await asyncio.sleep(duration_s)

    # Collect violations
    violations = registry.drain_violations()
    result.violations_found = len(violations)
    result.violations = [v.to_dict() for v in violations]
    result.completed_at = datetime.now(timezone.utc).isoformat()
    result.duration_s = duration_s

    # Try to get results from Arbiter
    if arbiter_client:
        arbiter_results = await arbiter_client.get_canary_results(run_id)
        if arbiter_results:
            # Merge Arbiter-detected violations
            arbiter_violations = arbiter_results.get("violations", [])
            result.violations.extend(arbiter_violations)
            result.violations_found += len(arbiter_violations)

    return result
