# Task: Make OTLP Export Default in Baton

## What to change

Baton currently treats OpenTelemetry span and metric export as an optional feature (`pip install baton[otel]`). This should be the default behavior.

## Specific changes

1. **Move `opentelemetry` from optional to required dependency** in pyproject.toml. Move the packages from `[project.optional-dependencies]` otel extra to `[project.dependencies]`.

2. **Enable OTLP span export by default** in config.py / schemas.py. The `ObservabilityConfig` should default `otlp_enabled` to `True` (or add such a field if it doesn't exist). Default endpoint: `http://localhost:4317` (standard OTLP collector). Users opt-out by setting `otlp_enabled: false` in baton.yaml.

3. **Add Chronicler as a named OTLP sink** in config.py. Support multiple OTLP endpoints:
   ```yaml
   observability:
     otlp_enabled: true
     otlp_endpoints:
       - name: collector
         endpoint: http://localhost:4317
         protocol: grpc
       - name: chronicler
         endpoint: http://localhost:4318
         protocol: grpc
   ```

4. **Update otel.py** to support multiple endpoints — fan out spans/metrics to all configured endpoints.

5. **De-emphasize the built-in dashboard** in CLI help text and docs. Add a note that it is a development aid, not production observability.

6. **Update tests** for the new defaults.

## Constraints

- Backward compatible: existing baton.yaml files without observability config should work (OTLP attempts connection to localhost:4317, logs warning if unreachable, continues without blocking)
- Unreachable OTLP endpoint must never block circuit operation (fire-and-forget, consistent with Arbiter integration pattern)
- All existing tests must pass
