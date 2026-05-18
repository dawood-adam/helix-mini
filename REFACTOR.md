# Refactor note: helix-mini → helix

A ground-up rewrite into a lighter, transparent, CLI-first project with the
same capabilities. Clean break — no migration of old data or `snap-N.json`.

## What changed

- **Dependency-light core.** `langgraph` and `litellm` moved to the
  `helix[sdk]` extra. The default (CLI) path needs only `click`,
  `python-dotenv`, `pyyaml`. `helix.core` imports with neither heavy dep.
- **One core, two orchestrators.** Stage logic was extracted out of the
  LangGraph closures into `core/stages.py`. A plain `loop.py` is the default
  runner; `langgraph_runner.py` is an optional mirror. Both share
  `loop.advance` and route through the single `core/transitions.next_stage`,
  so they can't diverge (a conformance test enforces it).
- **Agents are markdown.** The six hardcoded prompt constants became
  `builtin_agents/*.md` (frontmatter + body), project-overridable with no code
  change. Stage order is derived from frontmatter, not a constant.
- **Real HITL.** Previously `ask_fn` was always `None` and gates 1–4 were
  unconditional edges — no human interaction existed. Now a gate runs after
  every stage: proceed, send back to **any** stage with feedback (threaded
  into that stage via `state.human_feedback`), or stop.
- **Autonomy model.** Per-gate `auto|always_ask` replaced by one
  `autonomy_until` value, switchable per run.
- **Unbounded cycling.** The hard `max_iterations` cap is gone; the bound is a
  configurable cost/call ceiling that **pauses and snapshots** (resumable)
  instead of raising.
- **Snapshots v2.** Was: full `ForgeState` (incl. inlined artifact bytes)
  per stage, linear `snap-N`. Now: content-addressed object store (artifacts
  deduped by sha, snapshot stays KB), explicit `parent`/`branch` DAG, with
  `branch` / `revert` / `resume-from-any`. Still zero LLM cost.
- **Repo-local by default.** Atlas (`./atlas`) and control dir (`./.helix`)
  live in the project; one `helix.toml` configures them. No `~/.helix-mini`.
- **CLI rename.** `helix-mini` → `helix`; package `helix_mini` → `helix`.
  `helix init` scaffolds a `CLAUDE.md` so an agentic CLI can drive it.

## What was removed

- The forked LangGraph-only execution path (now one shared core).
- Per-gate autonomy dict, `max_iterations`/`build_iterations` as a *cap*
  (`build_iterations` remains an informational counter).
- The sprawling `docs/guides` + `docs/reference` tree, replaced by five
  focused docs.
- Fatal `CostCapExceeded` behavior (now a resumable pause).

## Why it's lighter

Default install has 3 small deps instead of 4 heavy ones; the core is
orchestrator-agnostic and prompt-as-data; the snapshot store no longer grows
with artifact size. ~17 focused tests, all green including dual-orchestrator
conformance.
