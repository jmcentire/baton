# === Mock Server Generation (src_baton_mock) v1 ===
#  Dependencies: asyncio, json, logging, random, string, pathlib, typing, yaml
# Mock server generation from contract specs. Generates asyncio HTTP servers that serve valid responses for endpoints defined in OpenAPI or JSON Schema specs. A single MockServer can serve multiple ports simultaneously (for collapsed circuits).

# Module invariants:
#   - logger is initialized with module name __name__
#   - Default host for servers is 127.0.0.1
#   - HTTP responses use application/json content type
#   - Request timeout is 5.0 seconds
#   - Default string format generates 5 lowercase letters
#   - Default integer range is 1-100
#   - Default number range is 0-100 with 2 decimal places
#   - Boolean schema always generates True
#   - Array default minItems is 1
#   - Object generates all required fields (defaults to all properties if not specified)
#   - Mock server uses HTTP/1.1 protocol
#   - Connections use 'close' connection header

class MockServer:
    """In-process mock HTTP server serving canned responses. Can serve routes for multiple ports simultaneously (collapsed mode)."""
    _route_tables: dict[int, dict[str, dict[str, Any]]] # required, Mapping of port to route table (path to method to response body)
    _servers: list[asyncio.Server]           # required, List of running asyncio servers

class RouteTable:
    """Route table mapping paths to HTTP methods to response bodies"""
    path: str                                # required, HTTP path
    method: str                              # required, HTTP method (GET, POST, etc.)
    response_body: Any                       # required, Response body to return

def generate_instance(
    schema: dict,
) -> Any:
    """
    Generate a random valid instance from a JSON Schema. Returns example/default if present, otherwise generates based on schema type.

    Postconditions:
      - Returns value from 'example' field if present
      - Returns value from 'default' field if present and no example
      - Returns first enum value if 'enum' present
      - For strings: returns formatted value based on format field or random lowercase string
      - For integers: returns random int between minimum (default 1) and maximum (default 100)
      - For numbers: returns random float between 0 and 100 rounded to 2 decimals
      - For booleans: returns True
      - For arrays: returns list with minItems (default 1) generated instances
      - For objects: returns dict with all required fields generated
      - Returns None for unrecognized types

    Side effects: none
    Idempotent: no
    """
    ...

def parse_openapi(
    spec_path: str,
) -> dict[str, dict[str, Any]]:
    """
    Parse an OpenAPI 3.x spec and return route table. Returns mapping of path to HTTP method to response body.

    Postconditions:
      - Returns empty dict if spec is None or has no 'paths' key
      - Returns route table with paths as keys
      - Each path maps HTTP method (uppercase) to response body
      - Response body generated from 200 or 201 success response schema
      - Resolves $ref references from components/schemas
      - Prefers explicit examples over generated instances
      - Skips methods starting with 'x-' or named 'parameters'

    Errors:
      - file_not_found (FileNotFoundError): spec_path does not exist
      - parse_error (yaml.YAMLError or json.JSONDecodeError): YAML or JSON parsing fails

    Side effects: reads_file
    Idempotent: no
    """
    ...

def parse_json_schema(
    spec_path: str,
) -> dict[str, dict[str, Any]]:
    """
    Parse a JSON Schema and return a single-endpoint route table with GET / endpoint.

    Postconditions:
      - Returns dict with single key '/'
      - Root path maps 'GET' to generated instance from schema

    Errors:
      - file_not_found (FileNotFoundError): spec_path does not exist
      - parse_error (json.JSONDecodeError): JSON parsing fails

    Side effects: reads_file
    Idempotent: no
    """
    ...

def load_routes(
    spec_path: str,
) -> dict[str, dict[str, Any]]:
    """
    Load routes from a spec file with auto-detection of format (OpenAPI or JSON Schema). Returns empty dict if file not found or parsing fails.

    Postconditions:
      - Returns empty dict if file does not exist (logs warning)
      - Returns empty dict if parsing raises exception
      - Detects OpenAPI if data contains 'openapi' or 'paths' key
      - Detects JSON Schema if data contains 'type' or 'properties' key
      - Returns empty dict for unrecognized formats

    Side effects: reads_file, logging
    Idempotent: no
    """
    ...

def __init__(
    self: MockServer,
) -> None:
    """
    Initialize MockServer with empty route tables and server list.

    Postconditions:
      - _route_tables is empty dict
      - _servers is empty list

    Side effects: none
    Idempotent: no
    """
    ...

def add_routes(
    self: MockServer,
    port: int,
    routes: dict[str, dict[str, Any]],
) -> None:
    """
    Register routes for a specific port.

    Postconditions:
      - _route_tables[port] is set to routes
      - Overwrites existing routes for port if any

    Side effects: mutates_state
    Idempotent: no
    """
    ...

def add_default_routes(
    self: MockServer,
    port: int,
) -> None:
    """
    Add default health endpoint for a port with no contract. Adds GET / and GET /health.

    Postconditions:
      - _route_tables[port] contains GET / returning {status: 'mock', port: <port>}
      - _route_tables[port] contains GET /health returning {status: 'ok'}
      - Overwrites existing routes for port if any

    Side effects: mutates_state
    Idempotent: no
    """
    ...

def start(
    self: MockServer,
    host: str = 127.0.0.1,
) -> None:
    """
    Start HTTP servers for all registered ports. Creates asyncio servers listening on specified host.

    Postconditions:
      - Creates asyncio server for each port in _route_tables
      - Appends each server to _servers list
      - Logs info message for each started server with host, port, and route count

    Errors:
      - port_in_use (OSError): Port is already bound

    Side effects: mutates_state, network_call, logging
    Idempotent: no
    """
    ...

def stop(
    self: MockServer,
) -> None:
    """
    Stop all running servers. Closes servers and waits for cleanup.

    Postconditions:
      - All servers in _servers are closed
      - _servers list is cleared

    Side effects: mutates_state, network_call
    Idempotent: no
    """
    ...

def is_running(
    self: MockServer,
) -> bool:
    """
    Property that returns whether any servers are currently running.

    Postconditions:
      - Returns True if _servers is non-empty
      - Returns False if _servers is empty

    Side effects: none
    Idempotent: no
    """
    ...

def _handle(
    self: MockServer,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    port: int,
) -> None:
    """
    Handle an HTTP request: parse request line, match route from port's route table, return canned JSON response (200 OK or 404 Not Found). Implements basic HTTP/1.1 protocol with 5 second timeout on initial read.

    Postconditions:
      - Reads HTTP request line with 5 second timeout
      - Reads and discards remaining headers until blank line
      - Parses method (default GET) and path (default /) from request line
      - Looks up route in _route_tables[port][path][method]
      - Tries alternate path without trailing slash if not found
      - Returns 404 JSON response if route not found
      - Returns 200 JSON response with route body if found
      - Closes writer connection
      - Logs debug message on exception

    Errors:
      - timeout (asyncio.TimeoutError): Request line not received within 5 seconds

    Side effects: network_call, logging
    Idempotent: no
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['MockServer', 'RouteTable', 'generate_instance', 'parse_openapi', 'parse_json_schema', 'load_routes', 'add_routes', 'add_default_routes', 'start', 'stop', 'is_running', '_handle']
