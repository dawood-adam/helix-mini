# CLAUDE.md

Guidance for Claude Code working in this repository.

## Commands

```bash
pip install -e .                 # CLI mode (dependency-light: click, dotenv, pyyaml)
pip install -e '.[sdk,dev]'      # + LangGraph/litellm + pytest
pytest -q                        # 17 tests (incl. dual-orchestrator conformance)
PYTHONPATH="$PWD/src" pytest -q  # in a git worktree (editable install points at main src)
helix --help                     # CLI entry point
```

Python >=3.11. No linter configured.

## Architecture

One dependency-light pipeline **core**, two **orchestrators** over it, two
ways to **drive** it. See [docs/architecture.md](docs/architecture.md).

- **`helix/core/`** — imports with neither langgraph nor litellm.
  `state.py` (`PipelineState` + `human_feedback`), `agents.py` (markdown agent
  loader + table-driven context/mapping + deterministic registry),
  `stages.py`, `gates.py` (HITL + `autonomy_until`), `transitions.py` (the
  single `next_stage` resolver), `snapshots.py` (content-addressed DAG),
  `atlas.py`/`ingest.py`, `decisions.py`.
- **`helix/orchestrator/`** — `loop.py` (default; owns `advance`, the shared
  per-step unit) and `langgraph_runner.py` (`helix[sdk]`; lazy langgraph).
  Both call `loop.advance` → `transitions.next_stage`, so they cannot diverge.
- **`helix/`** — `config.py` (all path/auth/model resolution; repo-local
  defaults), `llm.py` (chokepoint; litellm lazy), `llm_cli.py`, `sandbox.py`,
  `app.py` (facade), `cli.py`, `agent_iface.py` (fail-closed Agent SDK).
- **`helix/builtin_agents/*.md`** — the six agents as markdown.

## Key invariants

- `helix.core` and `helix.orchestrator.loop` MUST import without langgraph or
  litellm (a manual `sys.modules` check guards this).
- Both orchestrators route via `core.transitions.next_stage`. Add routing
  logic there, never in an orchestrator. `tests/test_conformance.py` enforces
  parity.
- A snapshot must never call an LLM. `mint_snapshot` only serializes and
  content-addresses; it reuses the stage's decision text as the digest.
- All LLM output to disk passes `sandbox.sanitize_atlas_writes` /
  `sanitize_code_artifacts`. `Atlas._safe_resolve` is defense-in-depth.
- `sandbox.py` imports `PageWrite` from `core.atlas` (store only, no sandbox
  import); `core.ingest` is the only module importing sandbox, so no cycle.
- Auth precedence is OAuth-wins (`config.ModelConfig.default`); the agent gate
  in `agent_iface.run_permission_decision` is fail-closed.

## Test patterns

- `tests/conftest.py` isolates `HELIX_HOME` to a tmp dir and patches
  `helix.core.agents.call_llm_json`, routing fake JSON by system-prompt
  keyword.
- The conformance test runs one scenario through `engine="loop"` and
  `engine="sdk"` and asserts identical results (skips if langgraph absent).
