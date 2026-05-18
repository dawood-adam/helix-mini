# Usage

## Set up a project

```bash
helix init my-research      # creates question.md, CLAUDE.md, helix.toml
cd my-research
# add source files (PDF/markdown/code/data), edit question.md
```

`helix.toml` is the only configuration. Defaults are repo-local: the Atlas is
`./atlas`, snapshots are `./.helix/snapshots`. Override `[atlas].path` or set
`HELIX_HOME` to relocate.

## Run with human-in-the-loop (default)

```bash
helix run .
```

After every stage Helix prints a report (decision, rationale, state summary)
and asks:

- **`p` proceed** — continue to the next stage.
- **`g` go back** — pick *any* stage and type feedback. The run re-enters
  there; your note is injected into that stage's prompt on the re-run and
  recorded in the decision/snapshot trail. Cycling is unbounded.
- **`s` stop**.

`critic_results` reports a verdict (ship / iterate / abandon); `iterate` is
just a send-back to `builder`. The deterministic `validator` auto-routes hard
band violations back to `builder` with the flags as feedback.

## Autonomy

```bash
helix run . --autonomous-until builder   # auto-proceed gates before builder, then ask
helix run . --auto                       # fully autonomous (no gates)
```

Mode is per run; resume with a different mode any time.

## Engines (model-agnostic)

```bash
helix run .                       # auto: OAuth subscription > API key
helix run . --cli claude          # force the Claude CLI engine (no API key)
helix run . --lightspeed          # cheapest model + auto gates
helix run . --local --model-size medium     # offline Qwen via Ollama
helix run . --local-recommended   # simple stages local, critical via cloud
helix run . --engine sdk          # same pipeline via the LangGraph runner
```

Auth lives in `.helix/.env` (or `helix setup`). **OAuth wins**: a
`CLAUDE_CODE_OAUTH_TOKEN` always beats `ANTHROPIC_API_KEY`. The API path and
`--engine sdk` need `helix[sdk]`.

## Driving from Claude Code (CLI-driven mode)

`helix init` writes a `CLAUDE.md` so an agentic CLI opened in the folder knows
to run `helix run .`, relay each gate report, and use the snapshot commands.
The CLI itself is the model — no API key. This is the primary mode.

## The Claude agent

```bash
helix agent show the timeline for my-research and resume it from snap-5
helix agent                       # interactive
```

Read tools (atlas/decision/snapshot) auto-approve; `run_pipeline`,
`resume_pipeline`, `snapshot_revert` are human-gated. The gate is
**fail-closed**: every other tool, including the SDK's Bash/Write/Edit, is
denied and hard-blocked. Needs `helix[agent]`.

## Cost ceiling

`helix.toml [limits] cost_cap / call_cap` bound a run. On reaching the
ceiling: interactively you are asked to continue (doubles the ceiling) or
stop; autonomously the run **pauses** (a snapshot is minted) and prints a
`helix snapshots resume` line. It never silently dies.

## Snapshots & resume

See [snapshots.md](snapshots.md). Common:

```bash
helix snapshots list my-research
helix snapshots resume my-research 5 --at planner --branch retry --auto
helix snapshots revert my-research 5      # restore that snapshot's artifacts
```
