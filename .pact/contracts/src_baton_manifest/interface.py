# === Service Manifest Loader (src_baton_manifest) v1 ===
#  Dependencies: pathlib, yaml, baton.schemas
# Reads and parses baton-service.yaml files from service directories, converting them into ServiceManifest objects with dependency specifications.

# Module invariants:
#   - MANIFEST_FILENAME = 'baton-service.yaml'
#   - Default version is '0.0.0' if not specified
#   - Default port is 0 if not specified
#   - Default proxy_mode is 'http' if not specified
#   - Default role is 'service' if not specified
#   - Empty strings are used as defaults for api_spec, mock_spec, and command
#   - Empty dict is used as default for metadata
#   - Dependencies can be specified as strings or dicts in YAML

Path = primitive  # pathlib.Path type for file system paths

class ServiceManifest:
    """Imported from baton.schemas - represents a parsed service manifest"""
    pass

class DependencySpec:
    """Imported from baton.schemas - represents a service dependency"""
    pass

def load_manifest(
    service_dir: str | Path,
) -> ServiceManifest:
    """
    Load a ServiceManifest from baton-service.yaml in the given directory. Opens and reads the YAML file, validates it's not empty, and parses it into a ServiceManifest object.

    Preconditions:
      - service_dir must be a valid directory path
      - baton-service.yaml file must exist in service_dir

    Postconditions:
      - Returns a valid ServiceManifest object
      - File has been read and closed

    Errors:
      - manifest_not_found (FileNotFoundError): baton-service.yaml file does not exist in service_dir
          message: No baton-service.yaml found in {service_dir}
      - empty_manifest (ValueError): YAML file is empty or yaml.safe_load returns None
          message: Empty baton-service.yaml in {service_dir}
      - yaml_parse_error (yaml.YAMLError): YAML file contains invalid YAML syntax
      - io_error (IOError): File cannot be opened or read due to permissions or other IO issues

    Side effects: Reads file from disk at path {service_dir}/baton-service.yaml
    Idempotent: yes
    """
    ...

def _parse_manifest(
    raw: dict,
) -> ServiceManifest:
    """
    Parse raw YAML dict into ServiceManifest. Processes dependencies (converting strings and dicts to DependencySpec objects) and constructs a ServiceManifest with all fields, using defaults for missing values.

    Preconditions:
      - raw must contain 'name' key
      - raw must be a dictionary

    Postconditions:
      - Returns a ServiceManifest with all required and optional fields populated
      - Dependencies are converted to DependencySpec objects
      - Default values are applied for missing optional fields

    Errors:
      - missing_name (KeyError): raw dict does not contain 'name' key
          key: name
      - invalid_dependency_spec (TypeError): DependencySpec constructor fails due to invalid parameters
      - invalid_service_manifest (TypeError): ServiceManifest constructor fails due to invalid parameters

    Side effects: none
    Idempotent: yes
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['ServiceManifest', 'DependencySpec', 'load_manifest', '_parse_manifest']
