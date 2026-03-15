"""Tests for taint analysis module."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from baton.schemas import TaintConfig
from baton.taint import (
    TAINT_FILE,
    VIOLATIONS_FILE,
    CanaryDatum,
    CanaryGenerator,
    TaintRegistry,
    TaintScanner,
    TaintViolation,
)


class TestCanaryGenerator:
    def test_generate_produces_8_char_hex_fingerprint(self):
        gen = CanaryGenerator()
        datum = gen.generate("email", "api")
        assert len(datum.fingerprint) == 8
        assert re.fullmatch(r"[0-9a-f]{8}", datum.fingerprint)

    def test_generate_embeds_fingerprint_in_value(self):
        gen = CanaryGenerator()
        for category in CanaryGenerator.CATEGORIES:
            datum = gen.generate(category, "node-a")
            fp = datum.fingerprint
            if category in ("email", "name"):
                # Full 8-char fingerprint embedded verbatim
                assert fp in datum.value
            elif category == "credit_card":
                # fp[0:4] and fp[4:8] split across segments
                assert fp[0:4] in datum.value
                assert fp[4:8] in datum.value
            else:
                # SSN and phone: fp[0:2] and fp[2:6]
                assert fp[0:2] in datum.value
                assert fp[2:6] in datum.value

    def test_generate_set_produces_one_per_category(self):
        gen = CanaryGenerator()
        canaries = gen.generate_set("node-a")
        assert len(canaries) == 5
        categories = {d.category for d in canaries}
        assert categories == set(CanaryGenerator.CATEGORIES)

    def test_generate_set_unique_fingerprints(self):
        gen = CanaryGenerator()
        canaries = gen.generate_set("node-a")
        fps = [d.fingerprint for d in canaries]
        assert len(set(fps)) == 5

    def test_ssn_format(self):
        gen = CanaryGenerator()
        datum = gen.generate("ssn", "api")
        assert re.fullmatch(r"555-[0-9a-f]{2}-[0-9a-f]{4}", datum.value)

    def test_email_format(self):
        gen = CanaryGenerator()
        datum = gen.generate("email", "api")
        assert re.fullmatch(r"canary-[0-9a-f]{8}@baton\.test", datum.value)

    def test_credit_card_format(self):
        gen = CanaryGenerator()
        datum = gen.generate("credit_card", "api")
        assert re.fullmatch(r"4000-0000-[0-9a-f]{4}-[0-9a-f]{4}", datum.value)

    def test_phone_format(self):
        gen = CanaryGenerator()
        datum = gen.generate("phone", "api")
        assert re.fullmatch(r"555-0[0-9a-f]{2}-[0-9a-f]{4}", datum.value)

    def test_name_format(self):
        gen = CanaryGenerator()
        datum = gen.generate("name", "api")
        assert re.fullmatch(r"Canary_[0-9a-f]{8} Testuser", datum.value)

    def test_generate_populates_seed_node(self):
        gen = CanaryGenerator()
        datum = gen.generate("email", "my-service")
        assert datum.seed_node == "my-service"

    def test_generate_populates_created_at(self):
        gen = CanaryGenerator()
        datum = gen.generate("email", "api")
        assert datum.created_at != ""

    def test_generate_populates_category(self):
        gen = CanaryGenerator()
        datum = gen.generate("phone", "api")
        assert datum.category == "phone"


class TestTaintRegistry:
    def test_register_stores_datum(self):
        reg = TaintRegistry()
        gen = CanaryGenerator()
        datum = gen.generate("email", "api")
        reg.register(datum, {"api", "service"})
        assert datum.fingerprint in reg.all_fingerprints()

    def test_check_fingerprint_returns_none_for_allowed_node(self):
        reg = TaintRegistry()
        gen = CanaryGenerator()
        datum = gen.generate("email", "api")
        reg.register(datum, {"api", "service"})
        result = reg.check_fingerprint(datum.fingerprint, "api", "response")
        assert result is None

    def test_check_fingerprint_returns_violation_for_disallowed_node(self):
        reg = TaintRegistry()
        gen = CanaryGenerator()
        datum = gen.generate("email", "api")
        reg.register(datum, {"api"})
        result = reg.check_fingerprint(datum.fingerprint, "db", "response", "trace-1")
        assert isinstance(result, TaintViolation)
        assert result.fingerprint == datum.fingerprint
        assert result.seed_node == "api"
        assert result.observed_node == "db"
        assert result.observed_in == "response"
        assert result.trace_id == "trace-1"
        assert "api" in result.allowed_nodes
        assert "db" not in result.allowed_nodes

    def test_check_fingerprint_returns_none_for_unknown(self):
        reg = TaintRegistry()
        result = reg.check_fingerprint("deadbeef", "api", "response")
        assert result is None

    def test_all_fingerprints_returns_registered_set(self):
        reg = TaintRegistry()
        gen = CanaryGenerator()
        d1 = gen.generate("email", "api")
        d2 = gen.generate("ssn", "api")
        reg.register(d1, {"api"})
        reg.register(d2, {"api"})
        assert reg.all_fingerprints() == {d1.fingerprint, d2.fingerprint}

    def test_all_canaries_returns_registered_data(self):
        reg = TaintRegistry()
        gen = CanaryGenerator()
        d1 = gen.generate("email", "api")
        reg.register(d1, {"api"})
        canaries = reg.all_canaries()
        assert len(canaries) == 1
        assert canaries[0].fingerprint == d1.fingerprint

    def test_drain_violations_returns_and_clears(self):
        reg = TaintRegistry()
        gen = CanaryGenerator()
        datum = gen.generate("email", "api")
        reg.register(datum, {"api"})
        reg.check_fingerprint(datum.fingerprint, "db", "response")
        assert len(reg.violations) == 1

        drained = reg.drain_violations()
        assert len(drained) == 1
        assert drained[0].observed_node == "db"
        assert len(reg.violations) == 0

    def test_clear_removes_all_data(self):
        reg = TaintRegistry()
        gen = CanaryGenerator()
        datum = gen.generate("email", "api")
        reg.register(datum, {"api"})
        reg.check_fingerprint(datum.fingerprint, "db", "response")
        reg.clear()
        assert reg.all_fingerprints() == set()
        assert reg.all_canaries() == []
        assert reg.violations == []

    def test_persistence_register_writes_canary_jsonl(self, project_dir: Path):
        baton_dir = project_dir / ".baton"
        baton_dir.mkdir()
        reg = TaintRegistry(project_dir=project_dir)
        gen = CanaryGenerator()
        datum = gen.generate("email", "api")
        reg.register(datum, {"api"})
        canary_file = baton_dir / TAINT_FILE
        assert canary_file.exists()
        lines = canary_file.read_text().strip().splitlines()
        assert len(lines) == 1
        assert datum.fingerprint in lines[0]

    def test_persistence_violation_writes_jsonl(self, project_dir: Path):
        baton_dir = project_dir / ".baton"
        baton_dir.mkdir()
        reg = TaintRegistry(project_dir=project_dir)
        gen = CanaryGenerator()
        datum = gen.generate("email", "api")
        reg.register(datum, {"api"})
        reg.check_fingerprint(datum.fingerprint, "db", "response")
        violations_file = baton_dir / VIOLATIONS_FILE
        assert violations_file.exists()
        lines = violations_file.read_text().strip().splitlines()
        assert len(lines) == 1
        assert "db" in lines[0]

    def test_violation_severity_defaults_to_critical(self):
        reg = TaintRegistry()
        gen = CanaryGenerator()
        datum = gen.generate("ssn", "api")
        reg.register(datum, {"api"})
        v = reg.check_fingerprint(datum.fingerprint, "external", "response")
        assert v is not None
        assert v.severity == "critical"


class TestTaintScanner:
    def test_scan_finds_fingerprint_and_returns_violation(self):
        reg = TaintRegistry()
        gen = CanaryGenerator()
        datum = gen.generate("email", "api")
        reg.register(datum, {"api"})

        scanner = TaintScanner(reg)
        scanner.rebuild_pattern()

        payload = f'{{"email": "{datum.value}"}}'.encode()
        violations = scanner.scan(payload, "db", "response", "t-1")
        assert len(violations) == 1
        assert violations[0].fingerprint == datum.fingerprint
        assert violations[0].observed_node == "db"
        assert violations[0].observed_in == "response"

    def test_scan_returns_empty_for_allowed_node(self):
        reg = TaintRegistry()
        gen = CanaryGenerator()
        datum = gen.generate("email", "api")
        reg.register(datum, {"api", "service"})

        scanner = TaintScanner(reg)
        scanner.rebuild_pattern()

        payload = f'{{"email": "{datum.value}"}}'.encode()
        violations = scanner.scan(payload, "api", "response")
        assert violations == []

    def test_scan_returns_empty_when_no_fingerprints_registered(self):
        reg = TaintRegistry()
        scanner = TaintScanner(reg)
        scanner.rebuild_pattern()

        violations = scanner.scan(b"some random data", "api", "response")
        assert violations == []

    def test_scan_handles_multiple_fingerprints_in_same_data(self):
        reg = TaintRegistry()
        gen = CanaryGenerator()
        d1 = gen.generate("email", "api")
        d2 = gen.generate("name", "api")
        reg.register(d1, {"api"})
        reg.register(d2, {"api"})

        scanner = TaintScanner(reg)
        scanner.rebuild_pattern()

        # Both email and name embed the full 8-char fingerprint
        payload = f"{d1.value} {d2.value}".encode()
        violations = scanner.scan(payload, "db", "response")
        assert len(violations) == 2
        found_fps = {v.fingerprint for v in violations}
        assert found_fps == {d1.fingerprint, d2.fingerprint}

    def test_rebuild_pattern_updates_after_new_registrations(self):
        reg = TaintRegistry()
        gen = CanaryGenerator()
        d1 = gen.generate("email", "api")
        reg.register(d1, {"api"})

        scanner = TaintScanner(reg)
        scanner.rebuild_pattern()

        # Register a new one after the first rebuild
        d2 = gen.generate("name", "api")
        reg.register(d2, {"api"})
        scanner.rebuild_pattern()

        # Use d2's value which embeds the full fingerprint
        payload = f"{d2.value}".encode()
        violations = scanner.scan(payload, "db", "response")
        assert len(violations) == 1
        assert violations[0].fingerprint == d2.fingerprint

    def test_scan_direction_request(self):
        reg = TaintRegistry()
        gen = CanaryGenerator()
        datum = gen.generate("email", "api")
        reg.register(datum, {"api"})

        scanner = TaintScanner(reg)
        scanner.rebuild_pattern()

        payload = f"{datum.value}".encode()
        violations = scanner.scan(payload, "db", "request", "t-req")
        assert len(violations) == 1
        assert violations[0].observed_in == "request"

    def test_scan_direction_response(self):
        reg = TaintRegistry()
        gen = CanaryGenerator()
        datum = gen.generate("email", "api")
        reg.register(datum, {"api"})

        scanner = TaintScanner(reg)
        scanner.rebuild_pattern()

        payload = f"{datum.value}".encode()
        violations = scanner.scan(payload, "db", "response", "t-resp")
        assert len(violations) == 1
        assert violations[0].observed_in == "response"

    def test_scan_no_duplicate_violations_for_repeated_fingerprint(self):
        """Same fingerprint appearing multiple times in data produces one violation."""
        reg = TaintRegistry()
        gen = CanaryGenerator()
        datum = gen.generate("email", "api")
        reg.register(datum, {"api"})

        scanner = TaintScanner(reg)
        scanner.rebuild_pattern()

        payload = f"{datum.value} {datum.value} {datum.value}".encode()
        violations = scanner.scan(payload, "db", "response")
        assert len(violations) == 1

    def test_scan_without_rebuild_returns_empty(self):
        """Scanner with no pattern compiled should return empty."""
        reg = TaintRegistry()
        gen = CanaryGenerator()
        datum = gen.generate("email", "api")
        reg.register(datum, {"api"})

        scanner = TaintScanner(reg)
        # deliberately skip rebuild_pattern()
        payload = f"{datum.value}".encode()
        violations = scanner.scan(payload, "db", "response")
        assert violations == []


class TestTaintConfig:
    def test_defaults(self):
        config = TaintConfig()
        assert config.enabled is False
        assert config.scan_requests is True
        assert config.scan_responses is True
        assert config.categories == ["ssn", "email", "credit_card", "phone", "name"]

    def test_custom_categories(self):
        config = TaintConfig(categories=["email", "ssn"])
        assert config.categories == ["email", "ssn"]

    def test_enable(self):
        config = TaintConfig(enabled=True)
        assert config.enabled is True

    def test_frozen(self):
        config = TaintConfig()
        with pytest.raises(Exception):
            config.enabled = True  # type: ignore[misc]


class TestTaintIntegration:
    def test_full_flow_generate_register_scan_violation(self):
        """End-to-end: generate canary, register, scan at wrong node, get violation."""
        gen = CanaryGenerator()
        reg = TaintRegistry()
        scanner = TaintScanner(reg)

        # Generate canaries for api node
        canaries = gen.generate_set("api")
        for datum in canaries:
            reg.register(datum, {"api", "service"})

        scanner.rebuild_pattern()

        # Simulate data leaking -- include raw fingerprints so the scanner
        # can detect all categories (some formats like SSN only embed a
        # partial fingerprint, so the scanner wouldn't find them via value alone)
        leaked = " ".join(d.fingerprint for d in canaries)
        violations = scanner.scan(leaked.encode(), "external-db", "response", "trace-42")

        assert len(violations) == 5
        for v in violations:
            assert v.seed_node == "api"
            assert v.observed_node == "external-db"
            assert v.observed_in == "response"
            assert v.trace_id == "trace-42"
            assert "api" in v.allowed_nodes
            assert "service" in v.allowed_nodes
            assert "external-db" not in v.allowed_nodes

        # Verify registry recorded the violations
        drained = reg.drain_violations()
        assert len(drained) == 5
        assert reg.violations == []

    def test_full_flow_no_violation_within_boundary(self):
        """Data seen at allowed node should produce no violations."""
        gen = CanaryGenerator()
        reg = TaintRegistry()
        scanner = TaintScanner(reg)

        canaries = gen.generate_set("api")
        for datum in canaries:
            reg.register(datum, {"api", "service"})

        scanner.rebuild_pattern()

        payload = " ".join(d.fingerprint for d in canaries)
        violations = scanner.scan(payload.encode(), "service", "response")
        assert violations == []
        assert reg.violations == []

    def test_full_flow_with_persistence(self, project_dir: Path):
        """Full flow with JSONL persistence."""
        baton_dir = project_dir / ".baton"
        baton_dir.mkdir()

        gen = CanaryGenerator()
        reg = TaintRegistry(project_dir=project_dir)
        scanner = TaintScanner(reg)

        datum = gen.generate("email", "api")
        reg.register(datum, {"api"})
        scanner.rebuild_pattern()

        violations = scanner.scan(datum.value.encode(), "db", "response")
        assert len(violations) == 1

        # Verify both files were written
        assert (baton_dir / TAINT_FILE).exists()
        assert (baton_dir / VIOLATIONS_FILE).exists()
