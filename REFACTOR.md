# Refactor: helix-mini to helix

A ground-up rewrite into a lighter, CLI-first project with the same
capabilities. It is a clean break: no migration of old data or `snap-N.json`
files.

## What changed

**Dependency-light core.** `langgraph` and `litellm` moved to the
`helix[sdk]` extra. The default CLI path needs only `click`, `python-dotenv`,
and `pyyaml`. Nothing in `helix.core` imports either heavy dependency.

**One core, two orchestrators.** Stage logic moved out of the LangGraph
closures into `core/stages.py`. The default runner is a plain loop;
`langgraph_runner.py` is an optional mirror. Both share `loop.advance` and
route through `core/transitions.next_stage`, and a conformance test asserts
they agree.

**Agents are markdown.** The six prompt constants became
`builtin_agents/*.md`, overridable per project with no code change. Stage
order is read from frontmatter rather than hardcoded.

**Real human-in-the-loop.** Before, `ask_fn` was always `None` and the
middle gates were unconditional edges, so no review actually happened. Now a
gate runs after every stage and can send the run back to any stage with
feedback that is threaded into that stage.

**Simpler autonomy.** The per-gate autonomy dictionary became one
`autonomy_until` value, changeable per run.

**Unbounded cycling.** The hard iteration cap is gone. The bound is a
configurable cost and call ceiling that pauses and snapshots (resumable)
instead of raising.

**Snapshots v2.** Was: the full state including inlined artifact bytes, every
stage, in a flat `snap-N` list. Now: a content-addressed object store
(artifacts deduped by hash, snapshots stay small) with an explicit
parent/branch DAG and branch, revert, and resume-from-any. Still zero LLM
cost.

**Repo-local by default.** The Atlas (`./atlas`) and control directory
(`./.helix`) live in the project. One `helix.toml` configures them. There is
no `~/.helix-mini`.

**Renamed.** `helix-mini` to `helix`; package `helix_mini` to `helix`.
`helix init` scaffolds a `CLAUDE.md` so an agentic CLI can drive the project.

## What was removed

- The LangGraph-only execution path (one shared core now).
- The per-gate autonomy dictionary and the iteration cap. `build_iterations`
  remains as an informational counter.
- The large `docs/guides` and `docs/reference` trees, replaced by five
  focused documents.
- The fatal `CostCapExceeded`; the ceiling is now a resumable pause.

## Why it is lighter

The default install has three small dependencies instead of four heavy ones.
The core is orchestrator-agnostic and prompt-as-data. The snapshot store no
longer grows with artifact size. Seventeen focused tests pass, including
dual-orchestrator conformance.
