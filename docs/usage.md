# Using Helix

## Create a project

```bash
helix init my-research
cd my-research
```

This writes three files:

- `question.md` — your research question. Edit it.
- `helix.toml` — the only configuration. Defaults are repo-local: the Atlas
  is `./atlas`, snapshots are `./.helix/snapshots`.
- `CLAUDE.md` — the instructions Claude Code reads when you say "start helix".

Add your source files (PDF, markdown, code, data) to the folder.

## Drive it from Claude Code (recommended)

Open Claude Code in the project and work in plain language:

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
helix> ... (runs the gates automatically, stops at the Validator)
```

The scaffolded `CLAUDE.md` makes Claude Code: ask which sources to use and
confirm the question before running anything; run the pipeline and stop at
every stage with a short report; carry out your decision (proceed, send back
to any earlier stage with feedback, or stop); honor "run autonomously until
<stage>"; and use the snapshot and Atlas commands when you ask.

Helix's interface is tool-agnostic — it is a CLI plus a terminal review
prompt, usable by any human or agent. The conversational, zero-setup path is
optimized for Claude Code, which reads `CLAUDE.md` automatically. Another
agentic CLI (Cursor, Aider, a Codex/Gemini CLI, your own) can drive Helix the
same way if you point it at the project's `CLAUDE.md` instructions through
whatever rules mechanism that tool uses.

## What actually runs the agents

It is worth being precise, because two different Claude roles are involved:

- The Claude Code session you type into is the **conductor**. It reads
  `CLAUDE.md`, runs the `helix run` command, and relays gate reports to you.
  It does not run Scout, Planner, and the rest itself.
- `helix run` powers each LLM stage by spawning its **own headless `claude`
  subprocess per stage** (the `cli/claude` engine), authenticated by your
  subscription token. No API key is involved.

So Claude Code calling the backend *and* Claude powering the agents are both
true — but it is a different Claude: the conductor invokes `helix run`, and
`helix run` spawns a fresh model process for each of the five LLM stages. What
runs the stages is decided by engine resolution:

| You have | Stages run on |
|---|---|
| a Claude subscription token (OAuth) | `claude` CLI subprocesses — no API key |
| an API key only | the Anthropic/OpenAI API via litellm (`helix[sdk]`) |
| `--local` | Ollama + Qwen, fully offline |

OAuth wins: a subscription token always beats a stray `ANTHROPIC_API_KEY`, so
you are never billed for the API by accident.

## Run it directly

The chat layer is optional. `helix run` is the same pipeline without it, and
is exactly what the conductor calls:

```bash
helix run .
```

It pauses after each stage and prints a report:

```
── gate after planner ──
  decision : Plan: CFD cardiac model
  rationale: Designed validation plan with success criteria
[p]roceed / [g]o back to a stage / [s]top:
```

`p` proceeds; `g` sends the run back to any stage with feedback (no iteration
cap); `s` stops.

## A run, end to end

One project, showing how the pipeline, the Atlas, and snapshots fit together:

1. **Scout** ingests the folder, reads the Atlas index (anything earlier
   projects learned is already available), proposes approaches, and writes a
   source page per file to the Atlas.
2. **Methods Critic** picks an approach; **Planner** writes a plan with
   numeric bands and a plan page; **Builder** writes code artifacts and
   reports metrics.
3. **Validator** checks those metrics against the plan's bands. A `HARD:`
   miss loops back to the Builder with the flags as feedback.
4. **Results Critic** judges the outcome, writes the project overview page,
   and returns a verdict.
5. A snapshot is minted after **every** stage and **every** send-back, so the
   whole run is a git-style history you can diff, branch, and resume.
6. The next project's Scout reads the same Atlas, so concepts and entities
   compound across projects instead of starting from scratch.

The result: validated artifacts, a full decision log, a branchable snapshot
history, and a wiki that is richer than before the run. See
[pipeline.md](pipeline.md) for what each stage does in detail and
[snapshots.md](snapshots.md) for the snapshot model.

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
setup. The API path and `--engine sdk` need `helix[sdk]`.

## The Claude agent

`helix agent` is a separate, scriptable entry point, distinct from driving
Helix conversationally inside Claude Code:

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
