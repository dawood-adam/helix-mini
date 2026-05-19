# Using Helix

Helix is driven through an MCP client. This guide uses Claude Code.

## Create a project

```bash
helix init my-research
cd my-research
```

This writes:

- `question.md` — the research question. Edit it.
- `helix.toml` — configuration: the Atlas path and the run limits.
- `CLAUDE.md` — instructions the client reads when you say "start helix".
- `.mcp.json` — registers the `helix-mcp` server for this project.

Add source material anywhere under the project, or drop it into
`atlas/inbox/` for managed ingestion. Open the folder in Claude Code; it
starts `helix-mcp` automatically.

## Driving a run

Work in plain language. The client calls Helix's tools.

```text
you>   start helix
helix> What should we call this project?
you>   smartphone-bp
helix> One-sentence research question?
you>   Cuffless BP from smartphone rPPG
helix> How should it run?
       1 step-by-step   2 auto up to a stage   3 fully autonomous
you>   1
helix> Source folder?
you>   ./papers
helix> Scout finished. Decision: 2 candidate approaches; recommends #1.
       Proceed, send back, or stop?
you>   send back to scout — restrict to 2024 papers only
helix> Re-ran Scout with that directive. Planner is done. Proceed?
you>   run autonomously until the validator
helix> ...
```

`hx_start` runs that setup conversation through MCP elicitation and starts
the pipeline. `run_pipeline(folder, autonomy_until)` is the same run without
the wizard.

## Control modes

The control mode becomes a `Plan` that governs every gate:

| Mode | Behaviour |
|---|---|
| step-by-step | Pause and ask at every transition (default). |
| auto up to a stage | Auto-proceed until that stage, then ask. |
| fully autonomous | Never ask; deterministic routing only. |

At a paused gate you may **proceed**, **send the run back** to any earlier
stage with a directive (threaded into that stage when it re-runs), or
**stop**. Declining a gate prompt pauses the run; it is resumable from the
last snapshot. You can change the plan mid-run with `hx_run_plan_set`.

## A run, end to end

1. **Scout** reads the Atlas and the sources, proposes approaches, and
   writes source pages.
2. **Methods Critic** evaluates and recommends an approach.
3. **Planner** writes a validation plan with numeric bands.
4. **Builder** writes code artifacts and reports metrics.
5. **Validator** (deterministic, no model) checks metrics against the bands;
   a hard miss routes back to the Builder with the flags as feedback.
6. **Results Critic** judges the outcome and returns a verdict.

Every stage emits a Decision Card and a snapshot. Every send-back is
snapshotted too, so the whole run is a branchable history. The next
project's Scout reads the same Atlas, so knowledge compounds.

## Observing and resuming

- `hx_run_status` / `hx_run_events` — the latest run's state and transition
  trail (persisted; survives a server restart).
- `snapshot_list` / `snapshot_show` / `snapshot_diff` / `snapshot_timeline`
  — the history.
- `resume_pipeline(project, snapshot, at=, branch=)` — rebuild a snapshot's
  state and re-enter at any stage; a new branch keeps an experiment off the
  main line.
- `snapshot_revert` — write a snapshot's artifacts back to disk without
  running anything.
- The `hot://<project>` resource is a one-page working-state cache,
  regenerated at run end. Read it first when resuming.

## Limits

`helix.toml [limits]` sets `token_cap` and `call_cap`. The token figure is a
server-side estimate (sampling does not report usage). Reaching a cap pauses
the run and records a resumable snapshot; interactively, you are offered the
choice to raise the ceiling instead.

## Component guides

- [forge.md](forge.md) — the pipeline and its agents
- [atlas.md](atlas.md) — the wiki, ingest, recall, lint
- [snapshots.md](snapshots.md) — the version-control model
- [mcp.md](mcp.md) — the full tool, resource, and prompt surface
