"""System-controlled service log capture.

Captures service stdout/stderr, structures with severity and node attribution,
persists to .baton/service_logs.jsonl for audit trail. Scans for taint
fingerprints in log output.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from baton.state import append_jsonl, read_jsonl

LOGS_FILE = "service_logs.jsonl"

# Severity levels (syslog-compatible ordering)
SEVERITIES = ("debug", "info", "warning", "error", "critical")

# Patterns to detect severity in log lines
_SEVERITY_PATTERNS = [
    (re.compile(r"\b(CRITICAL|FATAL)\b", re.IGNORECASE), "critical"),
    (re.compile(r"\bERROR\b", re.IGNORECASE), "error"),
    (re.compile(r"\b(WARNING|WARN)\b", re.IGNORECASE), "warning"),
    (re.compile(r"\bDEBUG\b", re.IGNORECASE), "debug"),
    (re.compile(r"\bINFO\b", re.IGNORECASE), "info"),
]


def parse_severity(line: str) -> str:
    """Extract severity level from a log line.

    Scans for common log level patterns (ERROR, WARNING, DEBUG, etc.).
    Defaults to "info" for stdout, "error" for stderr if no pattern found.
    """
    for pattern, level in _SEVERITY_PATTERNS:
        if pattern.search(line):
            return level
    return ""  # caller decides default based on stream


class ServiceLogCollector:
    """Captures and structures service log output.

    Provides a callback for ProcessManager that structures each line
    with node attribution, severity, timestamp, and stream source.
    Persists to .baton/service_logs.jsonl.
    """

    def __init__(self, project_dir: Path, taint_scanner=None):
        self._project_dir = project_dir
        self._taint_scanner = taint_scanner
        self._buffer: list[dict] = []
        self._buffer_max = 10000

    def handler(self, node_name: str, stream: str, line: str) -> None:
        """Log handler callback for ProcessManager.

        Args:
            node_name: Which node produced this line
            stream: "stdout" or "stderr"
            line: The log line text
        """
        severity = parse_severity(line)
        if not severity:
            severity = "error" if stream == "stderr" else "info"

        entry = {
            "node_name": node_name,
            "stream": stream,
            "severity": severity,
            "message": line,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._buffer.append(entry)
        if len(self._buffer) > self._buffer_max:
            self._buffer = self._buffer[-self._buffer_max:]

        append_jsonl(self._project_dir, LOGS_FILE, entry)

        # Taint scan log output for canary fingerprints
        if self._taint_scanner:
            self._taint_scanner.scan(
                line.encode("utf-8"), node_name, "log",
            )

    def query(
        self,
        node: str | None = None,
        severity: str | None = None,
        last_n: int = 100,
    ) -> list[dict]:
        """Query in-memory log buffer."""
        results = list(self._buffer)
        if node:
            results = [e for e in results if e.get("node_name") == node]
        if severity:
            sev_idx = SEVERITIES.index(severity) if severity in SEVERITIES else 0
            results = [
                e for e in results
                if SEVERITIES.index(e.get("severity", "info")) >= sev_idx
            ]
        return results[-last_n:]

    @staticmethod
    def load_history(
        project_dir: str | Path,
        node: str | None = None,
        severity: str | None = None,
        last_n: int | None = None,
    ) -> list[dict]:
        """Read from .baton/service_logs.jsonl."""
        records = read_jsonl(project_dir, LOGS_FILE, last_n=last_n)
        if node:
            records = [r for r in records if r.get("node_name") == node]
        if severity and severity in SEVERITIES:
            sev_idx = SEVERITIES.index(severity)
            records = [
                r for r in records
                if SEVERITIES.index(r.get("severity", "info")) >= sev_idx
            ]
        return records
