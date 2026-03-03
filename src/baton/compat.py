"""Static compatibility analysis.

Compares expected dependency interfaces against exposed service APIs.
"""

from __future__ import annotations

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
