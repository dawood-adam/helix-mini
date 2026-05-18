# Contributing

## Setup

```bash
git clone <repo-url> && cd helix
pip install -e '.[sdk,dev]'      # langgraph, litellm, pytest
pip install -e '.[pdf]'          # optional: PDF ingestion
```

## Tests

```bash
pytest -q                        # 17 tests, including dual-orchestrator conformance
PYTHONPATH="$PWD/src" pytest -q  # when running inside a git worktree
pytest -k conformance -v
```

No linter is configured.

## Code conventions

- `from __future__ import annotations` at the top of every module, except
  `__init__.py`.
- Type hints on signatures. `@dataclass` for data containers.
- Private helpers are `_`-prefixed. Every module has a docstring.
- Comments explain why, not what. Keep them rare.

## Architecture constraints

These are invariants. Keep the conformance test green.

- **Dependency-light core.** Nothing in `helix/core/` or
  `orchestrator/loop.py` may import `langgraph` or `litellm` at module load.
- **One router.** Routing logic lives only in `core/transitions.py`. Both
  orchestrators step through `loop.advance`.
- **Snapshots never call an LLM.**
- **Sandbox first.** LLM output reaches disk only through
  `sandbox.sanitize_atlas_writes` or `sanitize_code_artifacts`.
- **No import cycle.** `sandbox` imports `PageWrite` from `core.atlas` (the
  store, which imports no sandbox). Only `core.ingest` imports `sandbox`.
- Secrets never appear in logs, subprocess arguments, or error messages.

## Adding an agent

1. Add `helix/builtin_agents/<stage>.md` with frontmatter and a system
   prompt. Set `order` to its pipeline position.
2. For an `llm` agent, add a context builder to `_CONTEXT` and a response
   mapper to `_MAP` in `core/agents.py`, then add the decision text in
   `core/stages.py` (`_decision_text`).
3. For a `deterministic` agent, register a function in `_DETERMINISTIC`. It
   calls no LLM and has no cost.
4. Add a fake response, keyed by a phrase from the system prompt, in
   `tests/conftest.py`.

## Adding a provider

Add an entry to `PROVIDERS` in `helix/config.py` and a validation model in
`validate_api_key`. The `helix setup` wizard picks it up automatically.

## Architecture

See [docs/architecture.md](docs/architecture.md).
