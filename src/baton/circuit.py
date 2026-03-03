"""Circuit graph operations.

Pure functions that operate on frozen CircuitSpec models and return new instances.
"""

from __future__ import annotations

from baton.schemas import CircuitSpec, EdgeSpec, NodeSpec

DEFAULT_PORT_START = 9001
DEFAULT_PORT_MAX = 9999


def add_node(
    circuit: CircuitSpec,
    name: str,
    port: int = 0,
    proxy_mode: str = "http",
    contract: str = "",
) -> CircuitSpec:
    """Add a node to the circuit. Auto-assigns port if not specified."""
    if circuit.node_by_name(name) is not None:
        raise ValueError(f"Node '{name}' already exists")
    if port == 0:
        port = _next_port(circuit)
    node = NodeSpec(name=name, port=port, proxy_mode=proxy_mode, contract=contract)
    return CircuitSpec(
        name=circuit.name,
        version=circuit.version,
        nodes=[*circuit.nodes, node],
        edges=list(circuit.edges),
    )


def remove_node(circuit: CircuitSpec, name: str) -> CircuitSpec:
    """Remove a node and all its edges from the circuit."""
    if circuit.node_by_name(name) is None:
        raise ValueError(f"Node '{name}' not found")
    return CircuitSpec(
        name=circuit.name,
        version=circuit.version,
        nodes=[n for n in circuit.nodes if n.name != name],
        edges=[e for e in circuit.edges if e.source != name and e.target != name],
    )


def add_edge(circuit: CircuitSpec, source: str, target: str, label: str = "") -> CircuitSpec:
    """Add a directed edge between two nodes."""
    if circuit.node_by_name(source) is None:
        raise ValueError(f"Source node '{source}' not found")
    if circuit.node_by_name(target) is None:
        raise ValueError(f"Target node '{target}' not found")
    for e in circuit.edges:
        if e.source == source and e.target == target:
            raise ValueError(f"Edge {source} -> {target} already exists")
    edge = EdgeSpec(source=source, target=target, label=label)
    return CircuitSpec(
        name=circuit.name,
        version=circuit.version,
        nodes=list(circuit.nodes),
        edges=[*circuit.edges, edge],
    )


def remove_edge(circuit: CircuitSpec, source: str, target: str) -> CircuitSpec:
    """Remove a directed edge."""
    found = False
    new_edges = []
    for e in circuit.edges:
        if e.source == source and e.target == target:
            found = True
        else:
            new_edges.append(e)
    if not found:
        raise ValueError(f"Edge {source} -> {target} not found")
    return CircuitSpec(
        name=circuit.name,
        version=circuit.version,
        nodes=list(circuit.nodes),
        edges=new_edges,
    )


def set_contract(circuit: CircuitSpec, node_name: str, contract_path: str) -> CircuitSpec:
    """Set the contract spec path for a node."""
    if circuit.node_by_name(node_name) is None:
        raise ValueError(f"Node '{node_name}' not found")
    new_nodes = []
    for n in circuit.nodes:
        if n.name == node_name:
            new_nodes.append(NodeSpec(
                name=n.name,
                host=n.host,
                port=n.port,
                proxy_mode=n.proxy_mode,
                contract=contract_path,
                management_port=n.management_port,
                metadata=dict(n.metadata),
            ))
        else:
            new_nodes.append(n)
    return CircuitSpec(
        name=circuit.name,
        version=circuit.version,
        nodes=new_nodes,
        edges=list(circuit.edges),
    )


def has_cycle(circuit: CircuitSpec) -> bool:
    """Check if the circuit's edge graph contains a cycle."""
    adj: dict[str, list[str]] = {n.name: [] for n in circuit.nodes}
    for e in circuit.edges:
        adj[e.source].append(e.target)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {name: WHITE for name in adj}

    def dfs(node: str) -> bool:
        color[node] = GRAY
        for neighbor in adj[node]:
            if color[neighbor] == GRAY:
                return True
            if color[neighbor] == WHITE and dfs(neighbor):
                return True
        color[node] = BLACK
        return False

    return any(dfs(name) for name, c in color.items() if c == WHITE)


def topological_sort(circuit: CircuitSpec) -> list[str]:
    """Return node names in topological order (dependencies first).

    Raises ValueError if the graph has a cycle.
    """
    if has_cycle(circuit):
        raise ValueError("Circuit contains a cycle")

    adj: dict[str, list[str]] = {n.name: [] for n in circuit.nodes}
    in_degree: dict[str, int] = {n.name: 0 for n in circuit.nodes}
    for e in circuit.edges:
        adj[e.source].append(e.target)
        in_degree[e.target] += 1

    queue = [name for name, deg in in_degree.items() if deg == 0]
    result: list[str] = []
    while queue:
        queue.sort()
        node = queue.pop(0)
        result.append(node)
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return result


def _next_port(circuit: CircuitSpec) -> int:
    """Find the next available port."""
    used = {n.port for n in circuit.nodes}
    for port in range(DEFAULT_PORT_START, DEFAULT_PORT_MAX + 1):
        if port not in used:
            return port
    raise RuntimeError("No available ports in range")
