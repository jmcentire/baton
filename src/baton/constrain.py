"""Constrain integration for Baton.

Reads component_map.yaml from Constrain output and generates
a baton.yaml skeleton with nodes, edges, and data access declarations.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def load_component_map(constrain_dir: str | Path) -> dict:
    """Read component_map.yaml from a Constrain output directory.

    Args:
        constrain_dir: Path to directory containing component_map.yaml

    Returns:
        Parsed YAML dict

    Raises:
        FileNotFoundError: If component_map.yaml not found
    """
    path = Path(constrain_dir) / "component_map.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No component_map.yaml found in {constrain_dir}")
    with open(path) as f:
        data = yaml.safe_load(f)
    if data is None:
        return {"components": [], "edges": []}
    return data


def generate_baton_config(
    component_map: dict,
    circuit_name: str = "default",
    start_port: int = 8001,
) -> dict:
    """Generate a baton.yaml-compatible dict from a component_map.

    Port assignment starts at start_port and increments for each component.

    Args:
        component_map: Parsed component_map.yaml dict
        circuit_name: Name for the generated circuit
        start_port: First port to assign (default 8001)

    Returns:
        Dict ready to serialize as baton.yaml
    """
    nodes = []
    port = start_port

    for component in component_map.get("components", []):
        name = component.get("name", "")
        if not name:
            continue

        node: dict = {
            "name": name,
            "port": component.get("port", port),
        }

        # Protocol mapping
        protocol = component.get("protocol", "http")
        if protocol != "http":
            node["proxy_mode"] = protocol

        # Role mapping
        role = component.get("role", "service")
        if role != "service":
            node["role"] = role

        # Data access declarations
        data_access = component.get("data_access", {})
        if data_access:
            node["data_access"] = {
                "reads": data_access.get("reads", []),
                "writes": data_access.get("writes", []),
            }

        # Authority domains
        authority = component.get("authority", {})
        if authority and authority.get("domains"):
            node["authority"] = authority["domains"]

        # OpenAPI spec path
        spec = component.get("openapi_spec", "")
        if spec:
            node["openapi_spec"] = spec

        nodes.append(node)
        port += 1  # Next port even if component specified its own

    edges = []
    for edge in component_map.get("edges", []):
        source = edge.get("from", edge.get("source", ""))
        target = edge.get("to", edge.get("target", ""))
        if not source or not target:
            continue
        ed: dict = {"source": source, "target": target}

        # Data tiers in flight
        tiers = edge.get("data_tiers_in_flight", edge.get("tiers", []))
        if tiers:
            ed["data_tiers_in_flight"] = tiers

        edges.append(ed)

    config: dict = {
        "name": circuit_name,
        "version": 2,
    }
    if nodes:
        config["nodes"] = nodes
    if edges:
        config["edges"] = edges

    return config


def generate_and_save(
    constrain_dir: str | Path,
    output_dir: str | Path,
    circuit_name: str = "default",
    start_port: int = 8001,
) -> Path:
    """Load component_map.yaml and generate baton.yaml.

    Args:
        constrain_dir: Directory containing component_map.yaml
        output_dir: Directory to write baton.yaml to
        circuit_name: Circuit name
        start_port: First port to assign

    Returns:
        Path to the generated baton.yaml
    """
    component_map = load_component_map(constrain_dir)
    config = generate_baton_config(component_map, circuit_name, start_port)

    output_path = Path(output_dir) / "baton.yaml"
    with open(output_path, "w") as f:
        f.write(f"# Generated from {Path(constrain_dir).resolve()}/component_map.yaml\n")
        f.write(f"# Ports start at {start_port} — modify as needed.\n\n")
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    return output_path
