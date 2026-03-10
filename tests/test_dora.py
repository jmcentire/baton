"""Tests for DORA metrics derivation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from baton.dora import (
    DORAMetrics,
    EventType,
    compute_dora,
    format_dora,
    record_event,
    _compute_change_failure_rate,
    _compute_deployment_frequency,
    _compute_lead_times,
    _compute_mttr,
    _filter_window,
    _parse_ts,
)
from baton.state import append_jsonl, ensure_baton_dir


def _ts(minutes_ago: int = 0) -> str:
    """Generate ISO timestamp N minutes in the past."""
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return dt.isoformat()


class TestParseTimestamp:
    def test_valid_iso(self):
        result = _parse_ts("2026-03-08T12:00:00+00:00")
        assert result is not None
        assert result.year == 2026

    def test_naive_gets_utc(self):
        result = _parse_ts("2026-03-08T12:00:00")
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_empty_string(self):
        assert _parse_ts("") is None

    def test_invalid(self):
        assert _parse_ts("not-a-date") is None


class TestFilterWindow:
    def test_filters_old_events(self):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        events = [
            {"timestamp": _ts(30)},    # 30 min ago -- in window
            {"timestamp": _ts(120)},   # 2 hours ago -- out of window
        ]
        result = _filter_window(events, cutoff)
        assert len(result) == 1

    def test_empty_list(self):
        cutoff = datetime.now(timezone.utc)
        assert _filter_window([], cutoff) == []


class TestDeploymentFrequency:
    def test_basic_frequency(self):
        events = [
            {"timestamp": _ts(0)},
            {"timestamp": _ts(60)},
            {"timestamp": _ts(120)},
        ]
        freq, count = _compute_deployment_frequency(events, window_hours=24)
        assert count == 3
        assert abs(freq - 3.0) < 0.01  # 3 per day

    def test_empty(self):
        freq, count = _compute_deployment_frequency([], window_hours=24)
        assert count == 0
        assert freq == 0.0

    def test_week_window(self):
        events = [{"timestamp": _ts(i * 60)} for i in range(7)]
        freq, count = _compute_deployment_frequency(events, window_hours=168)
        assert count == 7
        assert abs(freq - 1.0) < 0.01  # 7 per week = 1 per day


class TestLeadTimes:
    def test_basic_lead_time(self):
        deploy_ts = _ts(10)
        signal_ts = _ts(9)  # 1 minute after deploy

        deploys = [{"timestamp": deploy_ts, "node_name": "api"}]
        signals = [
            {"timestamp": signal_ts, "node_name": "api", "status_code": 200},
        ]
        result = _compute_lead_times(deploys, signals)
        assert len(result) == 1
        assert 50 < result[0] < 70  # ~60 seconds

    def test_ignores_error_signals(self):
        deploy_ts = _ts(10)
        error_ts = _ts(9)
        ok_ts = _ts(8)

        deploys = [{"timestamp": deploy_ts, "node_name": "api"}]
        signals = [
            {"timestamp": error_ts, "node_name": "api", "status_code": 500},
            {"timestamp": ok_ts, "node_name": "api", "status_code": 200},
        ]
        result = _compute_lead_times(deploys, signals)
        assert len(result) == 1
        # Should pick the 200, not the 500
        assert result[0] > 100  # ~120 seconds (skipped the error)

    def test_ignores_different_node(self):
        deploy_ts = _ts(10)
        signal_ts = _ts(9)

        deploys = [{"timestamp": deploy_ts, "node_name": "api"}]
        signals = [
            {"timestamp": signal_ts, "node_name": "db", "status_code": 200},
        ]
        result = _compute_lead_times(deploys, signals)
        assert len(result) == 0

    def test_no_signals(self):
        deploys = [{"timestamp": _ts(10), "node_name": "api"}]
        assert _compute_lead_times(deploys, []) == []

    def test_no_deploys(self):
        signals = [{"timestamp": _ts(0), "node_name": "api", "status_code": 200}]
        assert _compute_lead_times([], signals) == []


class TestChangeFailureRate:
    def test_no_rollbacks(self):
        deploys = [
            {"timestamp": _ts(10), "node_name": "api"},
            {"timestamp": _ts(5), "node_name": "api"},
        ]
        rate, count = _compute_change_failure_rate(deploys, [])
        assert rate == 0.0
        assert count == 0

    def test_one_rollback(self):
        deploys = [
            {"timestamp": _ts(60), "node_name": "api"},
            {"timestamp": _ts(30), "node_name": "api"},
        ]
        rollbacks = [
            {"timestamp": _ts(55), "node_name": "api"},  # After first deploy
        ]
        rate, count = _compute_change_failure_rate(deploys, rollbacks)
        assert count == 1
        assert abs(rate - 0.5) < 0.01  # 1 of 2

    def test_all_failed(self):
        deploys = [
            {"timestamp": _ts(60), "node_name": "api"},
            {"timestamp": _ts(30), "node_name": "db"},
        ]
        rollbacks = [
            {"timestamp": _ts(55), "node_name": "api"},
            {"timestamp": _ts(25), "node_name": "db"},
        ]
        rate, count = _compute_change_failure_rate(deploys, rollbacks)
        assert count == 2
        assert abs(rate - 1.0) < 0.01

    def test_no_deploys(self):
        rate, count = _compute_change_failure_rate([], [])
        assert rate is None
        assert count == 0


class TestMTTR:
    def test_basic_mttr(self):
        failures = [{"timestamp": _ts(10), "node_name": "api"}]
        recoveries = [{"timestamp": _ts(5), "node_name": "api"}]  # 5 min later
        result = _compute_mttr(failures, recoveries)
        assert len(result) == 1
        assert 280 < result[0] < 320  # ~300 seconds

    def test_multiple_cycles(self):
        failures = [
            {"timestamp": _ts(60), "node_name": "api"},
            {"timestamp": _ts(30), "node_name": "api"},
        ]
        recoveries = [
            {"timestamp": _ts(55), "node_name": "api"},
            {"timestamp": _ts(25), "node_name": "api"},
        ]
        result = _compute_mttr(failures, recoveries)
        assert len(result) == 2

    def test_no_recovery(self):
        failures = [{"timestamp": _ts(10), "node_name": "api"}]
        assert _compute_mttr(failures, []) == []

    def test_recovery_different_node(self):
        failures = [{"timestamp": _ts(10), "node_name": "api"}]
        recoveries = [{"timestamp": _ts(5), "node_name": "db"}]
        assert _compute_mttr(failures, recoveries) == []


class TestRecordEvent:
    def test_writes_event(self, project_dir: Path):
        ensure_baton_dir(project_dir)
        event = record_event(project_dir, EventType.DEPLOY, "api", detail="v2")
        assert event["type"] == "deploy"
        assert event["node_name"] == "api"
        assert event["detail"] == "v2"
        assert "timestamp" in event

        # Verify it was written
        events_path = project_dir / ".baton" / "events.jsonl"
        assert events_path.exists()
        data = json.loads(events_path.read_text().strip())
        assert data["type"] == "deploy"

    def test_custom_timestamp(self, project_dir: Path):
        ensure_baton_dir(project_dir)
        ts = "2026-03-08T00:00:00+00:00"
        event = record_event(project_dir, EventType.SWAP, "db", timestamp=ts)
        assert event["timestamp"] == ts


class TestComputeDora:
    def test_empty_project(self, project_dir: Path):
        """No data should return zeroed metrics without errors."""
        metrics = compute_dora(project_dir, window_hours=24)
        assert metrics.deployment_count == 0
        assert metrics.deployment_frequency == 0.0
        assert metrics.lead_time_p50 is None
        assert metrics.change_failure_rate is None
        assert metrics.mttr_p50 is None

    def test_with_deployments(self, project_dir: Path):
        ensure_baton_dir(project_dir)

        # Write some deploy events
        record_event(project_dir, EventType.DEPLOY, "api", detail="v1")
        record_event(project_dir, EventType.DEPLOY, "api", detail="v2")
        record_event(project_dir, EventType.SWAP, "db", detail="v1")

        metrics = compute_dora(project_dir, window_hours=24)
        assert metrics.deployment_count == 3
        assert metrics.deployment_frequency > 0
        assert metrics.change_failure_rate == 0.0  # No rollbacks
        assert metrics.rollback_count == 0

    def test_with_rollback(self, project_dir: Path):
        ensure_baton_dir(project_dir)

        record_event(project_dir, EventType.DEPLOY, "api")
        record_event(project_dir, EventType.CANARY_ROLLBACK, "api")

        metrics = compute_dora(project_dir, window_hours=24)
        assert metrics.deployment_count == 1
        assert metrics.rollback_count == 1
        assert metrics.change_failure_rate == 1.0

    def test_with_lead_time(self, project_dir: Path):
        ensure_baton_dir(project_dir)

        deploy_ts = _ts(5)
        signal_ts = _ts(4)

        record_event(project_dir, EventType.DEPLOY, "api", timestamp=deploy_ts)
        append_jsonl(project_dir, "signals.jsonl", {
            "node_name": "api",
            "status_code": 200,
            "timestamp": signal_ts,
        })

        metrics = compute_dora(project_dir, window_hours=24)
        assert metrics.lead_time_p50 is not None
        assert metrics.lead_time_p50 > 0

    def test_with_failure_recovery(self, project_dir: Path):
        ensure_baton_dir(project_dir)

        fail_ts = _ts(10)
        recover_ts = _ts(5)

        record_event(project_dir, EventType.FAILURE_DETECTED, "api", timestamp=fail_ts)
        record_event(project_dir, EventType.RECOVERY, "api", timestamp=recover_ts)

        metrics = compute_dora(project_dir, window_hours=24)
        assert metrics.mttr_p50 is not None
        assert metrics.failure_count == 1
        assert 280 < metrics.mttr_p50 < 320  # ~5 minutes

    def test_window_filtering(self, project_dir: Path):
        ensure_baton_dir(project_dir)

        # Event outside the window
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        record_event(project_dir, EventType.DEPLOY, "api", timestamp=old_ts)

        # Event inside the window
        record_event(project_dir, EventType.DEPLOY, "db")

        metrics = compute_dora(project_dir, window_hours=24)
        assert metrics.deployment_count == 1  # Only the recent one


class TestDORAMetrics:
    def test_to_dict(self):
        m = DORAMetrics(
            deployment_frequency=2.5,
            lead_time_p50=120.5,
            change_failure_rate=0.15,
            mttr_p50=300.0,
            window_hours=168,
            deployment_count=17,
            rollback_count=3,
            failure_count=5,
        )
        d = m.to_dict()
        assert d["deployment_frequency"] == 2.5
        assert d["lead_time_p50_s"] == 120.5
        assert d["change_failure_rate"] == 0.15
        assert d["mttr_p50_s"] == 300.0
        assert d["window_hours"] == 168

    def test_to_dict_none_values(self):
        m = DORAMetrics()
        d = m.to_dict()
        assert d["lead_time_p50_s"] is None
        assert d["change_failure_rate"] is None
        assert d["mttr_p50_s"] is None


class TestFormatDora:
    def test_full_report(self):
        m = DORAMetrics(
            deployment_frequency=2.5,
            lead_time_p50=45.0,
            change_failure_rate=0.10,
            mttr_p50=180.0,
            window_hours=168,
            deployment_count=17,
            rollback_count=2,
            failure_count=3,
        )
        output = format_dora(m)
        assert "2.50/day" in output
        assert "45.0s" in output
        assert "10.0%" in output
        assert "3.0m" in output
        assert "17" in output

    def test_no_data_report(self):
        m = DORAMetrics()
        output = format_dora(m)
        assert "0.00/day" in output
        assert "--" in output

    def test_lead_time_minutes(self):
        m = DORAMetrics(lead_time_p50=300.0)
        output = format_dora(m)
        assert "5.0m" in output

    def test_lead_time_hours(self):
        m = DORAMetrics(lead_time_p50=7200.0)
        output = format_dora(m)
        assert "2.0h" in output

    def test_mttr_hours(self):
        m = DORAMetrics(mttr_p50=7200.0, failure_count=1)
        output = format_dora(m)
        assert "2.0h" in output


class TestCLIIntegration:
    def test_dora_command(self, project_dir: Path):
        """Test the CLI dispatch for baton dora."""
        from baton.cli import main

        ensure_baton_dir(project_dir)
        record_event(project_dir, EventType.DEPLOY, "api")

        rc = main(["dora", "--dir", str(project_dir)])
        assert rc == 0

    def test_dora_json(self, project_dir: Path):
        """Test JSON output mode."""
        from baton.cli import main
        import io
        import sys

        ensure_baton_dir(project_dir)
        record_event(project_dir, EventType.DEPLOY, "api")

        # Capture stdout
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            rc = main(["dora", "--json", "--dir", str(project_dir)])
        finally:
            sys.stdout = old_stdout

        assert rc == 0
        data = json.loads(captured.getvalue())
        assert "deployment_frequency" in data
        assert "change_failure_rate" in data

    def test_dora_empty_project(self, project_dir: Path):
        """Dora on empty project should succeed with zeros."""
        from baton.cli import main

        rc = main(["dora", "--dir", str(project_dir)])
        assert rc == 0

    def test_dora_custom_window(self, project_dir: Path):
        """Test custom window parameter."""
        from baton.cli import main
        import io
        import sys

        ensure_baton_dir(project_dir)

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            rc = main(["dora", "--json", "--window", "24", "--dir", str(project_dir)])
        finally:
            sys.stdout = old_stdout

        assert rc == 0
        data = json.loads(captured.getvalue())
        assert data["window_hours"] == 24
