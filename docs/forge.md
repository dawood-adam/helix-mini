# Forge — the pipeline

Forge turns source material into validated artifacts through six stages, with
a human checkpoint at every transition. A `model` stage is answered by the
client agent through the tool loop (`hx_step` renders its prompt,
`hx_submit` feeds back the answer); the server runs no model itself.

```
Scout → Methods Critic → Planner → Builder → Validator → Results Critic
```

## The stages

| Stage (id) | Kind | Does |
|---|---|---|
| Scout (`scout`) | model | Reads the Atlas and the sources; proposes candidate approaches; writes source pages. |
| Methods Critic (`critic_methods`) | model | Evaluates the candidates; recommends one. |
| Planner (`planner`) | model | Writes a validation plan with numeric bands. |
| Builder (`builder`) | model | Writes code artifacts; reports metrics. |
| Validator (`validator`) | deterministic | Checks metrics against the plan's bands. No model, no cost. |
| Results Critic (`critic_results`) | model | Judges the outcome; returns a verdict. |

Stages are markdown files in `helix/builtin_agents/`. A project may override
any of them with `agents/<stage>.md` — no code change. Frontmatter declares
the stage order, kind, and whether the stage may write the Atlas; the body
is the system prompt and output contract. The Validator is deterministic: it
dispatches to a registered Python function and never calls a model. A hard
band miss routes the run back to the Builder with the flags as feedback.

## The Decision Card

Every agent emits one structured object alongside its domain output:

```
summary · key_findings · assumptions · open_questions
· directive_for_next · confidence
```

It is the single human-readable record of a stage. The snapshot stores it
(so snapshotting stays zero-LLM), the gate prompt shows it, and the hot cache
is built from it. If a model omits or mangles the card, a generic one is
derived so a run never blocks on a missing field.

## Gates and the Plan

After each stage, `gates.decide_gate` resolves the transition. Whether a gate
auto-proceeds or asks is decided by the run-scoped **Plan** (`core.plan`):

- empty plan — ask at every gate (step-by-step);
- `auto_until` a stage — auto-proceed until there, then ask;
- explicit steps — per-stage autonomy, with an optional directive injected
  into that stage.

`autonomy_until` (`''`, a stage name, or `END`) is a compatibility
constructor for the Plan. The Plan is run-scoped — threaded through the loop,
never stored in pipeline state — and can be changed mid-run with
`hx_run_plan_set`. The deterministic routes (a hard validator miss; a
Results-Critic `iterate` verdict) apply regardless of autonomy.

At an interactive gate the decision is **proceed**, **send back** to any
earlier stage with a directive, or **stop**. A send-back records the directive
against the target stage; that stage's prompt includes it on the re-run.
Declining the gate prompt pauses the run resumably.

## The run registry

`runs.py` records each run under `.helix/runs/<run_id>/`: a `record.json`
(status, current stage, last snapshot, token estimate) and an
`events.jsonl` transition log, updated at every transition. The live record
also holds the run's `Plan`, so `hx_run_plan_set` steers it and
`hx_run_status` / `hx_run_events` observe it. A run spans many tool calls
(`hx_step` / `hx_submit`); the suspended step is persisted to
`.helix/runs/<project>.pending.json` so even a server restart between steps
is resumable. The registry adds observability and survives a restart; live
continuation is via snapshots and `resume_pipeline`.

## Cost ceiling

Cycling has no fixed cap. `helix.toml [limits]` sets `token_cap` and
`call_cap`. The token count is an estimate (≈ chars/4) of each stage's
rendered prompt plus the agent's submitted answer. Reaching a cap pauses the
run with a resumable snapshot; interactively, you are offered the choice to
raise the ceiling and continue.
