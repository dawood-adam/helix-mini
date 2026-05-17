# Working with the Atlas

## Goal

Explore and query the Atlas wiki after pipeline runs. The Atlas is a persistent knowledge base that accumulates findings across all projects.

## Prerequisites

- At least one completed pipeline run (to populate the Atlas)

## Checking Atlas Status

```bash
helix-mini status
```

Example output:
```
Atlas: /Users/you/.helix-mini/atlas
Pages: 12

Projects: cardiac-sim, protein-fold
```

## Searching the Atlas

Search by keyword across all pages:

```bash
helix-mini atlas search "cardiac"
```

Example output:
```
--- Cardiac Modeling Study (sources/paper1.md) ---
CFD-based cardiac simulation paper. The study examines...
...

--- Test Project Overview (projects/cardiac-sim/overview.md) ---
CFD cardiac simulation — shipped with 0.91 accuracy...
```

Searches match against page titles and paths in `index.md`. Up to 20 results are returned with a 500-character content preview.

## Viewing Decision Logs

Each pipeline run records every decision made at every gate:

```bash
helix-mini log cardiac-sim
```

Example output:
```
# Decision Log

## [2026-05-17T04:33:00+00:00] scout
**Decision:** Identified 2 approaches
**Rationale:** Ingested sources and analyzed for research directions

## [2026-05-17T04:33:05+00:00] gate_scope
**Decision:** proceed
**Rationale:** 2 approaches proposed
...
```

## Atlas Directory Structure

All data lives at `~/.helix-mini/atlas/` (or `$HELIX_MINI_HOME/atlas/`):

```
atlas/
├── index.md              # Page registry (one line per page)
├── log.md                # Timestamped audit log
├── sources/              # Ingested source material summaries
├── concepts/             # Key concepts identified by agents
├── entities/             # Named entities (people, datasets, etc.)
└── projects/
    └── cardiac-sim/
        ├── overview.md       # Project summary
        ├── .decisions.json   # Decision log (JSON)
        ├── decisions.md      # Decision log (markdown)
        ├── artifacts/        # Builder-written code (sandbox-confined;
        │   └── src/sim.py    #   rewritten in place on each refine pass)
        └── .snapshots/
            ├── snap-1.json   # State after scout
            ├── snap-2.json   # State after critic_methods
            └── snap-N.json   # One per pipeline stage (+ each refine loop)
```

## Browsing Pages Directly

Atlas pages are plain markdown files. You can read them directly:

```bash
cat ~/.helix-mini/atlas/index.md
cat ~/.helix-mini/atlas/sources/paper1.md
cat ~/.helix-mini/atlas/projects/cardiac-sim/overview.md
```

## Inspecting Snapshots

Snapshots capture the full pipeline state after each major stage. They're JSON files you can inspect:

```bash
cat ~/.helix-mini/atlas/projects/cardiac-sim/.snapshots/snap-1.json | python -m json.tool
```

Each snapshot contains:
- `timestamp` — When the snapshot was taken
- `stage` — Pipeline stage at the time
- `state` — Full `ForgeState` as a dict (all 20 fields)

## Exploring the Atlas Conversationally

Instead of `status` / `atlas search` / `log`, you can ask a Claude agent
(requires `pip install '.[agent]'`):

```bash
helix-mini agent what do we know about cardiac modeling and show the decision log
helix-mini agent          # interactive session
```

Just type the request after `agent` — no quotes. (Avoid shell glob characters
like `?` or `*` in an unquoted prompt; phrase it without them, or quote it.)

The agent uses read-only Atlas tools automatically; launching a new pipeline
run from the agent requires explicit terminal confirmation. See
[Driving helix-mini with a Claude Agent](claude-agent.md).

## How the Atlas Compounds

The Atlas persists across all pipeline runs. When the scout agent runs for a new project, it reads the existing Atlas index to see what's already known. This means:

- Knowledge from project A is available when analyzing project B
- Running the same folder again will build on previous findings
- Concepts and entities accumulate over time
