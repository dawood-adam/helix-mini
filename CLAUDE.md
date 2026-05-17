# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -e ".[dev]"          # Install with test dependencies
pip install -e ".[pdf]"          # Install with PDF support (pymupdf)
pytest                           # Run all 66 tests
pytest tests/test_sandbox.py -v  # Run a single test file
pytest -k test_scout -v          # Run a single test by name
helix-mini --help                # CLI entry point
```

No linter is configured. Python >=3.11 required.

## Architecture

Helix Mini runs a research pipeline over input folders: ingest files, identify approaches, critique, plan, build, validate — with every agent reading from and writing to a shared **Atlas** (an LLM-maintained markdown wiki that persists across projects).

### Package layout

- **`config/`** — Model selection (`ModelConfig` with per-stage overrides), provider registry (Anthropic/OpenAI), `.env` loading, setup wizard. All symbols re-exported from `config/__init__.py`.
- **`atlas/`** — Markdown wiki: `store.py` (Atlas class with thread-safe read/write/index), `ingest.py` (file/PDF ingestion). Re-exported from `atlas/__init__.py`.
- **`pipeline/`** — LangGraph workflow: `state.py` (ForgeState dataclass + GraphState TypedDict), `agents.py` (6 LLM agents), `graph.py` (12-node graph), `router.py` (gate decisions), `runner.py` (execution), `decisions.py`/`snapshots.py` (audit trail). Re-exported from `pipeline/__init__.py`.
- **`sandbox.py`** — Validates all LLM-generated Atlas writes (path traversal, content size, batch limits) before they touch the filesystem.
- **`llm.py`** — Thin litellm wrapper (`call_llm_json`). All LLM calls go through here.
- **`docker.py`** — Optional Docker sandbox (non-root, read-only mounts, resource limits).
- **`app.py`** — Facade: wires Atlas + config + runner.
- **`cli.py`** — Click CLI: `run`, `setup`, `init`, `status`, `log`, `atlas search`.

### Pipeline flow

```
scout → gate → critic_methods → gate → planner → gate → builder → gate → validator
  → sanity_route: pass → critic_results → gate → END
                   fail → builder (retry loop)
```

Each agent calls `call_llm_json()`, then passes `atlas_writes` through `sanitize_atlas_writes()` before writing to Atlas. The validator is deterministic (no LLM) — it checks results against validation bands.

### Circular import caveat

`sandbox.py` imports `PageWrite` from `atlas.store` (not `atlas/__init__`) to avoid a circular dependency: `sandbox → atlas → atlas.ingest → sandbox`.

## Test patterns

- Tests mock LLM calls with `@patch("helix_mini.pipeline.agents.call_llm_json")` returning `(dict, cost)` tuples.
- `conftest.py` provides `tmp_atlas`, `sample_folder`, and `make_fake_llm_response` fixtures.
- `test_lightspeed.py` has predefined fake responses for the full 5-agent pipeline sequence.

## Security invariants

- API key values must never appear in log output or subprocess argument lists. `_collect_env_vars()` uses `-e VAR_NAME` (no `=VALUE`) so Docker inherits from host.
- All LLM output destined for the filesystem must pass through `sanitize_atlas_writes()`. Atlas also has `_safe_resolve()` as defense-in-depth.
- `validate_ingest_source()` rejects symlinks pointing outside the input folder.
