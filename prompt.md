# Enable OTLP Export by Default in Baton Circuit Orchestration

## Context

Baton is a circuit orchestration / service mesh system that currently treats OpenTelemetry (OTLP) span and metric export as optional. The system has existing `OtelSpanExporter` and `OtelMetricExporter` classes supporting gRPC and HTTP protocols, plus built-in observability via JSONL signals and dashboard.

## Problem

Teams naturally forward telemetry to external observability tools (Honeycomb/Jaeger) for exploration because Baton's built-in observability is too thin for exploratory querying. The current opt-in approach creates friction for teams who need OTLP export enabled by default. Additionally, the new Chronicler project requires OTLP as a sink for story building, and OTLP export enables closed-loop feedback in the governance stack.

## Requirements

### Functional Requirements
- Change OpenTelemetry from optional to required dependency in pyproject.toml
- Default `otlp_enabled` to `True` in `ObservabilityConfig`
- Support multiple OTLP endpoints for fan-out capability (collector + Chronicler)
- Implement fire-and-forget approach: unreachable endpoints log warning and continue without blocking circuit operation
- Maintain backward compatibility for existing baton.yaml configs without observability section

### Non-Functional Requirements
- All existing 804+ tests must continue to pass
- Circuit operation must never be blocked by OTLP export failures
- System must gracefully handle unreachable OTLP endpoints
- Performance impact should be minimal

## Stakeholders
- Teams using Baton for deployment/routing
- Users of external observability tools (Honeycomb/Jaeger)  
- FOSS governance stack users
- Chronicler project team

## Dependencies
- OpenTelemetry library (transitioning from optional to required)
- Pact (contracts)
- Sentinel (production monitoring)
- Chronicler project
- External observability tools
- OTLP collector endpoints

## Success Criteria
- Seamless integration with external observability tools by default
- Fan-out capability to multiple OTLP endpoints working correctly
- Backward compatibility maintained for existing configurations
- No blocking behavior on unreachable endpoints
- All tests passing

## Constraints
- Must maintain backward compatibility with existing baton.yaml files
- Circuit operation must never be blocked by observability export
- Focus on OTLP export enhancement, not replacing built-in observability