"""Tests for service log capture and following."""

from __future__ import annotations

import json

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


def test_follow_history_limits_history_and_keeps_appends(tmp_path):
    collector = ServiceLogCollector(tmp_path)
    for message in ("old", "recent", "newest"):
        collector.handler("api", "stdout", message)

    records = ServiceLogCollector.follow_history(tmp_path, last_n=2)
    assert next(records)["message"] == "recent"
    # Append while the caller is still consuming the initial snapshot.
    collector.handler("api", "stdout", "appended")
    assert next(records)["message"] == "newest"
    assert next(records)["message"] == "appended"
    records.close()


def test_follow_history_waits_for_complete_record(tmp_path, monkeypatch):
    collector = ServiceLogCollector(tmp_path)
    collector.handler("api", "stdout", "initial")
    path = tmp_path / ".baton" / "service_logs.jsonl"
    payload = json.dumps({"message": "completed"})
    with path.open("a") as stream:
        stream.write(payload[:8])

    def finish_record(_interval):
        with path.open("a") as stream:
            stream.write(payload[8:] + "\n")

    monkeypatch.setattr(service_log_module.time, "sleep", finish_record)
    records = ServiceLogCollector.follow_history(tmp_path)
    assert next(records)["message"] == "initial"
    assert next(records)["message"] == "completed"
    records.close()


def test_follow_history_skips_blank_history_and_appended_lines(tmp_path):
    collector = ServiceLogCollector(tmp_path)
    collector.handler("api", "stdout", "initial")
    path = tmp_path / ".baton" / "service_logs.jsonl"
    with path.open("a") as stream:
        stream.write("\n  \n")

    records = ServiceLogCollector.follow_history(tmp_path)
    assert next(records)["message"] == "initial"
    with path.open("a") as stream:
        stream.write("\n")
    collector.handler("api", "stdout", "appended")
    assert next(records)["message"] == "appended"
    records.close()


def test_follow_history_filters_new_records(tmp_path):
    collector = ServiceLogCollector(tmp_path)
    collector.handler("api", "stderr", "initial")
    records = ServiceLogCollector.follow_history(tmp_path, node="api", severity="error")
    assert next(records)["message"] == "initial"
    collector.handler("worker", "stderr", "wrong node")
    collector.handler("api", "stdout", "wrong level")
    collector.handler("api", "stderr", "matching")
    assert next(records)["message"] == "matching"
    records.close()
