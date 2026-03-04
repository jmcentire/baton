# === Adapter Control Server (src_baton_adapter_control) v1 ===
#  Dependencies: asyncio, json, logging, baton.adapter, baton.schemas
# A small HTTP server that runs on each adapter's management port, exposing REST endpoints for health checks (/health), metrics (/metrics), status information (/status), and routing configuration (/routing).

# Module invariants:
#   - _server is None when not running, asyncio.Server when running
#   - Supported HTTP paths are: /health, /metrics, /status, /routing
#   - All responses are JSON with Content-Type: application/json
#   - Request timeout is 5 seconds
#   - All connections use Connection: close header
#   - Status code mapping: 200='OK', 404='Not Found', 500='Internal Server Error'

class AdapterControlServer:
    """Management HTTP server for a single adapter that handles control API requests"""
    _adapter: Adapter                        # required, The adapter instance this control server manages
    _server: Optional[asyncio.Server]        # required, The underlying asyncio TCP server instance

def __init__(
    self: AdapterControlServer,
    adapter: Adapter,
) -> None:
    """
    Initialize the AdapterControlServer with an adapter instance. Sets up the server but does not start it.

    Preconditions:
      - adapter must be a valid Adapter instance

    Postconditions:
      - _adapter is set to the provided adapter
      - _server is initialized to None

    Side effects: mutates_state
    Idempotent: no
    """
    ...

def is_running(
    self: AdapterControlServer,
) -> bool:
    """
    Property that checks if the control server is currently running by verifying the server exists and is serving.

    Postconditions:
      - Returns True if _server is not None and is_serving() returns True
      - Returns False otherwise

    Side effects: none
    Idempotent: no
    """
    ...

def start(
    self: AdapterControlServer,
) -> None:
    """
    Start the control server on the adapter's management port. Creates an asyncio TCP server and begins listening for HTTP requests.

    Preconditions:
      - _adapter.node must have valid host and management_port attributes

    Postconditions:
      - _server is set to a running asyncio.Server instance
      - Server is listening on node.host:node.management_port
      - Log message is written with server details

    Errors:
      - OSError (OSError): Port already in use or binding fails
      - AttributeError (AttributeError): adapter.node does not have expected attributes

    Side effects: mutates_state, network_call, logging
    Idempotent: no
    """
    ...

def stop(
    self: AdapterControlServer,
) -> None:
    """
    Stop the control server if it is running. Closes the server and waits for all connections to close.

    Postconditions:
      - If _server was not None, it is closed and awaited
      - _server is set to None

    Side effects: mutates_state, network_call
    Idempotent: no
    """
    ...

def _handle(
    self: AdapterControlServer,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """
    Handle an incoming HTTP request to the control API. Parses HTTP request line, routes to appropriate handler based on path, and writes response. Supports GET requests to /health, /metrics, /status, /routing. Returns 404 for other paths.

    Preconditions:
      - reader and writer are valid asyncio stream objects

    Postconditions:
      - HTTP response is written to writer
      - writer is closed

    Errors:
      - TimeoutError (asyncio.TimeoutError): Reading request line takes more than 5 seconds
      - GenericException (Exception): Any exception during request handling is caught and logged

    Side effects: network_call, logging
    Idempotent: no
    """
    ...

def _handle_health(
    self: AdapterControlServer,
) -> str:
    """
    Handle GET /health endpoint. Calls adapter health_check and returns JSON with health status including node name, verdict, latency, and detail.

    Preconditions:
      - _adapter.health_check() must be callable

    Postconditions:
      - Returns JSON string with health data
      - JSON contains keys: node, verdict, latency_ms, detail

    Errors:
      - AttributeError (AttributeError): health object missing expected attributes

    Side effects: none
    Idempotent: no
    """
    ...

def _handle_metrics(
    self: AdapterControlServer,
) -> str:
    """
    Handle GET /metrics endpoint. Returns JSON with adapter metrics including request counts, status codes, bytes forwarded, latency statistics, and active connections.

    Preconditions:
      - _adapter.metrics must exist and have expected attributes

    Postconditions:
      - Returns JSON string with metrics data
      - JSON contains keys: requests_total, requests_failed, bytes_forwarded, last_latency_ms, status_2xx, status_3xx, status_4xx, status_5xx, active_connections, latency_p50, latency_p95, latency_p99

    Errors:
      - AttributeError (AttributeError): metrics object missing expected attributes or methods

    Side effects: none
    Idempotent: no
    """
    ...

def _handle_status(
    self: AdapterControlServer,
) -> str:
    """
    Handle GET /status endpoint. Returns JSON with adapter status including node name, listening address, proxy mode, backend configuration, and routing strategy if applicable.

    Preconditions:
      - _adapter.node, _adapter.backend, and _adapter.routing must be accessible

    Postconditions:
      - Returns JSON string with status data
      - JSON contains keys: node, listening, mode, backend, running
      - If routing exists, JSON also contains routing_strategy and routing_locked

    Errors:
      - AttributeError (AttributeError): adapter objects missing expected attributes

    Side effects: none
    Idempotent: no
    """
    ...

def _handle_routing(
    self: AdapterControlServer,
) -> str:
    """
    Handle GET /routing endpoint. Returns JSON with routing configuration. If no routing object exists, returns single backend strategy. Otherwise returns routing model dump.

    Postconditions:
      - Returns JSON string with routing configuration
      - If routing is None, returns single strategy with backend info
      - If routing exists, returns routing.model_dump() as JSON

    Errors:
      - AttributeError (AttributeError): routing object missing model_dump method or backend missing attributes

    Side effects: none
    Idempotent: no
    """
    ...

def _write_response(
    writer: asyncio.StreamWriter,
    status: int,
    body: str,
) -> None:
    """
    Static method to write an HTTP response with given status code and JSON body to the writer stream. Constructs HTTP/1.1 response headers and body.

    Preconditions:
      - writer must be a valid StreamWriter
      - status should be a valid HTTP status code
      - body should be a valid string

    Postconditions:
      - HTTP response headers are written to writer
      - Response body is written to writer
      - Content-Type is set to application/json
      - Connection is set to close

    Errors:
      - UnicodeEncodeError (UnicodeEncodeError): body contains characters that cannot be UTF-8 encoded

    Side effects: network_call
    Idempotent: no
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['AdapterControlServer', 'is_running', 'start', 'stop', '_handle', '_handle_health', '_handle_metrics', '_handle_status', '_handle_routing', '_write_response', 'UnicodeEncodeError']
