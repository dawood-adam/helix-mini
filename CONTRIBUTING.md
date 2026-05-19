# Contributing

## Setup

```bash
git clone <repo-url> && cd helix-mini
pip install -e '.[dev]'          # core + pytest
pip install -e '.[embed,pdf]'    # optional: semantic recall + PDF ingest
```

Python ≥ 3.11. Core dependencies are deliberately few: `click`,
`python-dotenv`, `pyyaml`, `mcp`, `anyio`.

## Tests

```bash
pytest -q
PYTHONPATH="$PWD/src" pytest -q  # when running inside a git worktree
```

No linter is configured. Optional-dependency paths (`mcp`, `fastembed`) are
guarded with `pytest.importorskip`, so the suite runs with the core install
alone.

## Code conventions

- `from __future__ import annotations` at the top of every module, except
  `__init__.py`.
- Type hints on signatures. `@dataclass` for data containers.
- Private helpers are `_`-prefixed. Every module has a docstring.
- Comments explain why, not what. Keep them rare.

## Architecture constraints

These are invariants — see [docs/architecture.md](docs/architecture.md) and
`CLAUDE.md`.

- **Dependency-light core.** `helix/core/`, `helix/io.py`, and
  `orchestrator/loop.py` import without `mcp` or `fastembed`. SDK contact is
  confined to `helix/mcp/`; the embedding model is lazy-imported in
  `core.embed`.
- **One router.** Routing logic lives only in `core/transitions.py`; the
  single runner steps through `loop.advance`.
- **A snapshot never calls a model.**
- **Agent-driven, no credentials.** The model is the client agent, reached
  through the tool loop (`hx_step` / `hx_submit`) via the JSON-responder
  seam in `helix/llm.py` — never server-side sampling.
- **Sandbox first.** Model output reaches disk only through
  `sandbox.sanitize_atlas_writes` / `sanitize_code_artifacts`; project, run,
  and bundle names through `validate_project_name` at every path root.
- **No import cycle.** `sandbox` imports only `PageWrite` from `core.atlas`
  (the store, which imports no sandbox).
- Secrets never appear in logs, subprocess arguments, or error messages.

## Adding an agent

1. Add `helix/builtin_agents/<stage>.md` with frontmatter (set `order` to
   its pipeline position, `kind`, and the Atlas-write policy) and a system
   prompt with its JSON output contract.
2. For an `llm` agent, add a context builder to `_CONTEXT` and a response
   mapper to `_MAP` in `core/agents.py`.
3. For a `deterministic` agent, register a function in `_DETERMINISTIC`. It
   calls no model and has no cost.
4. Add a fake response, keyed by a phrase from the system prompt, in
   `tests/conftest.py` (the in-process `app.run` test harness routes by
   that keyword).

A project may override any builtin with `agents/<stage>.md` — no code
change.

## Architecture

See [docs/architecture.md](docs/architecture.md) and
[docs/agent-driven-pipeline.md](docs/agent-driven-pipeline.md).
