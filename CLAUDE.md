# CLAUDE.md

Guidance for Claude Code working in this repository.

## Commands

```bash
pip install -e .                 # core: click, python-dotenv, pyyaml, mcp, anyio
pip install -e '.[dev]'          # + pytest
pip install -e '.[embed,pdf]'    # optional: fastembed (semantic recall), pymupdf
pytest -q
PYTHONPATH="$PWD/src" pytest -q  # in a git worktree (editable install -> main src)
helix --help                     # init + mcp launcher only
```

Python ≥ 3.11. No linter configured.

## Architecture

A dependency-light pipeline **core**, one **orchestrator** (the loop), and
one **drive surface** (the MCP server). See
[docs/architecture.md](docs/architecture.md).

- **`helix/core/`** — the pipeline and the Atlas. `state.py`
  (`PipelineState`), `agents.py` (markdown agents + table-driven
  context/mapping), `stages.py`, `gates.py`, `transitions.py` (the single
  `next_stage` resolver), `plan.py` (run control), `decisions.py`
  (`DecisionCard`), `snapshots.py` (content-addressed DAG + git-ops),
  `atlas.py` (frontmatter store + the canonical `iter_pages`),
  `atlas_index.py` (SQLite graph), `embed.py`, `recall.py`, `lint.py`,
  `ingest.py`, `hot.py`.
- **`helix/orchestrator/loop.py`** — the only runner; owns `advance`, the
  per-stage unit (run → snapshot → gate → transition).
- **`helix/`** — `io.py` (the standardized client-IO seam: sampling +
  elicitation), `llm.py` (chokepoint → sampling), `config.py` (paths +
  limits), `sandbox.py`, `runs.py` (the bounded run registry), `app.py`
  (facade), `agent_iface.py` (pure tool bodies), `cli.py` (init + mcp).
- **`helix/mcp/`** — `server.py` (FastMCP: tools, resources, prompts),
  `client_io.py` (the MCP-backed `ClientIO`). The only modules that import
  the `mcp` SDK.
- **`helix/builtin_agents/*.md`** — the six agents as markdown.

## Key invariants

- `helix.core`, `helix.io`, and `helix.orchestrator.loop` import without
  `mcp` or `fastembed`. SDK contact is confined to `helix/mcp/`; the
  embedding model is lazy-imported inside `helix.core.embed`.
- All pipeline routing goes through `core.transitions.next_stage`. Add
  routing logic there, never in the orchestrator.
- A snapshot never calls an LLM. `mint_snapshot` serializes and
  content-addresses; it stores the stage's Decision Card as the digest.
- The model is driven only via the client (MCP sampling). `llm.call_llm`
  resolves the bound `ClientIO` from `helix.io`; nothing holds API keys.
- Run control is the run-scoped `Plan` (`core.plan`), threaded like
  `ask`/`interactive` — never a `PipelineState` field. `autonomy_until` is a
  compat constructor.
- Model-controlled strings reaching the filesystem are confined by
  `sandbox`: page/artifact content via `sanitize_atlas_writes` /
  `sanitize_code_artifacts`; project / run / bundle names (the snapshot,
  runs, and hot path roots) via `validate_project_name`. `Atlas._safe_resolve`
  is defense-in-depth. `sandbox` imports only `PageWrite` from `core.atlas`
  (store, no sandbox import), so although `core.ingest`, `core.snapshots`,
  and `core.hot` import `sandbox` for these validators, there is no cycle.
- One page scan: `core.atlas.iter_pages`. `atlas_index`, `embed`, and
  `recall` adapt it rather than re-walking the tree.

## Test patterns

- `tests/conftest.py` isolates `HELIX_HOME` to a tmp dir and patches
  `helix.core.agents.call_llm_json` (the patch point above `call_llm`),
  routing fake JSON by system-prompt keyword.
- MCP behaviour is exercised end to end with
  `mcp.shared.memory.create_connected_server_and_client_session`, supplying
  fake `sampling`/`elicitation` callbacks.
- Optional-dependency paths (`mcp`, `fastembed`) are guarded with
  `pytest.importorskip`; the surrounding logic is tested model-free via
  injected functions.
