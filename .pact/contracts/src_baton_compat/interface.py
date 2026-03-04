# === Static Compatibility Analysis (src_baton_compat) v1 ===
#  Dependencies: json, dataclasses, pathlib, typing, yaml, baton.schemas
# Compares expected dependency interfaces against exposed service APIs. Performs static compatibility checks by loading OpenAPI specs and verifying that consumer expected APIs are satisfied by provider exposed APIs through structural subtyping.

# Module invariants:
#   - CompatReport.compatible is False if any error-severity issue exists in issues list
#   - HTTP methods in path mappings are always uppercase
#   - Missing files result in empty dict rather than exceptions in _load_api_paths
#   - Schema comparison uses structural subtyping (provider can have extra fields)

class CompatIssue:
    """A single compatibility issue (frozen dataclass)"""
    consumer: str                            # required, Name of the consuming service
    provider: str                            # required, Name of the providing service
    path: str                                # required, API path where the issue occurs
    method: str                              # required, HTTP method where the issue occurs
    severity: str                            # required, Severity level: 'error' or 'warning'
    detail: str                              # required, Detailed description of the compatibility issue

class CompatReport:
    """Result of a compatibility check (mutable dataclass)"""
    compatible: bool = True                  # optional, Whether the services are compatible
    issues: list[CompatIssue] = []           # optional, List of compatibility issues found

class PathMapping:
    """Type alias for the return type of _load_api_paths"""
    path: str                                # required, API path string
    methods: dict[str, Any]                  # required, Dictionary mapping HTTP method (uppercase) to response schema or None

def check_compatibility(
    provider: ServiceManifest,
    consumers: list[ServiceManifest],
    base_dir: str | Path = ".",
) -> CompatReport:
    """
    Check if a provider service is compatible with all consumers. Loads consumer expected APIs and provider API specs from OpenAPI files, then verifies that all expected paths/methods exist and schemas are structurally compatible.

    Postconditions:
      - Returns a CompatReport with compatible=True if no error-severity issues found
      - All consumers depending on provider are checked
      - Only consumers with expected_api defined are validated

    Errors:
      - FileNotFoundError (FileNotFoundError): If base_dir path is invalid when converted to Path
      - YAMLError (yaml.YAMLError): If YAML spec files are malformed (propagated from _load_api_paths)
      - JSONDecodeError (json.JSONDecodeError): If JSON spec files are malformed (propagated from _load_api_paths)
      - AttributeError (AttributeError): If provider or consumers have missing attributes (name, api_spec, dependencies)

    Side effects: Reads OpenAPI spec files from filesystem via _load_api_paths
    Idempotent: no
    """
    ...

def _load_api_paths(
    base: Path,
    spec_path: str,
) -> dict[str, dict[str, Any]]:
    """
    Load OpenAPI paths from a spec file (YAML or JSON). Parses the 'paths' section and extracts HTTP methods with their success response schemas. Skips methods starting with 'x-' and 'parameters'.

    Postconditions:
      - Returns empty dict {} if file does not exist
      - Returns empty dict {} if spec is None or lacks 'paths' key
      - All method keys in returned dict are uppercase
      - Methods starting with 'x-' or equal to 'parameters' are excluded

    Errors:
      - YAMLError (yaml.YAMLError): If YAML file is malformed
      - JSONDecodeError (json.JSONDecodeError): If JSON file is malformed
      - OSError (OSError): If file cannot be opened or read

    Side effects: Reads file from filesystem
    Idempotent: no
    """
    ...

def _extract_response_schema(
    operation: dict,
    components: dict,
) -> Any:
    """
    Extract the success response schema (200 or 201) from an OpenAPI operation definition. Resolves $ref references to components/schemas.

    Postconditions:
      - Returns None if no schema found or empty schema
      - Returns resolved schema dict if $ref is present
      - Prioritizes 200 response over 201
      - Only extracts application/json content

    Errors:
      - IndexError (IndexError): If $ref string does not contain '/' separator
      - KeyError (KeyError): If schema references are malformed or missing

    Side effects: none
    Idempotent: no
    """
    ...

def _compare_paths(
    consumer: str,
    provider: str,
    expected: dict[str, dict[str, Any]],
    actual: dict[str, dict[str, Any]],
    report: CompatReport,
) -> None:
    """
    Compare expected paths/methods against actual provider paths. Adds CompatIssue errors to report for missing paths or methods, and delegates to _compare_schemas for schema validation when both expected and actual schemas exist.

    Postconditions:
      - All missing paths result in error-severity CompatIssue added to report
      - All missing methods result in error-severity CompatIssue added to report
      - Schema comparison is only performed when both expected and actual schemas are truthy

    Side effects: Mutates report by adding CompatIssue objects
    Idempotent: no
    """
    ...

def _compare_schemas(
    consumer: str,
    provider: str,
    path: str,
    method: str,
    expected: dict,
    actual: dict,
    report: CompatReport,
) -> None:
    """
    Structural subtype check: validates that expected schema fields exist in actual schema. Performs recursive validation for array item types. Provider can return extra fields (structural subtyping).

    Postconditions:
      - Type mismatch results in error and early return
      - For object types: missing required properties result in error
      - For array types: recursively validates item schemas
      - Extra fields in actual are allowed (structural subtyping)

    Side effects: Mutates report by adding CompatIssue objects, Recursively calls itself for array item validation
    Idempotent: no
    """
    ...

def add(
    self: CompatReport,
    issue: CompatIssue,
) -> None:
    """
    Add a compatibility issue to the report. Appends issue to issues list and sets compatible to False if severity is 'error'.

    Postconditions:
      - issue is appended to self.issues
      - self.compatible is set to False if issue.severity == 'error'
      - self.compatible remains unchanged if severity is not 'error'

    Side effects: Mutates self.issues list, May mutate self.compatible boolean
    Idempotent: no
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['CompatIssue', 'CompatReport', 'PathMapping', 'check_compatibility', '_load_api_paths', '_extract_response_schema', '_compare_paths', '_compare_schemas', 'add']
