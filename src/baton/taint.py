"""Taint analysis for data boundary verification.

Seeds synthetic PII-shaped data with unique fingerprints into services,
then detects where those fingerprints appear. If a canary datum crosses
a boundary it shouldn't, that's a TaintViolation.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from baton.state import append_jsonl, read_jsonl

TAINT_FILE = "taint_canaries.jsonl"
VIOLATIONS_FILE = "taint_violations.jsonl"


@dataclass(frozen=True)
class CanaryDatum:
    """A single piece of synthetic data with a traceable fingerprint."""

    fingerprint: str          # 8-char hex string embedded in the value
    category: str             # "ssn", "email", "credit_card", "phone", "name"
    value: str                # The synthetic value containing the fingerprint
    seed_node: str            # Which node this was injected into
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "fingerprint": self.fingerprint,
            "category": self.category,
            "value": self.value,
            "seed_node": self.seed_node,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> CanaryDatum:
        return cls(
            fingerprint=d["fingerprint"],
            category=d["category"],
            value=d["value"],
            seed_node=d["seed_node"],
            created_at=d.get("created_at", ""),
        )


@dataclass(frozen=True)
class TaintViolation:
    """A detected boundary violation."""

    fingerprint: str
    category: str
    seed_node: str           # Where the datum was injected
    observed_node: str       # Where it was detected
    observed_in: str         # "request", "response"
    allowed_nodes: frozenset[str]
    timestamp: str = ""
    trace_id: str = ""
    severity: str = "critical"

    def to_dict(self) -> dict:
        return {
            "fingerprint": self.fingerprint,
            "category": self.category,
            "seed_node": self.seed_node,
            "observed_node": self.observed_node,
            "observed_in": self.observed_in,
            "allowed_nodes": sorted(self.allowed_nodes),
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "severity": self.severity,
        }


class CanaryGenerator:
    """Generates canary data with embedded fingerprints.

    Fingerprints are 8-char hex strings embedded in PII-shaped values:
    - SSN: 555-{fp[0:2]}-{fp[2:6]}  (555 prefix = known fake)
    - Email: canary-{fp}@baton.test
    - Credit card: 4000-0000-{fp[0:4]}-{fp[4:8]} (4000 prefix = test range)
    - Phone: 555-0{fp[0:2]}-{fp[2:6]}
    - Name: Canary_{fp} Testuser
    """

    CATEGORIES = ("ssn", "email", "credit_card", "phone", "name")

    def _make_fingerprint(self) -> str:
        """Generate a unique 8-char hex fingerprint."""
        return secrets.token_hex(4)

    def generate(self, category: str, seed_node: str) -> CanaryDatum:
        """Generate a single canary datum for the given category."""
        fp = self._make_fingerprint()
        now = datetime.now(timezone.utc).isoformat()
        value = self._format_value(category, fp)
        return CanaryDatum(
            fingerprint=fp,
            category=category,
            value=value,
            seed_node=seed_node,
            created_at=now,
        )

    def generate_set(self, seed_node: str) -> list[CanaryDatum]:
        """Generate one canary datum per category for a node."""
        return [self.generate(cat, seed_node) for cat in self.CATEGORIES]

    @staticmethod
    def _format_value(category: str, fp: str) -> str:
        """Format a fingerprint into a PII-shaped value."""
        if category == "ssn":
            return f"555-{fp[0:2]}-{fp[2:6]}"
        elif category == "email":
            return f"canary-{fp}@baton.test"
        elif category == "credit_card":
            return f"4000-0000-{fp[0:4]}-{fp[4:8]}"
        elif category == "phone":
            return f"555-0{fp[0:2]}-{fp[2:6]}"
        elif category == "name":
            return f"Canary_{fp} Testuser"
        else:
            return f"canary-{fp}"


class TaintRegistry:
    """Tracks all active canary data and where it should/shouldn't appear.

    Each canary datum has a set of allowed nodes -- the seed node plus
    its topological neighbors. Detecting a fingerprint outside this set
    constitutes a TaintViolation.
    """

    def __init__(self, project_dir: Path | None = None):
        self._data: dict[str, CanaryDatum] = {}        # fingerprint -> datum
        self._boundaries: dict[str, frozenset[str]] = {}  # fingerprint -> allowed_nodes
        self._violations: list[TaintViolation] = []
        self._project_dir = project_dir

    @property
    def violations(self) -> list[TaintViolation]:
        return list(self._violations)

    def register(self, datum: CanaryDatum, allowed_nodes: set[str]) -> None:
        """Register a canary datum with its allowed boundary set."""
        self._data[datum.fingerprint] = datum
        self._boundaries[datum.fingerprint] = frozenset(allowed_nodes)
        if self._project_dir:
            append_jsonl(self._project_dir, TAINT_FILE, datum.to_dict())

    def check_fingerprint(
        self,
        fingerprint: str,
        observed_node: str,
        observed_in: str = "response",
        trace_id: str = "",
    ) -> TaintViolation | None:
        """Check if observing a fingerprint at this node is a violation.

        Returns a TaintViolation if the fingerprint is outside its allowed set,
        or None if it's within bounds (or unknown).
        """
        if fingerprint not in self._data:
            return None

        datum = self._data[fingerprint]
        allowed = self._boundaries.get(fingerprint, frozenset())

        if observed_node in allowed:
            return None

        violation = TaintViolation(
            fingerprint=fingerprint,
            category=datum.category,
            seed_node=datum.seed_node,
            observed_node=observed_node,
            observed_in=observed_in,
            allowed_nodes=allowed,
            timestamp=datetime.now(timezone.utc).isoformat(),
            trace_id=trace_id,
        )
        self._violations.append(violation)
        if self._project_dir:
            append_jsonl(self._project_dir, VIOLATIONS_FILE, violation.to_dict())
        return violation

    def all_fingerprints(self) -> set[str]:
        """Return all registered fingerprints."""
        return set(self._data.keys())

    def all_canaries(self) -> list[CanaryDatum]:
        """Return all registered canary data."""
        return list(self._data.values())

    def drain_violations(self) -> list[TaintViolation]:
        """Return and clear the violation buffer."""
        drained = self._violations[:]
        self._violations.clear()
        return drained

    def clear(self) -> None:
        """Remove all canary data and violations."""
        self._data.clear()
        self._boundaries.clear()
        self._violations.clear()


class TaintScanner:
    """Scans request/response bytes for canary fingerprints.

    Uses a single compiled regex of all active fingerprints for
    efficient one-pass scanning. Designed to be low-overhead.
    """

    def __init__(self, registry: TaintRegistry):
        self._registry = registry
        self._pattern: re.Pattern[str] | None = None

    def rebuild_pattern(self) -> None:
        """Rebuild the regex pattern from current registry fingerprints."""
        fps = self._registry.all_fingerprints()
        if fps:
            # Sort by length descending so longer patterns match first
            sorted_fps = sorted(fps, key=len, reverse=True)
            self._pattern = re.compile("|".join(re.escape(fp) for fp in sorted_fps))
        else:
            self._pattern = None

    def scan(
        self,
        data: bytes,
        node_name: str,
        direction: str,
        trace_id: str = "",
    ) -> list[TaintViolation]:
        """Scan bytes for canary fingerprints. Returns any violations found.

        Args:
            data: The request or response bytes to scan
            node_name: Which node this data was observed at
            direction: "request" or "response"
            trace_id: Optional trace ID for correlation

        Returns:
            List of TaintViolation objects for any boundary crossings
        """
        if self._pattern is None:
            return []

        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return []

        violations = []
        seen_fps: set[str] = set()

        for match in self._pattern.finditer(text):
            fp = match.group()
            if fp in seen_fps:
                continue
            seen_fps.add(fp)

            violation = self._registry.check_fingerprint(
                fp, node_name, observed_in=direction, trace_id=trace_id,
            )
            if violation is not None:
                violations.append(violation)

        return violations
