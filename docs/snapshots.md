# Snapshots — version control

A snapshot is a saved point in a run: the full pipeline state at one
transition, stamped with the stage, time, parent, and branch. A run opens
with a `start` snapshot (so it is resumable before the first stage even
completes), then Helix mints one after every stage and every send-back. The
history is a real DAG — inspectable, diffable, branchable, and resumable
from any point.

## Zero cost

A snapshot calls no model. It serializes state and stores the stage's
Decision Card as the human-readable digest — content the stage already
produced. Artifact bytes are content-addressed under
`.helix/snapshots/<project>/objects/<sha256>` and referenced by hash;
identical files across iterations are stored once and the state record never
inlines bytes. A snapshot stays a few kilobytes after hundreds of cycles,
which is why per-stage snapshots are affordable and cycling has no fixed cap.

## Storage

```
.helix/snapshots/<project>/
├── <id>.json        one snapshot (state + Decision Card + manifest)
├── index.json       the ordered DAG (id, parent, branch, stage, ts)
├── refs.json        {tags: {...}, branches: {...}}
└── objects/<sha>    content-addressed artifact bytes
```

## Inspecting

| Tool | Shows |
|---|---|
| `snapshot_list` | The DAG, git-log style. |
| `snapshot_show` | One snapshot's key state. |
| `snapshot_diff` | Tracked differences between two snapshots. |
| `snapshot_timeline` | A Mermaid `gitGraph` of the history. |

## Branch, freeze, fork

| Tool | Effect |
|---|---|
| `hx_snap_branch` | Name a branch ref at a snapshot. |
| `hx_snap_freeze` | Tag a snapshot immutable for publication. |
| `hx_snap_fork` | Export the full history (snaps + objects + index + refs) as `forks/<name>.tar.gz` — a self-contained, reproducible bundle. |

A branch ref names a point; continuation happens by resuming with that
branch name, which keeps an experiment off the main line.

## Resume and revert

- `resume_pipeline(project, snapshot, at=, branch=, folder=)` rebuilds the
  snapshot's full state, including artifact bytes from the object store, and
  re-enters the agent-driven loop — returning the next stage's prompt. By
  default it re-enters at the snapshot's own stage; `at` picks any stage;
  `branch` continues on a new branch parented at that snapshot; `folder`
  roots it at the project regardless of the server's working directory.
- `snapshot_revert` is the file-level checkout: it writes a snapshot's
  artifacts back to disk and runs nothing.

There is no separate `checkout`. `resume_pipeline` (branched continuation)
and `snapshot_revert` (restore a tree) cover it without a redundant
destructive operation.

## Pausing

A run that hits the token/call ceiling, has its gate prompt declined, or
loses the MCP client mid-run records a resumable snapshot and stops rather
than failing. `hx_run_status` reports where it stopped; `resume_pipeline`,
or simply calling `hx_step` again, continues it.
