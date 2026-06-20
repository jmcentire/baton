"""Tests for service log capture and following."""

from __future__ import annotations

from baton import service_log as service_log_module
from baton.service_log import ServiceLogCollector


def test_follow_history_yields_existing_and_appended_records(tmp_path):
    collector = ServiceLogCollector(tmp_path)
    collector.handler("api", "stdout", "service ready")

    records = ServiceLogCollector.follow_history(tmp_path, poll_interval=0)
    first = next(records)

    collector.handler("api", "stderr", "request failed")
    second = next(records)
    records.close()

    assert first["message"] == "service ready"
    assert second["message"] == "request failed"


def test_follow_history_applies_node_and_severity_filters(tmp_path):
    collector = ServiceLogCollector(tmp_path)
    collector.handler("api", "stdout", "service ready")
    collector.handler("api", "stderr", "request failed")
    collector.handler("worker", "stderr", "worker failed")

    records = ServiceLogCollector.follow_history(
        tmp_path,
        node="api",
        severity="warning",
        poll_interval=0,
    )
    record = next(records)
    records.close()

    assert record["node_name"] == "api"
    assert record["severity"] == "error"
    assert record["message"] == "request failed"


def test_follow_history_waits_for_log_file(tmp_path, monkeypatch):
    collector = ServiceLogCollector(tmp_path)

    def create_log_file(_interval):
        collector.handler("api", "stdout", "first record")

    monkeypatch.setattr(service_log_module.time, "sleep", create_log_file)

    records = ServiceLogCollector.follow_history(tmp_path)
    record = next(records)
    records.close()

    assert record["message"] == "first record"
