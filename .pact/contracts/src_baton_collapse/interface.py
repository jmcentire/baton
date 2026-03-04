# === Circuit Collapse Algorithm (src_baton_collapse) v1 ===
#  Dependencies: logging, pathlib, baton.adapter, baton.mock, baton.schemas
# Compresses the circuit by replacing non-live nodes with a single MockServer process that serves all their contracts simultaneously. Provides functions to build mock servers for non-live nodes and compute backend targets for mocked nodes.

# Module invariants:
#   - Service port calculation: service_port = node.port + 20000 if node.port + 20000 <= 65535 else node.port + 5000
#   - Egress nodes are always treated as non-live (mocked) regardless of the live_nodes parameter
#   - Both functions use identical logic for determining effective_live nodes and service_port calculation
#   - Mock server host is always '127.0.0.1' (localhost)

class CircuitSpec:
    """External type from baton.schemas representing a circuit specification with nodes"""
    pass

class MockServer:
    """External type from baton.mock representing a mock server that can serve multiple routes"""
    pass

class BackendTarget:
    """External type from baton.adapter representing a backend target with host and port"""
    pass

class NodeRole(Enum):
    """External type from baton.schemas representing node roles"""
    pass

def build_mock_server(
    circuit: CircuitSpec,
    live_nodes: set[str],
    project_dir: str | Path = .,
) -> MockServer:
    """
    Build a MockServer for all non-live nodes. For each mocked node, loads routes from contract spec if available, otherwise adds default health/status routes. Uses service port convention (port + 20000, or port + 5000 if exceeds 65535).

    Preconditions:
      - circuit must have a nodes attribute containing iterable of nodes
      - circuit must have an egress_nodes attribute containing iterable of nodes with name attribute
      - each node must have name, port, and contract attributes

    Postconditions:
      - Returns a MockServer instance configured for all non-live nodes
      - Egress nodes are always mocked regardless of live_nodes set
      - Each mocked node has routes added on service_port (node.port + 20000, or node.port + 5000 if > 65535)
      - Nodes with valid contracts get routes loaded from spec, otherwise get default routes

    Errors:
      - attribute_error (AttributeError): circuit lacks nodes or egress_nodes attribute, or node lacks required attributes
      - file_not_found (FileNotFoundError): contract file path does not exist when load_routes is called
      - type_error (TypeError): live_nodes is not a set or circuit.egress_nodes is not iterable

    Side effects: Logs info messages for each mocked node configuration, Reads contract specification files from filesystem if node.contract exists, Mutates the returned MockServer instance by adding routes
    Idempotent: no
    """
    ...

def compute_mock_backends(
    circuit: CircuitSpec,
    live_nodes: set[str],
) -> dict[str, BackendTarget]:
    """
    Compute backend targets for mocked nodes. Returns a mapping of node_name to BackendTarget pointing to the mock server's port for that node. Uses the same service port convention as build_mock_server.

    Preconditions:
      - circuit must have a nodes attribute containing iterable of nodes
      - circuit must have an egress_nodes attribute containing iterable of nodes with name attribute
      - each node must have name and port attributes

    Postconditions:
      - Returns a dictionary mapping node names to BackendTarget instances
      - Only non-live nodes are included in the result
      - Egress nodes are always included regardless of live_nodes set
      - Each BackendTarget has host='127.0.0.1' and port set to service_port (node.port + 20000, or node.port + 5000 if > 65535)
      - Service port calculation matches build_mock_server

    Errors:
      - attribute_error (AttributeError): circuit lacks nodes or egress_nodes attribute, or node lacks required attributes
      - type_error (TypeError): live_nodes is not a set or circuit.egress_nodes is not iterable

    Side effects: none
    Idempotent: no
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['CircuitSpec', 'MockServer', 'BackendTarget', 'NodeRole', 'build_mock_server', 'compute_mock_backends']
