"""Config migration from v1 to v2 schema.

v2 adds per-node data_access, authority, openapi_spec fields,
per-edge data_tiers_in_flight, and top-level arbiter, ledger,
audit_channel sections.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import yaml


def detect_version(raw: dict) -> int:
    """Return the config schema version (defaults to 1 if absent)."""
    return int(raw.get("version", 1))


def migrate_v1_to_v2(raw: dict) -> dict:
    """Migrate a raw v1 config dict to v2 in place and return it.

    Idempotent: fields that already exist are not overwritten.
    """
    data = copy.deepcopy(raw)

    data["version"] = 2

    # -- Nodes --
    for node in data.get("nodes", []):
        if "data_access" not in node:
            node["data_access"] = {"reads": [], "writes": []}
        if "authority" not in node:
            node["authority"] = []
        # openapi_spec stub only for HTTP-mode nodes
        proxy_mode = node.get("proxy_mode", "http")
        if proxy_mode == "http" and "openapi_spec" not in node:
            node["openapi_spec"] = ""

    # -- Edges --
    for edge in data.get("edges", []):
        if "data_tiers_in_flight" not in edge:
            edge["data_tiers_in_flight"] = []

    # -- Top-level integration stubs --
    if "arbiter" not in data:
        data["arbiter"] = {
            "endpoint": "",
            "api_endpoint": "",
            "forward_spans": False,
            "classification_tagging": False,
        }
    if "ledger" not in data:
        data["ledger"] = {
            "api_endpoint": "",
            "mock_from_ledger": True,
        }
    if "audit_channel" not in data:
        data["audit_channel"] = {
            "port": 9000,
            "protocol": "http",
        }

    return data


def load_raw_config(path: Path) -> dict:
    """Load a YAML file and return the raw dict."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    if raw is None:
        raw = {}
    return raw


def save_raw_config(data: dict, path: Path) -> None:
    """Write a raw dict back to YAML."""
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def try_ruamel_roundtrip(path: Path, data: dict, output_path: Path) -> bool:
    """Attempt comment-preserving write via ruamel.yaml.

    Returns True if successful, False if ruamel is not available.
    """
    try:
        from ruamel.yaml import YAML  # type: ignore[import-untyped]

        ryaml = YAML()
        ryaml.preserve_quotes = True
        # Load original to get CommentedMap with comments
        with open(path) as f:
            commented = ryaml.load(f)

        # Merge migrated values into the commented structure
        _deep_update(commented, data)

        with open(output_path, "w") as f:
            ryaml.dump(commented, f)
        return True
    except ImportError:
        return False


def _deep_update(base: dict, updates: dict) -> None:
    """Recursively update base with values from updates."""
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_update(base[key], value)
        elif key in base and isinstance(base[key], list) and isinstance(value, list):
            # For lists (like nodes/edges), replace entirely since migration
            # may have added fields to list items
            base[key] = value
        else:
            base[key] = value


def run_migrate(
    config_path: Path,
    output_path: Path | None = None,
    dry_run: bool = False,
) -> int:
    """Run the migration. Returns 0 on success, 1 on error.

    Parameters
    ----------
    config_path:
        Path to the input baton.yaml.
    output_path:
        Where to write the result. Defaults to config_path (overwrite).
    dry_run:
        If True, print the migrated YAML to stdout without writing.
    """
    if not config_path.exists():
        print(f"Error: {config_path} not found", file=sys.stderr)
        return 1

    raw = load_raw_config(config_path)
    version = detect_version(raw)

    if version >= 2:
        print("Already at v2")
        return 0

    migrated = migrate_v1_to_v2(raw)

    if dry_run:
        yaml.dump(migrated, sys.stdout, default_flow_style=False, sort_keys=False)
        return 0

    dest = output_path or config_path

    # Try comment-preserving write first
    if not try_ruamel_roundtrip(config_path, migrated, dest):
        save_raw_config(migrated, dest)

    print(f"Migrated {config_path} to v2 -> {dest}")
    return 0
