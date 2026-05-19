# The agent-driven pipeline

Helix has no model of its own and holds no credentials. The client agent —
Claude Code — *is* the model: the server hands each stage's prompt back
through the tool loop, the agent answers in its own turn, and the server
ingests the answer. There is no MCP `sampling` and no API key.

## Why

Helix used to drive its model through MCP `sampling/createMessage`. Claude
Code does not implement sampling
([anthropics/claude-code#1785](https://github.com/anthropics/claude-code/issues/1785)),
so a sampling-driven run died the instant a stage needed inference. Reaching
out another way (an API key, a CLI subprocess) would add credentials or
processes. Inverting the dependency removes the problem instead of routing
around it.

## Scope: one seam

The whole server has **exactly one** model-consumption site:
`core.agents.run_agent` → `llm.call_llm_json`. Everything else is
deterministic and already worked without a model:

- **Already deterministic** — Atlas read/write/recall/ingest/lint,
  snapshots, decisions, runs, the hot cache, gates, `transitions`, and every
  other tool/resource. Semantic recall uses a *local* embedding model, not
  the client.
- **Intelligent content is forge output.** Source summaries, the plan,
  critiques, syntheses that land in the Atlas/snapshots are produced by the
  forge stages (or supplied directly by the agent via `hx_atlas_save`).

So inverting that single seam makes the *entire* server run through Claude
Code — the Atlas and snapshots are powered by it transitively, with no
per-subsystem change.

## How it works

`loop.advance` is unchanged: run the stage → snapshot → gate → transition.
Only *how the stage gets its model answer* changes, through a per-run JSON
responder bound on a contextvar (`llm.use_responder`), threaded like the
gate asker — never stored in `PipelineState`.

- **`hx_step`** renders the next model-needing stage's prompt. The responder
  raises `io.NeedsModel`, which unwinds out of `advance` *before* any Atlas
  write or snapshot — nothing is mutated, so the prior snapshot is the
  resume point. The rendered SYSTEM + USER prompt and a `pending_token` are
  returned to the agent and persisted to
  `.helix/runs/<project>.pending.json`. Deterministic stages (the Validator)
  run straight through with no round-trip.
- **`hx_submit`** rehydrates state from that prior snapshot and re-enters
  **the same `advance`** for the stage, with a responder that returns the
  agent's submitted JSON where the model answer would have been. From there
  `run_agent` proceeds exactly as before: sanitize and apply `atlas_writes`,
  map the response, mint the snapshot, run the gate, transition — then
  return the *next* stage's prompt (or the final summary).

Because submit re-enters from a snapshot and routes through the one
`next_stage`, the snapshot DAG and routing are unchanged. There is still one
runner; only the model-acquisition step differs.

**Prompt pinning.** A stage's prompt can depend on mutable Atlas state, so
`hx_step` pins the rendered prompt and the agent answers exactly what it was
shown. `hx_submit` injects that answer regardless of the re-rendered prompt;
the mapping/snapshot/gate are deterministic, keeping submit faithful and the
step idempotent under the multi-session folder race.

## The tools

- `hx_step(folder, question=, autonomy_until=)` — initialize a run (first
  call; reads `question.md`) or advance to the next prompt. Idempotent: a
  pending step is re-shown.
- `hx_submit(folder, stage, result_json, pending_token)` — submit the
  agent's answer; returns the next prompt or the done summary. A stale or
  wrong-stage token is rejected with guidance.
- `run_pipeline` and `hx_start` are **initializers**: they create the run
  (the wizard elicits name/question/mode for `hx_start`) and return the
  first `hx_step`. `resume_pipeline` rehydrates a snapshot and returns the
  next prompt.

Gates still use MCP **elicitation**, which Claude Code supports: each gate
asks unless the `Plan` (`autonomy_until`) auto-proceeds. A declined gate, a
budget ceiling, or a lost client all pause the run resumably rather than
crashing — every stop has a snapshot, and `hx_step` simply resumes.

## A run, end to end

```
hx_step(folder)            → NEEDS MODEL: scout prompt        (+ pending file)
hx_submit(scout, json)     → snapshot · gate · NEEDS MODEL: critic_methods
hx_submit(critic_methods)  → … planner … builder …
   (Validator runs server-side here — no round-trip)
hx_submit(critic_results)  → run summary: done (stages=6)
```

Five model round-trips for the six-stage pipeline; the deterministic
Validator is handled in-loop.

## Invariants

- One routing authority (`transitions.next_stage`) and one runner (a
  decomposed but single `advance`) — no parallel pipeline.
- A snapshot never calls a model (more true than before).
- `helix.core`, `helix.io`, and `loop.py` import without `mcp`/`fastembed`;
  `io.NeedsModel` is pure, like `Declined`/`ClientUnavailable`.
- The model is the client agent via the tool loop; nothing holds
  credentials.

`app.run` / `loop._run` remain only as the in-process test and embedding
harness (driven by a patched `call_llm_json`), never an MCP runner.
