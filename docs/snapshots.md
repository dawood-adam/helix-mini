# Snapshots

## The idea

A snapshot is a saved point in a run: the full pipeline state at one stage,
stamped with the stage name and time. Helix takes one after every stage and
every send-back, automatically. Think of it as git for the pipeline: a
branchable history you can inspect, diff, and resume from any point.

## Why it is free

A snapshot costs no LLM calls. It reuses the decision text the stage already
wrote for the gate as its human-readable summary, so nothing is generated on
the fly.

Generated artifacts are content-addressed. Each file's bytes are stored once
under `.helix/snapshots/<project>/objects/<sha256>` and referenced by hash.
Identical files across iterations are stored once, and the state record never
inlines artifact bytes. A snapshot stays a few kilobytes even after hundreds
of refine cycles. That is why per-stage snapshots are affordable and why
cycling has no fixed cap.

## Commands

Each snapshot records its `id`, `parent`, and `branch`, so the history is a
real DAG rather than a flat list.

| git | Helix |
|---|---|
| `git log` | `helix snapshots list <project>` |
| `git show` | `helix snapshots show <project> <id>` |
| `git diff A B` | `helix snapshots diff <project> <a> <b>` |
| graph view | `helix snapshots diagram <project>` (writes a Mermaid `gitGraph`) |
| `git checkout -- .` | `helix snapshots revert <project> <id>` |
| `git checkout <ref>` then continue | `helix snapshots resume <project> <id> [--at STAGE] [--branch NAME]` |

## Resume

`resume` rebuilds the snapshot's full state, including artifact bytes from the
object store, and re-enters the pipeline. By default it re-enters at the
snapshot's own stage; `--at STAGE` picks any stage. `--branch NAME` continues
on a new branch whose parent is that snapshot, so an experiment never
overwrites the main line. `resume` accepts the same engine and autonomy flags
as `run`.

```bash
helix snapshots resume cardiac 7                          # from snap-7's stage
helix snapshots resume cardiac 5 --at planner --branch replan --auto
```

## Revert

`revert` is the file-level checkout. It writes a snapshot's artifacts back
into the project's `artifacts/` directory and runs nothing.

```bash
helix snapshots revert cardiac 5
```

## Inspecting raw files

Snapshots are plain JSON under `.helix/snapshots/<project>/`:

```bash
python -m json.tool < .helix/snapshots/cardiac/7.json   # state.code_artifacts is []
ls .helix/snapshots/cardiac/objects/                     # artifact bytes by hash
```
