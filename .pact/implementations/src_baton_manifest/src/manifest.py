"""Service manifest loading.

Reads baton-service.yaml files from service directories.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from baton.schemas import DependencySpec, ServiceManifest

MANIFEST_FILENAME = "baton-service.yaml"


def load_manifest(service_dir: str | Path) -> ServiceManifest:
    """Load a ServiceManifest from baton-service.yaml in the given directory."""
    path = Path(service_dir) / MANIFEST_FILENAME
    if not path.exists():
        raise FileNotFoundError(f"No {MANIFEST_FILENAME} found in {service_dir}")
    with open(path) as f:
        raw = yaml.safe_load(f)
    if raw is None:
        raise ValueError(f"Empty {MANIFEST_FILENAME} in {service_dir}")
    return _parse_manifest(raw)


def _parse_manifest(raw: dict) -> ServiceManifest:
    """Parse raw YAML dict into ServiceManifest."""
    deps = []
    for d in raw.get("dependencies", []):
        if isinstance(d, str):
            deps.append(DependencySpec(name=d))
        elif isinstance(d, dict):
            deps.append(DependencySpec(**d))
        else:
            deps.append(d)

    return ServiceManifest(
        name=raw["name"],
        version=raw.get("version", "0.0.0"),
        api_spec=raw.get("api_spec", ""),
        mock_spec=raw.get("mock_spec", ""),
        command=raw.get("command", ""),
        port=raw.get("port", 0),
        proxy_mode=raw.get("proxy_mode", "http"),
        role=raw.get("role", "service"),
        dependencies=deps,
        metadata=raw.get("metadata", {}),
    )
