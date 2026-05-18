# Architecture

Helix is one pipeline core with two orchestrators over it and two ways to
drive it. The core imports with neither `langgraph` nor `litellm`.

## Layers

```mermaid
graph TD
    subgraph drive["Drive modes"]
      CLI["Claude Code / any agentic CLI<br/>(default, no API key)"]
      AGENT["helix agent<br/>(Claude Agent SDK, fail-closed)"]
      LIB["programmatic / API"]
    end
    subgraph orch["Orchestrators"]
      LOOP["loop.py — plain loop<br/>(default, dependency-light)"]
      LG["langgraph_runner.py<br/>(helix[sdk])"]
    end
    subgraph core["core/ (no langgraph, no litellm)"]
      ST["stages.py"]
      AG["agents.py + builtin_agents/*.md"]
      GA["gates.py (HITL + autonomy)"]
      TR["transitions.py (single next-stage resolver)"]
      SN["snapshots.py (content-addressed DAG)"]
      AT["atlas.py / ingest.py"]
      DE["decisions.py"]
    end
    CLI --> LOOP
    AGENT --> LOOP
    LIB --> LOOP
    LIB --> LG
    LOOP --> ST
    LG --> ST
    LOOP -->|advance| TR
    LG -->|advance| TR
    ST --> AG
    ST --> GA
    GA --> TR
    ST --> SN
    AG --> AT
    ST --> DE
    AG -->|cli/ models| ENG["llm_cli.py → claude CLI"]
    AG -->|api models| LIT["litellm (helix[sdk])"]
```

**Both orchestrators call the same `loop.advance`**, which calls
`core.transitions.next_stage`. They cannot diverge on routing or snapshots —
`tests/test_conformance.py` runs one scenario through both and asserts they
agree (Risk A).

## Pipeline flow

```mermaid
graph LR
    src["source folder"] --> scout
    scout --> g1{{gate}} --> critic_methods
    critic_methods --> g2{{gate}} --> planner
    planner --> g3{{gate}} --> builder
    builder --> g4{{gate}} --> validator
    validator --> g5{{sanity}}
    g5 -->|hard flags| builder
    g5 -->|pass| critic_results
    critic_results --> g6{{gate}}
    g6 -->|ship/abandon| done["shipped artifacts"]
    g6 -.->|iterate / send-back to ANY stage| scout
    classDef llm fill:#EFF4FF,stroke:#2563EB
    classDef det fill:#FEF6E7,stroke:#B45309
    class scout,critic_methods,planner,builder,critic_results llm
    class validator det
```

A gate runs after **every** stage. The human may proceed, send the run back
to **any** earlier stage with feedback (recorded in `state.human_feedback`
and injected into that stage's prompt), or stop. `validator` is deterministic
(no LLM); hard flags auto-route to `builder` with the flags as feedback.

## Autonomy and the cost ceiling

`autonomy_until` is one value: `""` asks at every gate, a stage name
auto-proceeds gates before it, `END` is fully autonomous. Switchable per run.
Cycling is unbounded; the only bound is a configurable cost/call ceiling
(`helix.toml [limits]`) that **pauses and snapshots** (resumable) instead of
raising — interactively it offers to continue (doubling the ceiling).

## Snapshots

Every stage and every send-back mints an immutable snapshot: stage-stamped,
deterministic, **zero LLM calls** (it reuses the decision text the stage
already produced). Artifact bytes are content-addressed under
`.helix/snapshots/<project>/objects/<sha>` (deduped), so a snapshot stays a
few KB across hundreds of cycles. Each records `parent` + `branch`, so the
history is a real DAG: list / show / diff / diagram / branch / revert /
resume-from-any. See [snapshots.md](snapshots.md).

## Storage layout

```
<project>/                 # HELIX_HOME or cwd
├── helix.toml             # [atlas].path, [limits], [default]/[lightspeed], [cli.*]
├── .helix/
│   ├── .env               # CLAUDE_CODE_OAUTH_TOKEN / API keys
│   └── snapshots/<proj>/  # <id>.json, index.json, objects/<sha>
├── atlas/                 # the persistent wiki (configurable path)
│   ├── index.md  log.md  sources/ concepts/ entities/
│   └── projects/<proj>/   # overview.md, decisions.md, .decisions.json,
│       └── artifacts/     #   timeline.md, sandbox-confined code
├── agents/<stage>.md      # optional per-project agent overrides
└── raw/<proj>/            # immutable copies of ingested input
```
