# Architecture

## Mental model

Helix has three layers, inside out:

1. **Core** (`helix/core/`) — the pipeline and the Atlas. Pure Python; it
   imports neither the MCP SDK nor an embedding model.
2. **Orchestrator** (`helix/orchestrator/loop.py`) — one runner that steps
   the core: run a stage, snapshot, consult the gate, transition.
3. **Drive surface** (`helix/mcp/`) — a stdio MCP server. The client (Claude
   Code) calls its tools; the server calls back into the client for model
   completions and user input.

The model lives entirely on the client side. When a stage needs an LLM, the
server issues an MCP `sampling/createMessage`; the client runs it and returns
the text. Helix stores no credentials.

```
  Claude Code (MCP client)
      │  tools / resources / prompts        ▲ sampling · elicitation
      ▼                                     │
  helix-mcp  (helix/mcp/server.py)  ── helix/io.py: the one client-IO seam
      │
      ▼
  app.py ─► orchestrator/loop.py ─► core/  (stages · gates · transitions
                                            · plan · snapshots · Atlas)
```

## The client-IO seam

`helix/io.py` is the single place anything is sent back to the client. It
exposes two operations behind one bound object:

- `sample(...)` — a model completion (MCP sampling).
- `elicit(...)` — a structured question to the user (MCP elicitation), built
  with `ask_text` / `ask_choice` / `ask_multi` / `ask_confirm`.

The pipeline core is synchronous and deep; the MCP session is asynchronous.
The seam bridges them once (an `anyio` worker thread for the run, hopping
back to the event loop per call). `helix/mcp/client_io.py` is the only
implementation; tests inject a scripted one. The same seam powers model
calls, HITL gates (`gate_asker`), the setup wizard, and tier promotion — one
mechanism, used uniformly.

## A step

`loop.advance` is the unit:

1. Run the stage (`stages.run_stage` → `agents.run_agent`). The agent emits
   its domain output plus a **Decision Card** (`core.decisions`).
2. Mint a snapshot. No LLM call — it serializes state and reuses the
   Decision Card as the human digest.
3. Resolve the gate (`gates.decide_gate`): the run-scoped **Plan**
   (`core.plan`) decides whether this transition auto-proceeds or asks. An
   ask goes through the client-IO seam as elicitation; a decline pauses the
   run resumably.
4. Transition (`transitions.next_stage`): proceed to the next stage, jump
   back to any stage with a directive, or stop.

Routing lives only in `transitions.next_stage`. The Plan replaces the older
`autonomy_until` string, which survives as a constructor for compatibility.

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
`helix.toml [limits]`. Sampling does not report usage to the server, so the
token figure is an estimate of the prompt and response text the server
handled. Reaching the ceiling pauses the run (resumable) or, interactively,
offers to raise it — it never crashes or loses work.

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
    └── embeddings.json        body-hash-keyed vector cache
```

## Invariants

- `helix.core`, `helix.io`, and `loop.py` import without `mcp` or
  `fastembed`. SDK contact is confined to `helix/mcp/`.
- All routing is in `core.transitions.next_stage`.
- A snapshot never calls an LLM.
- The model is reached only through the client-IO seam (MCP sampling).
- LLM output reaches disk only through the sandbox: page/artifact content
  via `sanitize_*`, and project/run/bundle names via
  `validate_project_name` at every path root.
- One page scan: `core.atlas.iter_pages`.
