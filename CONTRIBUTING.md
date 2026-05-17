# Contributing

## Development Setup

```bash
git clone <repo-url>
cd helix-mini
pip install -e ".[dev]"       # pytest + pytest-asyncio
pip install -e ".[pdf]"       # optional: PDF text extraction via pymupdf
```

## Running Tests

```bash
pytest                            # all 66 tests
pytest tests/test_sandbox.py -v   # single file
pytest -k test_scout -v           # single test by name
pytest -v --tb=short              # verbose, short tracebacks
```

No linter is currently configured.

## Code Conventions

These conventions are enforced by existing code patterns:

- **`from __future__ import annotations`** at the top of every module (except `__init__.py` files).
- **Type hints** on all function signatures and return types.
- **`@dataclass`** for data containers (`ForgeState`, `Page`, `PageWrite`, `LLMResponse`, `ModelConfig`).
- **`_` prefix** for private functions and methods.
- **`log = logging.getLogger(__name__)`** in each module for logging.
- **Module docstrings** on every `.py` file.

## Architecture Constraints

- **Sandbox first:** All LLM-generated filesystem writes must pass through `sanitize_atlas_writes()` in `sandbox.py` before calling `Atlas.write()`.
- **Circular import avoidance:** `sandbox.py` imports `PageWrite` from `atlas.store` (not `atlas/__init__`) to break the cycle: `sandbox → atlas → atlas.ingest → sandbox`.
- **API key security:** API key values must never appear in log output, subprocess arguments, or error messages. Docker env vars use `-e VAR_NAME` (without `=VALUE`).

## Adding a New Agent

1. Add a system prompt constant in `pipeline/agents.py` (e.g., `MY_AGENT_PROMPT`).
2. Add a method to the `Agents` class following the `_call_and_write()` pattern:
   ```python
   def my_agent(self, state: ForgeState) -> dict:
       context = self.atlas.read(state.project_name)
       resp, cost = self._call_and_write(
           "my_agent", MY_AGENT_PROMPT, f"...", state.project_name,
       )
       return {"some_field": resp.get("some_field"), "cost": cost}
   ```
3. Add a node function in `pipeline/graph.py` following the existing pattern (convert state, check cost cap, call agent, log decision, mint snapshot).
4. Wire the node into the graph with `graph.add_node()` and `graph.add_edge()`.
5. Add a fake response dict and test in `tests/test_lightspeed.py`.

## Adding a New Provider

1. Add an entry to `PROVIDERS` in `config/providers.py`:
   ```python
   "my_provider": {
       "env_var": "MY_PROVIDER_API_KEY",
       "default_model": "my_provider/model-name",
       "lightspeed_model": "my_provider/cheap-model",
   },
   ```
2. Add a validation model in the `model_map` dict inside `validate_api_key()`.
3. The CLI `setup` wizard and `_collect_env_vars()` in `docker.py` will pick it up automatically.

## Test Patterns

- Mock LLM calls with `@patch("helix_mini.pipeline.agents.call_llm_json")`.
- Return values are `(dict, float)` tuples — `(response_data, cost)`.
- Use `conftest.py` fixtures: `tmp_atlas`, `sample_folder`, `make_fake_llm_response`.
- Integration tests for the full pipeline are in `test_lightspeed.py` with a sequence of fake responses.

## Project Structure

See [docs/architecture.md](docs/architecture.md) for the full architecture map and component diagram.
