# === Baton Configuration Loader (src_baton_config) v1 ===
#  Dependencies: pathlib, yaml, baton.schemas, baton.registry, baton.manifest
# Configuration loading for Baton. Reads baton.yaml from a project directory and produces a CircuitSpec. Supports both topology-first (baton.yaml nodes/edges) and service-first (baton-service.yaml manifests) workflows.

# Module invariants:
#   - CONFIG_FILENAME = 'baton.yaml'
#   - Default circuit name is 'default'
#   - Default circuit version is 1
#   - Default node host is '127.0.0.1'
#   - Default node proxy_mode is 'http'
#   - Default node role is 'service'

Path = primitive  # pathlib.Path type for filesystem paths

class CircuitSpec:
    """Schema object representing a circuit configuration from baton.schemas"""
    pass

class NodeSpec:
    """Schema object representing a node in the circuit from baton.schemas"""
    pass

class EdgeSpec:
    """Schema object representing an edge in the circuit from baton.schemas"""
    pass

def load_circuit(
    project_dir: str | Path,
) -> CircuitSpec:
    """
    Load CircuitSpec from baton.yaml in the given directory. Returns an empty CircuitSpec if the YAML file contains only null/empty content.

    Preconditions:
      - project_dir must be a valid path
      - baton.yaml must exist in project_dir

    Postconditions:
      - Returns a CircuitSpec object parsed from YAML
      - Returns empty CircuitSpec() if YAML content is None

    Errors:
      - file_not_found (FileNotFoundError): baton.yaml does not exist in project_dir
          message: No baton.yaml found in {project_dir}
      - yaml_parse_error (yaml.YAMLError): YAML content is malformed
      - file_read_error (OSError): Cannot open or read the file

    Side effects: Reads baton.yaml file from filesystem
    Idempotent: no
    """
    ...

def save_circuit(
    circuit: CircuitSpec,
    project_dir: str | Path,
) -> None:
    """
    Save CircuitSpec to baton.yaml in the given directory. Serializes the CircuitSpec and writes it as YAML with no flow style and unsorted keys.

    Preconditions:
      - project_dir must be a valid path
      - circuit must be a valid CircuitSpec object

    Postconditions:
      - baton.yaml file is written to project_dir with serialized circuit data
      - YAML is formatted with default_flow_style=False and sort_keys=False

    Errors:
      - file_write_error (OSError): Cannot write to the file or directory
      - yaml_dump_error (yaml.YAMLError): Circuit data cannot be serialized to YAML

    Side effects: Writes baton.yaml file to filesystem
    Idempotent: no
    """
    ...

def load_circuit_from_services(
    project_dir: str | Path,
    service_dirs: list[str | Path] | None = None,
) -> CircuitSpec:
    """
    Derive CircuitSpec from service manifests. If service_dirs is None, discovers them from baton.yaml's 'services' key or by scanning subdirectories for baton-service.yaml files. Loads manifests and derives a circuit using the registry module.

    Preconditions:
      - project_dir must be a valid path
      - If service_dirs is None, discoverable service directories must exist

    Postconditions:
      - Returns CircuitSpec derived from service manifests
      - Circuit name is extracted from baton.yaml if it exists, otherwise defaults to 'default'

    Errors:
      - no_services_found (FileNotFoundError): service_dirs is empty after discovery
          message: No service directories found
      - yaml_parse_error (yaml.YAMLError): Cannot parse baton.yaml when reading circuit name
      - manifest_load_error (Exception): load_manifests fails to load service manifests
      - derive_circuit_error (Exception): derive_circuit fails to create CircuitSpec

    Side effects: Reads baton.yaml if it exists, Calls external functions load_manifests and derive_circuit from baton.registry, May read multiple service manifest files
    Idempotent: no
    """
    ...

def _discover_service_dirs(
    project_dir: Path,
) -> list[Path]:
    """
    Auto-discover service directories. First checks baton.yaml for a 'services' list of paths. Otherwise, scans immediate subdirectories for baton-service.yaml files.

    Preconditions:
      - project_dir must be a Path object

    Postconditions:
      - Returns list of Path objects for discovered service directories
      - Returns empty list if no services found
      - Service directories are sorted if discovered by scanning

    Errors:
      - yaml_parse_error (yaml.YAMLError): Cannot parse baton.yaml
      - file_read_error (OSError): Cannot read baton.yaml

    Side effects: Reads baton.yaml if it exists, Iterates through subdirectories to check for baton-service.yaml
    Idempotent: no
    """
    ...

def add_service_path(
    project_dir: str | Path,
    service_path: str,
) -> None:
    """
    Add a service directory path to baton.yaml's services list. Reads existing config, appends service_path if not already present, and writes back to file.

    Preconditions:
      - baton.yaml must exist in project_dir

    Postconditions:
      - service_path is added to services list in baton.yaml if not already present
      - baton.yaml is updated with new services list
      - If service_path already exists in list, no duplicate is added

    Errors:
      - file_not_found (FileNotFoundError): baton.yaml does not exist in project_dir
          message: No baton.yaml found in {project_dir}
      - yaml_parse_error (yaml.YAMLError): Cannot parse existing baton.yaml
      - file_write_error (OSError): Cannot write updated config back to file

    Side effects: Reads baton.yaml from filesystem, Writes updated baton.yaml to filesystem
    Idempotent: no
    """
    ...

def _parse_circuit(
    raw: dict,
) -> CircuitSpec:
    """
    Parse raw YAML dict into CircuitSpec. Extracts nodes and edges from the dictionary and constructs NodeSpec and EdgeSpec objects.

    Preconditions:
      - raw must be a dictionary

    Postconditions:
      - Returns CircuitSpec with parsed nodes and edges
      - name defaults to 'default' if not in raw dict
      - version defaults to 1 if not in raw dict
      - nodes and edges default to empty lists if not in raw dict

    Errors:
      - node_spec_error (TypeError): Node data cannot be unpacked into NodeSpec
      - edge_spec_error (TypeError): Edge data cannot be unpacked into EdgeSpec
      - circuit_spec_error (TypeError): CircuitSpec constructor fails with provided data

    Side effects: none
    Idempotent: no
    """
    ...

def _serialize_circuit(
    circuit: CircuitSpec,
) -> dict:
    """
    Convert CircuitSpec to a YAML-serializable dict. Selectively includes fields based on non-default values (host != '127.0.0.1', proxy_mode != 'http', role != 'service', etc.).

    Preconditions:
      - circuit must be a valid CircuitSpec object

    Postconditions:
      - Returns dictionary with name and version always present
      - nodes list included if circuit.nodes is non-empty
      - edges list included if circuit.edges is non-empty
      - Node fields only included if they differ from defaults
      - Edge label only included if present

    Errors:
      - attribute_error (AttributeError): CircuitSpec object missing expected attributes

    Side effects: none
    Idempotent: no
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['CircuitSpec', 'NodeSpec', 'EdgeSpec', 'load_circuit', 'save_circuit', 'load_circuit_from_services', '_discover_service_dirs', 'add_service_path', '_parse_circuit', '_serialize_circuit']
