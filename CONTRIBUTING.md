# Contributing to Baton

## Development Setup

```bash
git clone https://github.com/jmcentire/baton.git
cd baton
pip install -e ".[dev]"
pytest
```

## Project Structure

```
src/baton/
  schemas.py          # Pydantic v2 models
  config.py           # YAML config loader
  cli.py              # CLI entry point
  circuit.py          # Graph operations (pure functions)
  adapter.py          # Async reverse proxy
  adapter_control.py  # Management API endpoints
  routing.py          # Pre-baked routing patterns
  lifecycle.py        # Circuit lifecycle orchestration
  custodian.py        # Health monitoring + self-healing
  mock.py             # Mock server generation from specs
  collapse.py         # Collapse algorithm
  manifest.py         # Service manifest loading
  registry.py         # Circuit derivation from manifests
  compat.py           # Static compatibility analysis
  process.py          # Subprocess management
  state.py            # .baton/ persistence
  providers/          # Deployment backends
    local.py          # Local process deployment
    gcp.py            # GCP Cloud Run deployment
```

## Conventions

- Python 3.12+
- Pydantic v2 for all data models
- Frozen models for topology definitions, mutable for runtime state
- All async operations use asyncio (no external server frameworks)
- One test file per source module
- pytest with pytest-asyncio (`asyncio_mode = "auto"`)
- Pure functions for graph operations (circuit.py returns new CircuitSpec instances)

## Running Tests

```bash
pytest                    # all tests
pytest tests/test_cli.py  # specific module
pytest -v                 # verbose output
```

## Adding a New Provider

1. Create `src/baton/providers/yourprovider.py`
2. Implement the `DeploymentProvider` protocol:
   - `async def deploy(circuit, target) -> CircuitState`
   - `async def teardown(circuit, target) -> None`
   - `async def status(circuit, target) -> CircuitState`
3. Register in `src/baton/providers/__init__.py`
4. Add tests in `tests/test_providers.py`
5. Add optional dependencies in `pyproject.toml`

## Submitting Changes

1. Fork the repository
2. Create a feature branch
3. Write tests for new functionality
4. Ensure all tests pass (`pytest`)
5. Submit a pull request
