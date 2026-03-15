"""Static compatibility analysis.

Compares expected dependency interfaces against exposed service APIs.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from baton.schemas import ServiceManifest


@dataclass(frozen=True)
class CompatIssue:
    """A single compatibility issue."""

    consumer: str
    provider: str
    path: str
    method: str
    severity: str  # "error" or "warning"
    detail: str


@dataclass
class CompatReport:
    """Result of a compatibility check."""

    compatible: bool = True
    issues: list[CompatIssue] = field(default_factory=list)

    def add(self, issue: CompatIssue) -> None:
        self.issues.append(issue)
        if issue.severity == "error":
            self.compatible = False


def check_compatibility(
    provider: ServiceManifest,
    consumers: list[ServiceManifest],
    base_dir: str | Path = ".",
) -> CompatReport:
    """Check if a provider service is compatible with all consumers.

    For each consumer that depends on the provider:
    1. Load the consumer's expected_api for that dependency.
    2. Load the provider's api_spec.
    3. Verify expected paths/methods exist and schemas are structurally compatible.
    """
    report = CompatReport()
    base = Path(base_dir)

    provider_paths = (
        _load_api_paths(base, provider.api_spec) if provider.api_spec else {}
    )

    for consumer in consumers:
        for dep in consumer.dependencies:
            if dep.name != provider.name:
                continue
            if not dep.expected_api:
                continue

            expected_paths = _load_api_paths(base, dep.expected_api)
            _compare_paths(
                consumer.name, provider.name,
                expected_paths, provider_paths, report,
            )

    return report


def _load_api_paths(
    base: Path, spec_path: str
) -> dict[str, dict[str, Any]]:
    """Load OpenAPI paths from a spec file.

    Returns: {path: {METHOD: response_schema_or_None}}
    """
    full_path = base / spec_path
    if not full_path.exists():
        return {}
    with open(full_path) as f:
        if full_path.suffix in (".yaml", ".yml"):
            spec = yaml.safe_load(f)
        else:
            spec = json.load(f)
    if not spec or "paths" not in spec:
        return {}

    components = spec.get("components", {}).get("schemas", {})
    result: dict[str, dict[str, Any]] = {}
    for path_str, methods in spec.get("paths", {}).items():
        result[path_str] = {}
        for method, operation in methods.items():
            if method.startswith("x-") or method == "parameters":
                continue
            result[path_str][method.upper()] = _extract_response_schema(
                operation, components
            )
    return result


def _extract_response_schema(operation: dict, components: dict) -> Any:
    """Extract the success response schema from an operation."""
    responses = operation.get("responses", {})
    success = responses.get("200") or responses.get("201") or {}
    content = success.get("content", {}).get("application/json", {})
    schema = content.get("schema", {})
    if "$ref" in schema:
        ref_name = schema["$ref"].split("/")[-1]
        schema = components.get(ref_name, {})
    return schema or None


def _compare_paths(
    consumer: str,
    provider: str,
    expected: dict[str, dict[str, Any]],
    actual: dict[str, dict[str, Any]],
    report: CompatReport,
) -> None:
    """Compare expected paths/methods against actual."""
    for path, methods in expected.items():
        if path not in actual:
            for method in methods:
                report.add(CompatIssue(
                    consumer=consumer, provider=provider,
                    path=path, method=method, severity="error",
                    detail=f"Path '{path}' expected by {consumer} but not provided by {provider}",
                ))
            continue
        for method, expected_schema in methods.items():
            if method not in actual[path]:
                report.add(CompatIssue(
                    consumer=consumer, provider=provider,
                    path=path, method=method, severity="error",
                    detail=f"{method} {path} expected by {consumer} but not provided by {provider}",
                ))
                continue
            actual_schema = actual[path][method]
            if expected_schema and actual_schema:
                _compare_schemas(
                    consumer, provider, path, method,
                    expected_schema, actual_schema, report,
                )


def _compare_schemas(
    consumer: str,
    provider: str,
    path: str,
    method: str,
    expected: dict,
    actual: dict,
    report: CompatReport,
) -> None:
    """Structural subtype check: expected fields must exist in actual.

    Provider can return extra fields (structural subtyping).
    """
    expected_type = expected.get("type")
    actual_type = actual.get("type")

    if expected_type and actual_type and expected_type != actual_type:
        report.add(CompatIssue(
            consumer=consumer, provider=provider,
            path=path, method=method, severity="error",
            detail=f"Type mismatch: expected '{expected_type}', got '{actual_type}'",
        ))
        return

    if expected_type == "object":
        expected_required = set(expected.get("required", []))
        actual_props = set(actual.get("properties", {}).keys())
        missing = expected_required - actual_props
        if missing:
            report.add(CompatIssue(
                consumer=consumer, provider=provider,
                path=path, method=method, severity="error",
                detail=f"Missing required properties: {missing}",
            ))

    if expected_type == "array":
        exp_items = expected.get("items", {})
        act_items = actual.get("items", {})
        if exp_items and act_items:
            _compare_schemas(
                consumer, provider, path, method,
                exp_items, act_items, report,
            )


@dataclass(frozen=True)
class RuntimeProbeResult:
    """Result of probing a single endpoint."""
    path: str
    method: str
    reachable: bool
    status_code: int = 0
    detail: str = ""


@dataclass
class RuntimeValidationResult:
    """Result of runtime interface validation."""
    compatible: bool = True
    issues: list[CompatIssue] = field(default_factory=list)
    probed_endpoints: int = 0
    reachable: bool = False

    def add(self, issue: CompatIssue) -> None:
        self.issues.append(issue)
        if issue.severity == "error":
            self.compatible = False


async def validate_service_runtime(
    host: str,
    port: int,
    contract_path: str | Path,
    base_dir: str | Path = ".",
    timeout: float = 5.0,
) -> RuntimeValidationResult:
    """Probe a running service to verify it implements the expected API contract.

    For each path/method in the contract's OpenAPI spec:
    1. Send an HTTP request to verify the endpoint exists
    2. Verify the endpoint doesn't return 404 or 405

    Args:
        host: Service host
        port: Service port
        contract_path: Path to the OpenAPI spec file (relative to base_dir)
        base_dir: Base directory for resolving spec paths
        timeout: Timeout per probe request in seconds

    Returns:
        RuntimeValidationResult with compatibility assessment
    """
    result = RuntimeValidationResult()
    base = Path(base_dir)

    # Load the contract spec
    api_paths = _load_api_paths(base, str(contract_path))
    if not api_paths:
        # No paths in contract — nothing to validate
        result.reachable = True
        return result

    # Check reachability first (with retries for startup race)
    reachable = False
    for attempt in range(3):
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=2.0,
            )
            writer.close()
            await writer.wait_closed()
            reachable = True
            break
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
            if attempt < 2:
                await asyncio.sleep(0.5)

    result.reachable = reachable
    if not reachable:
        result.compatible = False
        result.issues.append(CompatIssue(
            consumer="runtime",
            provider="service",
            path="*",
            method="*",
            severity="error",
            detail=f"Service unreachable at {host}:{port}",
        ))
        return result

    # Probe each endpoint
    probes = []
    for path_str, methods in api_paths.items():
        for method in methods:
            probes.append((path_str, method))

    result.probed_endpoints = len(probes)

    # Probe concurrently
    probe_tasks = [
        _probe_endpoint(host, port, path_str, method, timeout)
        for path_str, method in probes
    ]
    probe_results = await asyncio.gather(*probe_tasks, return_exceptions=True)

    for (path_str, method), probe in zip(probes, probe_results):
        if isinstance(probe, Exception):
            result.add(CompatIssue(
                consumer="runtime",
                provider="service",
                path=path_str,
                method=method,
                severity="error",
                detail=f"Probe failed: {probe}",
            ))
            continue
        if not probe.reachable:
            result.add(CompatIssue(
                consumer="runtime",
                provider="service",
                path=path_str,
                method=method,
                severity="error",
                detail=probe.detail or "Endpoint unreachable",
            ))
        elif probe.status_code in (404, 405):
            result.add(CompatIssue(
                consumer="runtime",
                provider="service",
                path=path_str,
                method=method,
                severity="error",
                detail=f"Endpoint returned {probe.status_code} — not implemented",
            ))

    return result


async def _probe_endpoint(
    host: str,
    port: int,
    path: str,
    method: str,
    timeout: float,
) -> RuntimeProbeResult:
    """Send an HTTP request to probe a single endpoint.

    Uses HEAD for safe methods (GET), OPTIONS for others.
    Falls back to the actual method if HEAD/OPTIONS returns 405.
    """
    # Use the actual method for the probe — we just care about 404 vs not-404
    probe_method = method.upper()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        request = (
            f"{probe_method} {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Connection: close\r\n"
            f"Content-Length: 0\r\n"
            f"\r\n"
        ).encode("ascii")
        writer.write(request)
        await writer.drain()

        response = await asyncio.wait_for(reader.read(4096), timeout=timeout)
        writer.close()
        await writer.wait_closed()

        status_code = _parse_probe_status(response)
        return RuntimeProbeResult(
            path=path,
            method=probe_method,
            reachable=True,
            status_code=status_code,
        )
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
        return RuntimeProbeResult(
            path=path,
            method=probe_method,
            reachable=False,
            detail=str(e),
        )


def _parse_probe_status(response: bytes) -> int:
    """Parse HTTP status code from response bytes."""
    try:
        first_line = response.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        parts = first_line.split(" ")
        if len(parts) >= 2:
            return int(parts[1])
    except (ValueError, IndexError):
        pass
    return 0
