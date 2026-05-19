# Architecture

## Mental model

Helix has three layers, inside out:

1. **Core** (`helix/core/`) — the pipeline and the Atlas. Pure Python; it
   imports neither the MCP SDK nor an embedding model.
2. **Orchestrator** (`helix/orchestrator/loop.py`) — one runner that steps
   the core: run a stage, snapshot, consult the gate, transition.
3. **Drive surface** (`helix/mcp/`) — a stdio MCP server. The client (Claude
   Code) calls its tools; its agent answers each stage's prompt, and the
   server calls back only for user input (elicitation at gates).

The model lives entirely on the client side — as the client *agent*, not a
sampling callback. When a stage needs the model, `hx_step` returns its
prompt; the agent answers in its own turn and calls `hx_submit`. There is
no MCP `sampling`, and Helix stores no credentials. Full design:
[agent-driven-pipeline.md](agent-driven-pipeline.md).

```
  Claude Code (the agent — the model, on the user's plan)
      │  hx_step → {stage, prompt}      ▲ elicitation (gates only)
      ▼  hx_submit(stage, json)         │
  helix-mcp  (helix/mcp/server.py)  ── helix/io.py: the client-IO seam
      │
      ▼
  orchestrator/loop.py (advance, re-entered per submit) ─► core/
                  (stages · gates · transitions · plan · snapshots · Atlas)
```

## The client-IO seam

`helix/io.py` is the single place anything is sent back to the client. The
model is *not* here — it is the client agent, reached through the tool loop
(`hx_step`/`hx_submit`) via the JSON-responder seam in `helix/llm.py`. The
one remaining client callback is:

- `elicit(...)` — a structured question to the user (MCP elicitation), built
  with `ask_text` / `ask_choice` / `ask_multi` / `ask_confirm` (HITL gates,
  the setup wizard, tier promotion).

The pipeline core is synchronous and deep; the MCP session is asynchronous.
The seam bridges them once (an `anyio` worker thread for the call, hopping
back to the event loop). `helix/mcp/client_io.py` is the only
implementation; tests inject a scripted one or drive the step loop directly.

## A step

`loop.advance` is the unit:

1. Run the stage (`stages.run_stage` → `agents.run_agent`). The stage's
   model call routes through the bound JSON responder: `hx_step` renders the
   prompt and *suspends* the stage before any mutation; `hx_submit`
   re-enters the same `advance` from the prior snapshot with the agent's
   answer injected. The stage emits its domain output plus a **Decision
   Card** (`core.decisions`). Deterministic stages (the Validator) run
   straight through with no round-trip.
2. Mint a snapshot. No model call — it serializes state and reuses the
   Decision Card as the human digest.
3. Resolve the gate (`gates.decide_gate`): the run-scoped **Plan**
   (`core.plan`) decides whether this transition auto-proceeds or asks. An
   ask goes through the client-IO seam as elicitation; a decline pauses the
   run resumably.
4. Transition (`transitions.next_stage`): proceed to the next stage, jump
   back to any stage with a directive, or stop.

The step driver (`loop.step_begin` / `submit_stage` / `resume_step`) reuses
this one `advance` — it is not a second runner. Routing lives only in
`transitions.next_stage`. The Plan replaces the older `autonomy_until`
string, which survives as a constructor for compatibility.

## Run control

A `Plan` is run-scoped configuration, threaded through the loop alongside
the gate asker — never persisted in `PipelineState`. It governs gate
autonomy (auto vs. ask, per stage or window) and can inject a per-stage
directive through the existing feedback channel. `runs.py` keeps a bounded
registry: a record and event log per run under `.helix/runs/`, plus the live
`Plan` so `hx_run_plan_set` can steer a run and `hx_run_status` /
`hx_run_events` can observe it. History survives a server restart; live
continuation is via snapshots and resume.

## The bound on cycling

Cycling is unbounded by design; the only limit is a token/call ceiling in
`helix.toml [limits]`. The token figure is an estimate (≈ chars/4) of the
rendered prompt plus the agent's submitted answer — enough to bound a run.
Reaching the ceiling pauses the run (resumable) or, interactively, offers to
raise it — it never crashes or loses work.

## Storage

```
<project>/
├── helix.toml            limits + atlas path
├── question.md
├── .mcp.json             registers the helix MCP server
├── atlas/                the wiki (see docs/atlas.md)
│   ├── inbox/  raw/  sources/  concepts/  entities/  projects/
│   ├── index.md  log.md  ATLAS.md
│   └── projects/<id>/_hot.md
├── forks/                exported snapshot bundles
└── .helix/
    ├── snapshots/<project>/   <id>.json, index.json, refs.json, objects/
    ├── runs/<run_id>/         record.json, events.jsonl
    ├── runs/<project>.pending.json   suspended step (agent's turn)
    └── embeddings.json        body-hash-keyed vector cache
```

## Invariants

- `helix.core`, `helix.io`, and `loop.py` import without `mcp` or
  `fastembed`. SDK contact is confined to `helix/mcp/`.
- All routing is in `core.transitions.next_stage`.
- A snapshot never calls a model.
- The model is the client agent, reached only through the tool loop
  (`hx_step` / `hx_submit`) via the JSON-responder seam — never server-side
  sampling, and no credentials.
- LLM output reaches disk only through the sandbox: page/artifact content
  via `sanitize_*`, and project/run/bundle names via
  `validate_project_name` at every path root.
- One page scan: `core.atlas.iter_pages`.
