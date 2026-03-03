# Baton

Cloud-agnostic circuit orchestration. Pre-wired topologies with smart adapters, mock collapse, and self-healing.

## Architecture

Circuit board metaphor: define the topology (nodes + edges) once, then slot services in and out.

- **Circuit** — the board. Nodes + edges + addresses. First-class artifact.
- **Adapter** — async reverse proxy at each node. Handles hot-swap, drain, health.
- **Mock** — auto-generated from OpenAPI/JSON Schema contracts.
- **Collapse** — compress circuit: full mock (one process) through partial to full live.
- **Custodian** — monitors adapters, self-heals with atomic repairs.

## Structure

```
src/baton/
  schemas.py          # All Pydantic v2 models
  config.py           # YAML config loader
  cli.py              # argparse entry point
  circuit.py          # Graph operations
  adapter.py          # Async reverse proxy
  adapter_control.py  # Adapter management API
  mock.py             # Mock server generation
  custodian.py        # Health monitoring + repair
  process.py          # Subprocess management
  state.py            # .baton/ persistence
  lifecycle.py        # Circuit lifecycle orchestration
  collapse.py         # Collapse algorithm
  providers/          # Cloud deployment plugins
```

## Commands

```bash
baton init [dir]                       # create baton.yaml
baton node add <name> [--port N]       # add node to circuit
baton edge add <from> <to>             # add connection
baton up [--mock]                      # boot circuit
baton slot <node> <command>            # slot live service
baton swap <node> <command>            # hot-swap service
baton collapse [--live n1,n2]          # collapse circuit
baton status                           # show health
baton watch                            # start custodian
baton down                             # tear down
```

## Conventions

- Python 3.12+, Pydantic v2, argparse, hatchling, pytest
- Frozen models for topology definitions, mutable for runtime state
- Protocol-based DI for extensible components
- All async operations use asyncio (no external server frameworks)
- Tests: one test file per source module, pytest-asyncio
