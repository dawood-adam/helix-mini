# Snapshots — git-style version control

A snapshot is a timestamped, stage-stamped, deterministic serialization of the
full pipeline state. One is minted after **every stage** and **every
send-back**.

## Why it's cheap

A snapshot costs **zero LLM calls**. It reuses the decision/rationale the
stage already produced for the gate as its human-readable digest — nothing is
summarized on the fly. Artifact bytes are **content-addressed**: stored once
under `.helix/snapshots/<project>/objects/<sha256>` and referenced by hash
from a manifest. Identical artifacts across iterations are deduped, so a
snapshot stays a few KB even after hundreds of refine cycles. The pipeline
state blob never inlines artifact bytes.

So per-stage *and* per-send-back frequency is affordable; that is why cycling
is unbounded and the only real bound is the cost ceiling.

## The DAG

Each snapshot records `id`, `parent`, and `branch`, so the history is a real
git-style DAG, not a flat list.

| git | helix |
|-----|-------|
| `git log` | `helix snapshots list <project>` |
| `git show` | `helix snapshots show <project> <id>` |
| `git diff A B` | `helix snapshots diff <project> <a> <b>` |
| graph view | `helix snapshots diagram <project>` (Mermaid `gitGraph`) |
| `git checkout -- .` | `helix snapshots revert <project> <id>` (restore artifacts) |
| `git checkout <ref> && continue` | `helix snapshots resume <project> <id> [--at STAGE] [--branch NAME]` |

## Resume

`resume` rehydrates the snapshot's full state — including artifact bytes from
the object store — and re-enters the pipeline at `--at` (any stage; default
the snapshot's stage). `--branch NAME` continues on a new branch whose parent
is that snapshot, so experiments don't clobber the main line. Same engine and
autonomy flags as `run`.

```bash
helix snapshots resume cardiac 7                       # from snap-7's stage
helix snapshots resume cardiac 5 --at planner --branch replan --auto
```

`revert` is the file-level checkout: it writes a snapshot's artifacts back to
the project's `artifacts/` directory without running anything.

## Inspecting raw

Snapshots are plain JSON under `.helix/snapshots/<project>/`:

```bash
cat .helix/snapshots/cardiac/7.json | python -m json.tool   # state has code_artifacts: []
ls  .helix/snapshots/cardiac/objects/                        # artifact bytes by sha
```
