# Baton: Make OTLP Export Default

## What This Is

A targeted modification to Baton (circuit orchestration / service mesh) to make OpenTelemetry span and metric export the default behavior instead of an optional extra.

## Current State

Baton currently treats OTLP export as optional (`pip install baton[otel]`). The otel.py module has full OtelSpanExporter and OtelMetricExporter classes supporting gRPC and HTTP protocols. But users must opt in.

## What Changes

1. Move opentelemetry from optional to required dependency in pyproject.toml
2. Default otlp_enabled to True in ObservabilityConfig (opt-out instead of opt-in)
3. Support multiple OTLP endpoints (fan-out to collector + Chronicler)
4. Unreachable endpoints must never block circuit operation (fire-and-forget)
5. De-emphasize built-in dashboard as development aid in CLI help

## Why

The FOSS governance stack's unique contribution is closed-loop feedback (Sentinel → Pact contract tightening). But Baton's built-in observability (JSONL signals, dashboard) is too thin for exploratory querying. By making OTLP default, teams naturally forward to Honeycomb/Jaeger/etc. for exploration while the governance stack handles automated trust verification.

Chronicler (new project) will also act as an OTLP sink, building stories from Baton spans.

## Constraints

- Backward compatible: existing baton.yaml without observability config still works
- Unreachable OTLP endpoint logs warning, continues without blocking
- All existing 804+ tests must pass
- Multiple endpoints supported for fan-out

## Stack Position

Baton is the deployment/routing layer. It sits between Pact (contracts) and Sentinel (production monitoring). OTLP export connects it to external observability AND to Chronicler for story assembly.
