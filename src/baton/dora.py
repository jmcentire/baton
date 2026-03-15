"""DORA metrics derivation from Baton telemetry data.

Derives the four DORA metrics from existing JSONL files and circuit state:
  1. Deployment Frequency -- deployments per time window
  2. Lead Time for Changes -- deployment trigger to first healthy traffic
  3. Change Failure Rate -- percentage of deployments that trigger rollback
  4. Mean Time to Recovery (MTTR) -- failure detection to recovery

Data sources:
  - .baton/events.jsonl  -- lifecycle events (deploy, swap, rollback, recovery)
  - .baton/signals.jsonl -- per-request signal records with timestamps
  - .baton/metrics.jsonl -- periodic metric snapshots
  - .baton/state.json    -- current circuit state
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

from baton.state import append_jsonl, read_jsonl

logger = logging.getLogger(__name__)

EVENTS_FILE = "events.jsonl"


# -- Event types for lifecycle tracking --

class EventType:
    DEPLOY = "deploy"          # Service slotted or swapped
    SWAP = "swap"              # Hot-swap (deploy variant)
    ROLLBACK = "rollback"      # Canary or manual rollback
    CANARY_START = "canary_start"
    CANARY_PROMOTE = "canary_promote"
    CANARY_ROLLBACK = "canary_rollback"
    FAILURE_DETECTED = "failure_detected"
    RECOVERY = "recovery"
    VALIDATION_FAILED = "validation_failed"
    TAINT_VIOLATION = "taint_violation"
    SERVICE_EVENT = "service_event"


def record_event(
    project_dir: str | Path,
    event_type: str,
    node_name: str,
    detail: str = "",
    timestamp: str | None = None,
) -> dict:
    """Record a lifecycle event to .baton/events.jsonl.

    Called by lifecycle operations (slot, swap, canary) to build
    the event stream that DORA metrics are derived from.
    """
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    event = {
        "type": event_type,
        "node_name": node_name,
        "detail": detail,
        "timestamp": ts,
    }
    append_jsonl(project_dir, EVENTS_FILE, event)
    return event


# -- DORA Metrics --


@dataclass
class DORAMetrics:
    """The four DORA metrics for a time window.

    Attributes:
        deployment_frequency: Deployments per day in the window.
        lead_time_p50: Median seconds from deploy to first healthy signal.
            None if no deploy-to-healthy pairs found.
        change_failure_rate: Fraction of deployments that caused rollback (0.0-1.0).
            None if no deployments in window.
        mttr_p50: Median seconds from failure detection to recovery.
            None if no failure/recovery pairs found.
        window_hours: The time window these metrics cover.
        deployment_count: Total deployments in the window.
        rollback_count: Number of deployments that triggered rollback.
        failure_count: Number of failure/recovery cycles.
    """

    deployment_frequency: float = 0.0
    lead_time_p50: float | None = None
    change_failure_rate: float | None = None
    mttr_p50: float | None = None
    window_hours: int = 168
    deployment_count: int = 0
    rollback_count: int = 0
    failure_count: int = 0

    def to_dict(self) -> dict:
        return {
            "deployment_frequency": round(self.deployment_frequency, 3),
            "lead_time_p50_s": round(self.lead_time_p50, 1) if self.lead_time_p50 is not None else None,
            "change_failure_rate": round(self.change_failure_rate, 4) if self.change_failure_rate is not None else None,
            "mttr_p50_s": round(self.mttr_p50, 1) if self.mttr_p50 is not None else None,
            "window_hours": self.window_hours,
            "deployment_count": self.deployment_count,
            "rollback_count": self.rollback_count,
            "failure_count": self.failure_count,
        }


def _parse_ts(ts_str: str) -> datetime | None:
    """Parse ISO timestamp string, return None on failure."""
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _filter_window(events: list[dict], cutoff: datetime) -> list[dict]:
    """Filter events to those after the cutoff timestamp."""
    result = []
    for ev in events:
        ts = _parse_ts(ev.get("timestamp", ""))
        if ts and ts >= cutoff:
            result.append(ev)
    return result


def _compute_deployment_frequency(
    deploy_events: list[dict], window_hours: int,
) -> tuple[float, int]:
    """Count deployments and compute per-day frequency.

    Returns (frequency_per_day, total_count).
    """
    count = len(deploy_events)
    window_days = window_hours / 24.0
    freq = count / window_days if window_days > 0 else 0.0
    return freq, count


def _compute_lead_times(
    deploy_events: list[dict],
    signals: list[dict],
) -> list[float]:
    """Compute lead times: seconds from deploy to first healthy signal on that node.

    For each deployment event, find the first signal with status_code < 400
    on the same node after the deployment timestamp.
    """
    if not deploy_events or not signals:
        return []

    # Pre-sort signals by timestamp
    timed_signals = []
    for sig in signals:
        ts = _parse_ts(sig.get("timestamp", ""))
        if ts:
            timed_signals.append((ts, sig))
    timed_signals.sort(key=lambda x: x[0])

    lead_times = []
    for ev in deploy_events:
        deploy_ts = _parse_ts(ev.get("timestamp", ""))
        node = ev.get("node_name", "")
        if not deploy_ts or not node:
            continue

        # Find first healthy signal on this node after deploy
        for sig_ts, sig in timed_signals:
            if sig_ts < deploy_ts:
                continue
            if sig.get("node_name") != node:
                continue
            status = sig.get("status_code", 0)
            if 200 <= status < 400:
                delta = (sig_ts - deploy_ts).total_seconds()
                lead_times.append(delta)
                break

    return lead_times


def _compute_change_failure_rate(
    deploy_events: list[dict],
    rollback_events: list[dict],
) -> tuple[float | None, int]:
    """Compute fraction of deployments followed by rollback.

    A deployment is "failed" if a rollback event for the same node
    occurs before the next deployment to that node.

    Returns (rate, rollback_count).
    """
    if not deploy_events:
        return None, 0

    # Build per-node deployment timeline
    node_deploys: dict[str, list[datetime]] = {}
    for ev in deploy_events:
        ts = _parse_ts(ev.get("timestamp", ""))
        node = ev.get("node_name", "")
        if ts and node:
            node_deploys.setdefault(node, []).append(ts)

    # Sort each node's deploys
    for deploys in node_deploys.values():
        deploys.sort()

    # Count rollbacks attributable to deployments
    rollback_count = 0
    matched_deploys: set[tuple[str, str]] = set()  # (node, deploy_ts_iso)

    for rb in rollback_events:
        rb_ts = _parse_ts(rb.get("timestamp", ""))
        node = rb.get("node_name", "")
        if not rb_ts or not node or node not in node_deploys:
            continue

        # Find the most recent deployment before this rollback
        deploys = node_deploys[node]
        preceding = [d for d in deploys if d <= rb_ts]
        if preceding:
            deploy_ts = preceding[-1]
            key = (node, deploy_ts.isoformat())
            if key not in matched_deploys:
                matched_deploys.add(key)
                rollback_count += 1

    total = len(deploy_events)
    rate = rollback_count / total if total > 0 else 0.0
    return rate, rollback_count


def _compute_mttr(
    failure_events: list[dict],
    recovery_events: list[dict],
) -> list[float]:
    """Compute MTTR: seconds from failure detection to recovery.

    Pairs each failure event with the next recovery event on the same node.
    """
    if not failure_events or not recovery_events:
        return []

    # Sort recovery events by timestamp
    timed_recoveries = []
    for ev in recovery_events:
        ts = _parse_ts(ev.get("timestamp", ""))
        node = ev.get("node_name", "")
        if ts and node:
            timed_recoveries.append((ts, node))
    timed_recoveries.sort(key=lambda x: x[0])

    mttrs = []
    for fev in failure_events:
        fail_ts = _parse_ts(fev.get("timestamp", ""))
        node = fev.get("node_name", "")
        if not fail_ts or not node:
            continue

        # Find next recovery on same node
        for rec_ts, rec_node in timed_recoveries:
            if rec_ts > fail_ts and rec_node == node:
                delta = (rec_ts - fail_ts).total_seconds()
                mttrs.append(delta)
                break

    return mttrs


def compute_dora(
    project_dir: str | Path,
    window_hours: int = 168,
) -> DORAMetrics:
    """Compute DORA metrics from JSONL event and signal data.

    Reads:
      - .baton/events.jsonl for deployment, rollback, failure, recovery events
      - .baton/signals.jsonl for request-level data (lead time derivation)

    Args:
        project_dir: Path to the project directory containing .baton/
        window_hours: Time window in hours (default: 168 = 1 week)

    Returns:
        DORAMetrics dataclass with all four metrics.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)

    # Load events
    all_events = read_jsonl(project_dir, EVENTS_FILE)
    events = _filter_window(all_events, cutoff)

    # Categorize events
    deploy_events = [
        e for e in events
        if e.get("type") in (EventType.DEPLOY, EventType.SWAP)
    ]
    rollback_events = [
        e for e in events
        if e.get("type") in (EventType.ROLLBACK, EventType.CANARY_ROLLBACK)
    ]
    failure_events = [
        e for e in events
        if e.get("type") == EventType.FAILURE_DETECTED
    ]
    recovery_events = [
        e for e in events
        if e.get("type") == EventType.RECOVERY
    ]

    # Load signals for lead time calculation
    all_signals = read_jsonl(project_dir, "signals.jsonl")
    signals = _filter_window(all_signals, cutoff)

    # 1. Deployment Frequency
    freq, deploy_count = _compute_deployment_frequency(deploy_events, window_hours)

    # 2. Lead Time for Changes
    lead_times = _compute_lead_times(deploy_events, signals)
    lead_time_p50 = statistics.median(lead_times) if lead_times else None

    # 3. Change Failure Rate
    cfr, rollback_count = _compute_change_failure_rate(deploy_events, rollback_events)

    # 4. MTTR
    mttrs = _compute_mttr(failure_events, recovery_events)
    mttr_p50 = statistics.median(mttrs) if mttrs else None

    return DORAMetrics(
        deployment_frequency=freq,
        lead_time_p50=lead_time_p50,
        change_failure_rate=cfr,
        mttr_p50=mttr_p50,
        window_hours=window_hours,
        deployment_count=deploy_count,
        rollback_count=rollback_count,
        failure_count=len(mttrs),
    )


def format_dora(metrics: DORAMetrics) -> str:
    """Format DORA metrics as a human-readable report."""
    lines = [
        f"DORA Metrics (last {metrics.window_hours}h)",
        "=" * 40,
        "",
    ]

    # Deployment Frequency
    lines.append(f"Deployment Frequency:  {metrics.deployment_frequency:.2f}/day")
    lines.append(f"  Total deployments:   {metrics.deployment_count}")
    lines.append("")

    # Lead Time
    if metrics.lead_time_p50 is not None:
        if metrics.lead_time_p50 < 60:
            lt_str = f"{metrics.lead_time_p50:.1f}s"
        elif metrics.lead_time_p50 < 3600:
            lt_str = f"{metrics.lead_time_p50 / 60:.1f}m"
        else:
            lt_str = f"{metrics.lead_time_p50 / 3600:.1f}h"
        lines.append(f"Lead Time (p50):       {lt_str}")
    else:
        lines.append("Lead Time (p50):       --  (no deploy-to-healthy data)")
    lines.append("")

    # Change Failure Rate
    if metrics.change_failure_rate is not None:
        lines.append(f"Change Failure Rate:   {metrics.change_failure_rate * 100:.1f}%")
        lines.append(f"  Rollbacks:           {metrics.rollback_count}/{metrics.deployment_count}")
    else:
        lines.append("Change Failure Rate:   --  (no deployments)")
    lines.append("")

    # MTTR
    if metrics.mttr_p50 is not None:
        if metrics.mttr_p50 < 60:
            mttr_str = f"{metrics.mttr_p50:.1f}s"
        elif metrics.mttr_p50 < 3600:
            mttr_str = f"{metrics.mttr_p50 / 60:.1f}m"
        else:
            mttr_str = f"{metrics.mttr_p50 / 3600:.1f}h"
        lines.append(f"MTTR (p50):            {mttr_str}")
        lines.append(f"  Recovery cycles:     {metrics.failure_count}")
    else:
        lines.append("MTTR (p50):            --  (no failure/recovery pairs)")

    return "\n".join(lines)
