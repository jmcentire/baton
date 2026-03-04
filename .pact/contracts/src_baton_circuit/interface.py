# === Circuit Graph Operations (src_baton_circuit) v1 ===
#  Dependencies: baton.schemas
# Pure functions that operate on frozen CircuitSpec models and return new instances. Provides graph manipulation operations for circuit specifications including node/edge management, cycle detection, and topological sorting.

# Module invariants:
#   - DEFAULT_PORT_START = 9001
#   - DEFAULT_PORT_MAX = 9999
#   - All functions are pure (return new instances, do not mutate inputs)
#   - All CircuitSpec modifications preserve name and version fields
#   - Port range for auto-assignment is [9001, 9999] inclusive

def add_node(
    circuit: CircuitSpec,
    name: str,
    port: int = 0,
    proxy_mode: str = "http",
    contract: str = "",
    role: str = "service",
) -> CircuitSpec:
    """
    Add a node to the circuit. Auto-assigns port if not specified (port=0). Creates a new CircuitSpec with the added node.

    Preconditions:
      - Node with given name must not already exist in circuit
      - If port=0, there must be an available port in range [9001, 9999]

    Postconditions:
      - Returns new CircuitSpec with added node
      - Original circuit is unchanged (pure function)
      - New circuit has same name and version as original
      - New circuit has all original nodes plus new node
      - New circuit has all original edges unchanged

    Errors:
      - duplicate_node (ValueError): Node with given name already exists in circuit
          message: Node '{name}' already exists
      - no_available_port (RuntimeError): port=0 and all ports in range [9001, 9999] are used
          message: No available ports in range

    Side effects: none
    Idempotent: no
    """
    ...

def remove_node(
    circuit: CircuitSpec,
    name: str,
) -> CircuitSpec:
    """
    Remove a node and all its edges from the circuit. Returns new CircuitSpec without the specified node.

    Preconditions:
      - Node with given name must exist in circuit

    Postconditions:
      - Returns new CircuitSpec without the specified node
      - Original circuit is unchanged (pure function)
      - New circuit has same name and version as original
      - All edges where node is source or target are removed
      - All other nodes and edges remain unchanged

    Errors:
      - node_not_found (ValueError): Node with given name does not exist in circuit
          message: Node '{name}' not found

    Side effects: none
    Idempotent: no
    """
    ...

def add_edge(
    circuit: CircuitSpec,
    source: str,
    target: str,
    label: str = "",
) -> CircuitSpec:
    """
    Add a directed edge between two nodes. Creates a new CircuitSpec with the added edge.

    Preconditions:
      - Source node must exist in circuit
      - Target node must exist in circuit
      - Edge from source to target must not already exist

    Postconditions:
      - Returns new CircuitSpec with added edge
      - Original circuit is unchanged (pure function)
      - New circuit has same name and version as original
      - New circuit has all original nodes unchanged
      - New circuit has all original edges plus new edge

    Errors:
      - source_not_found (ValueError): Source node does not exist in circuit
          message: Source node '{source}' not found
      - target_not_found (ValueError): Target node does not exist in circuit
          message: Target node '{target}' not found
      - duplicate_edge (ValueError): Edge from source to target already exists
          message: Edge {source} -> {target} already exists

    Side effects: none
    Idempotent: no
    """
    ...

def remove_edge(
    circuit: CircuitSpec,
    source: str,
    target: str,
) -> CircuitSpec:
    """
    Remove a directed edge from the circuit. Returns new CircuitSpec without the specified edge.

    Preconditions:
      - Edge from source to target must exist in circuit

    Postconditions:
      - Returns new CircuitSpec without the specified edge
      - Original circuit is unchanged (pure function)
      - New circuit has same name and version as original
      - New circuit has all original nodes unchanged
      - All other edges remain unchanged

    Errors:
      - edge_not_found (ValueError): Edge from source to target does not exist in circuit
          message: Edge {source} -> {target} not found

    Side effects: none
    Idempotent: no
    """
    ...

def set_contract(
    circuit: CircuitSpec,
    node_name: str,
    contract_path: str,
) -> CircuitSpec:
    """
    Set the contract spec path for a node. Returns new CircuitSpec with updated node contract.

    Preconditions:
      - Node with given name must exist in circuit

    Postconditions:
      - Returns new CircuitSpec with updated node contract
      - Original circuit is unchanged (pure function)
      - New circuit has same name and version as original
      - Specified node has contract field updated to contract_path
      - All other node fields and all other nodes remain unchanged
      - All edges remain unchanged

    Errors:
      - node_not_found (ValueError): Node with given name does not exist in circuit
          message: Node '{node_name}' not found

    Side effects: none
    Idempotent: no
    """
    ...

def has_cycle(
    circuit: CircuitSpec,
) -> bool:
    """
    Check if the circuit's edge graph contains a cycle using depth-first search with color marking (WHITE=0, GRAY=1, BLACK=2).

    Postconditions:
      - Returns True if circuit contains at least one cycle
      - Returns False if circuit is acyclic (DAG)
      - Original circuit is unchanged (pure function)

    Side effects: none
    Idempotent: no
    """
    ...

def topological_sort(
    circuit: CircuitSpec,
) -> list[str]:
    """
    Return node names in topological order (dependencies first) using Kahn's algorithm with sorted queue for deterministic ordering.

    Preconditions:
      - Circuit must not contain a cycle (must be a DAG)

    Postconditions:
      - Returns list of node names in topological order
      - For every edge (u, v), u appears before v in the result
      - Original circuit is unchanged (pure function)
      - Result is deterministic (queue is sorted at each step)

    Errors:
      - contains_cycle (ValueError): Circuit contains a cycle
          message: Circuit contains a cycle

    Side effects: none
    Idempotent: no
    """
    ...

def _next_port(
    circuit: CircuitSpec,
) -> int:
    """
    Find the next available port in the range [DEFAULT_PORT_START, DEFAULT_PORT_MAX]. Internal helper function for port auto-assignment.

    Preconditions:
      - At least one port in range [9001, 9999] must be available

    Postconditions:
      - Returns the first available port in ascending order from 9001
      - Returned port is not used by any node in the circuit
      - Original circuit is unchanged (pure function)

    Errors:
      - no_available_ports (RuntimeError): All ports in range [9001, 9999] are used by circuit nodes
          message: No available ports in range

    Side effects: none
    Idempotent: no
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['add_node', 'remove_node', 'add_edge', 'remove_edge', 'set_contract', 'has_cycle', 'topological_sort', '_next_port']
