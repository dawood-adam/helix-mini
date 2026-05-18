# Contributing

## Setup

```bash
git clone <repo-url> && cd helix
pip install -e '.[sdk,dev]'      # langgraph + litellm + pytest
pip install -e '.[pdf]'          # optional: PDF ingestion
```

## Tests

```bash
pytest -q                        # 17 tests, incl. dual-orchestrator conformance
PYTHONPATH="$PWD/src" pytest -q  # in a git worktree
pytest -k conformance -v
```

No linter is configured.

## Code conventions

- `from __future__ import annotations` atop every module (not `__init__.py`).
- Type hints on signatures; `@dataclass` for data containers.
- `_`-prefixed private helpers; module docstrings; minimal comments
  (explain *why*, never *what*).

## Architecture constraints

- **Dependency-light core:** nothing under `helix/core/` (and
  `orchestrator/loop.py`) may import `langgraph` or `litellm` at module load.
- **One router:** routing logic lives only in `core/transitions.py`; both
  orchestrators go through `loop.advance`. `tests/test_conformance.py`
  enforces parity — keep it green.
- **Snapshots never call an LLM.**
- **Sandbox first:** LLM output to disk goes through
  `sandbox.sanitize_atlas_writes` / `sanitize_code_artifacts`.
- **No import cycle:** `sandbox` imports `PageWrite` from `core.atlas` (store
  only); only `core.ingest` imports `sandbox`.
- Secrets never appear in logs, subprocess args, or error messages.

## Adding an agent

1. Add `helix/builtin_agents/<stage>.md` (frontmatter + system prompt). Set
   `order` for its pipeline position.
2. For an `llm` agent, add a context builder to `_CONTEXT` and a response
   mapper to `_MAP` in `core/agents.py`; add the `(decision, rationale)` case
   in `core/stages.py:_decision_text`.
3. For a `kind: deterministic` agent, register a function in `_DETERMINISTIC`
   — no LLM, no cost.
4. Add a fake response (keyed by a system-prompt phrase) in
   `tests/conftest.py`.

## Adding a provider

Add an entry to `PROVIDERS` in `helix/config.py` and a validation model in
`validate_api_key`. The `setup` wizard picks it up automatically.

## Architecture

See [docs/architecture.md](docs/architecture.md).
