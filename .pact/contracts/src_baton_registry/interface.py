# === Service Registry and Circuit Derivation (src_baton_registry) v1 ===
#  Dependencies: pathlib, baton.circuit, baton.manifest, baton.schemas
# Pure functions that load service manifests from directories and derive CircuitSpec configurations by assigning ports, resolving dependencies, and creating node/edge specifications for service orchestration.

# Module invariants:
#   - DEFAULT_PORT_START and DEFAULT_PORT_MAX define the valid port range for auto-assignment
#   - All functions are pure except load_manifests which reads from filesystem
#   - Service names must be unique across all loaded manifests
#   - Ports must be unique across all nodes in a circuit
#   - EdgeSpec edges always have label 'depends-on'
#   - CircuitSpec version is always set to 1

class ServiceManifest:
    """External type from baton.schemas representing a service manifest with name, port, dependencies, proxy_mode, role, metadata, mock_spec, and api_spec fields"""
    pass

class CircuitSpec:
    """External type from baton.schemas representing a circuit specification with name, version, nodes, and edges"""
    pass

class NodeSpec:
    """External type from baton.schemas representing a node in the circuit with name, port, proxy_mode, contract, role, and metadata"""
    pass

class EdgeSpec:
    """External type from baton.schemas representing an edge in the circuit with source, target, and label"""
    pass

def load_manifests(
    service_dirs: list[str | Path],
) -> list[ServiceManifest]:
    """
    Load manifests from multiple service directories and validate that all service names are unique

    Postconditions:
      - All service names in returned manifests are unique
      - Length of returned list equals length of service_dirs input

    Errors:
      - duplicate_service_names (ValueError): Two or more manifests have the same service name
          message: Duplicate service names: {dupes}
      - manifest_load_failure (Exception): load_manifest raises an exception for any directory
          message: Propagates exceptions from load_manifest

    Side effects: Reads manifest files from each directory via load_manifest
    Idempotent: no
    """
    ...

def derive_circuit(
    manifests: list[ServiceManifest],
    circuit_name: str = default,
) -> CircuitSpec:
    """
    Derive a CircuitSpec from a list of service manifests by creating nodes with auto-assigned ports, resolving dependencies, and creating edges

    Postconditions:
      - Each manifest results in exactly one NodeSpec in the circuit
      - All nodes have unique ports assigned
      - Ports are assigned from DEFAULT_PORT_START to DEFAULT_PORT_MAX range when manifest.port == 0
      - Each non-optional dependency that exists creates an EdgeSpec from consumer to provider
      - Optional dependencies that are missing are silently skipped
      - All edges have label 'depends-on'
      - CircuitSpec.version is set to 1

    Errors:
      - port_conflict (ValueError): Two or more manifests specify the same non-zero port
          message: Port conflict for service '{m.name}': {port}
      - missing_required_dependency (ValueError): A manifest has a required (non-optional) dependency on a service name not in the manifests list
          message: Service '{m.name}' depends on '{dep.name}' which is not registered
      - no_available_ports (RuntimeError): All ports in the range DEFAULT_PORT_START to DEFAULT_PORT_MAX are already used when trying to auto-assign a port
          message: No available ports in range

    Side effects: none
    Idempotent: no
    """
    ...

def _next_port(
    used: set[int],
) -> int:
    """
    Find the next available port in the default range (DEFAULT_PORT_START to DEFAULT_PORT_MAX) that is not in the used set

    Postconditions:
      - Returned port is in range [DEFAULT_PORT_START, DEFAULT_PORT_MAX]
      - Returned port is not in the used set

    Errors:
      - no_available_ports (RuntimeError): All ports in the range DEFAULT_PORT_START to DEFAULT_PORT_MAX are already in the used set
          message: No available ports in range

    Side effects: none
    Idempotent: no
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['ServiceManifest', 'CircuitSpec', 'NodeSpec', 'EdgeSpec', 'load_manifests', 'derive_circuit', '_next_port']
