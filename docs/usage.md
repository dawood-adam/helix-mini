# Usage

## Create a project

```bash
helix init my-research
cd my-research
```

This writes three files:

- `question.md` — your research question. Edit it.
- `helix.toml` — the only configuration. Defaults are repo-local: the Atlas
  is `./atlas`, snapshots are `./.helix/snapshots`.
- `CLAUDE.md` — instructions Claude Code reads when you say "start helix".

Add your source files (PDF, markdown, code, data) to the folder.

## From Claude Code (recommended)

Open Claude Code in the project and drive the pipeline in plain language:

```bash
claude
```

```
you>   start helix
helix> 6 files here (3 PDF, 2 .md, 1 .csv). Use all of them, or a subset?
you>   all of them; question.md is correct
helix> Scout proposed 2 approaches; I recommend #1. Proceed / send back / stop?
you>   proceed
helix> Methods Critic: the eval corpus is too narrow to support approach #1.
       Proceed, or send back?
you>   send it back to Scout, restrict to the 2024 papers
helix> Re-ran Scout with that note; Planner produced a 4-step plan. Proceed?
you>   run autonomously until the validator, then check with me
helix> ... (runs Planner→Builder gates automatically, stops at the Validator)
```

What the scaffolded `CLAUDE.md` makes Claude Code do:

1. On "start helix", ask which source material to use and confirm the
   question — it does not run anything until you say so.
2. Run the pipeline and **stop at every stage** with a short report.
3. Relay your decision: proceed, send the run back to any earlier stage with
   feedback, or stop. "Send it back to the planner, the bands are too loose"
   re-enters that stage with the note attached.
4. Honor "run autonomously until <stage>" and switch back to asking when it
   gets there.
5. Use the snapshot and Atlas commands when you ask ("diff the last two
   snapshots", "resume from snap-5 on a new branch").

No API key is involved: Claude Code itself is the model. This is a thin layer
over `helix run` — everything below applies underneath it.

## Run it directly

```bash
helix run .
```

The pipeline pauses after each stage and prints a report:

```
── gate after planner ──
  decision : Plan: CFD cardiac model
  rationale: Designed validation plan with success criteria
[p]roceed / [g]o back to a stage / [s]top:
```

- `p` — continue to the next stage.
- `g` — choose any earlier stage and type feedback. The run re-enters there
  with your note added to that stage's prompt. There is no iteration cap.
- `s` — stop.

The Results Critic ends with a verdict of ship, iterate, or abandon;
`iterate` is a send-back to the builder. The Validator is deterministic: a
hard band violation sends the run back to the builder automatically, with the
flags as feedback.

## Autonomy

```bash
helix run . --autonomous-until builder   # auto until builder, then ask
helix run . --auto                       # never ask
```

Autonomy is chosen per run. A resume can use a different setting, and from
Claude Code you can switch mid-run by saying so.

## Engines

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
`ANTHROPIC_API_KEY`, so a stray key never bills you by accident. The API path
and `--engine sdk` need `helix[sdk]`.

## The Claude agent

`helix agent` is a separate, scriptable entry point (distinct from driving
Helix conversationally inside Claude Code):

```bash
helix agent show the timeline for my-research and resume it from snap-5
helix agent                                   # interactive session
```

Read tools (Atlas, decision log, snapshots) are auto-approved. `run_pipeline`,
`resume_pipeline`, and `snapshot_revert` require confirmation. The gate is
fail-closed: every other tool, including the SDK's Bash, Write, and Edit, is
denied. Needs `helix[agent]`.

## The cost ceiling

`helix.toml` sets `cost_cap` and `call_cap` under `[limits]`. When a run
reaches the ceiling it does not crash or lose work:

- interactive: you are asked to continue (which doubles the ceiling) or stop.
- autonomous: it takes a snapshot, stops, and prints the resume command.

## Snapshots and resume

Every stage and every send-back is snapshotted. See
[snapshots.md](snapshots.md). Common commands:

```bash
helix snapshots list my-research
helix snapshots resume my-research 5 --at planner --branch retry --auto
helix snapshots revert my-research 5      # restore that snapshot's files
```
