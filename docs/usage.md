# Usage

## 1. Create a project

```bash
helix init my-research
cd my-research
```

This writes three files:

- `question.md` — your research question. Edit it.
- `helix.toml` — the only configuration. Defaults are repo-local: the Atlas
  is `./atlas`, snapshots are `./.helix/snapshots`.
- `CLAUDE.md` — instructions an agentic CLI reads when you say "start helix".

Add your source files (PDF, markdown, code, data) to the folder.

## 2. Run with review (the default)

```bash
helix run .
```

After each stage Helix prints a report and waits:

```
── gate after planner ──
  decision : Plan: CFD cardiac model
  rationale: Designed validation plan with success criteria
  ...
[p]roceed / [g]o back to a stage / [s]top:
```

- `p` — continue to the next stage.
- `g` — choose any earlier stage and type feedback. The run re-enters there
  and your note is added to that stage's prompt. You can do this as many
  times as you want; there is no iteration cap.
- `s` — stop.

The Results Critic ends with a verdict of ship, iterate, or abandon. `iterate`
is simply a send-back to the builder. The Validator is deterministic: a hard
band violation sends the run back to the builder automatically, with the
flags as feedback.

## 3. Run with autonomy

```bash
helix run . --autonomous-until builder   # auto until builder, then ask
helix run . --auto                       # never ask
```

Autonomy is chosen per run. A resume can use a different setting.

## Choosing an engine

```bash
helix run .                                   # auto: OAuth, else API key
helix run . --cli claude                      # force the Claude CLI, no API key
helix run . --lightspeed                      # cheapest model, auto gates
helix run . --local --model-size medium       # offline, Ollama + Qwen
helix run . --local-recommended               # simple stages local, hard ones cloud
helix run . --engine sdk                      # same pipeline, LangGraph runner
```

Credentials live in `.helix/.env`, or run `helix setup` for a guided API-key
setup. OAuth wins: a `CLAUDE_CODE_OAUTH_TOKEN` always beats
`ANTHROPIC_API_KEY`. The API path and `--engine sdk` need `helix[sdk]`.

## Driving from Claude Code

`helix init` writes a `CLAUDE.md` so an agentic CLI opened in the folder knows
what to do. When you say "start helix" it first asks you to point out the
source material and confirm the question, then runs `helix run` and relays
each gate report back to you. The CLI is the model, so no API key is needed.
This is the primary way to use Helix.

## The Claude agent

```bash
helix agent show the timeline for my-research and resume it from snap-5
helix agent                                   # interactive session
```

Read tools (Atlas, decision log, snapshots) are auto-approved.
`run_pipeline`, `resume_pipeline`, and `snapshot_revert` require confirmation.
The gate is fail-closed: every other tool, including the SDK's Bash, Write,
and Edit, is denied. Needs `helix[agent]`.

## The cost ceiling

`helix.toml` sets `cost_cap` and `call_cap` under `[limits]`. When a run hits
the ceiling:

- interactive: you are asked to continue (which doubles the ceiling) or stop.
- autonomous: the run takes a snapshot, stops, and prints a resume command.

A run never fails silently or loses work at the ceiling.

## Snapshots and resume

Every stage and every send-back is snapshotted. See
[snapshots.md](snapshots.md). The common commands:

```bash
helix snapshots list my-research
helix snapshots resume my-research 5 --at planner --branch retry --auto
helix snapshots revert my-research 5      # restore that snapshot's files
```
