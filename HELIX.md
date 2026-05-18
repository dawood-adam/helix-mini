# Helix — system design

Helix turns a folder of source material into validated, contextualized code,
with a human checkpoint after every step, a wiki that compounds knowledge
across projects, and a git‑style snapshot of every step.

This is the canonical design. It consolidates the earlier v2/v3 notes into one
opinionated, deliberately simple plan, and it is honest about what is built
today versus what is planned.

## Principles

1. **Simple beats clever.** Markdown files, a tiny index, a manifest. No graph
   DB, no embeddings infrastructure, no event‑sourcing rewrite until scale
   demands it.
2. **One control plane.** Everything an agent or human does goes through one
   surface that enforces the sandbox, the integrity invariants, and the
   fail‑closed permission gate. Disk is durable truth; the control plane is
   the only validated way to mutate it.
3. **The driver is the brain; Helix is the engine.** Helix runs the process;
   the agent (normally the Claude Code session you're already in) does the
   thinking. This keeps subscription use interactive and ToS‑clean.
4. **Capture must be effortless.** Drop a file in a folder; it is taken care
   of. No formats to learn, no commands required.
5. **Nothing is lost.** Every stage and every redirection is an immutable
   snapshot you can diff, branch, revert, and resume.

## Architecture at a glance

```
 inbox ─► Forge:  Scout → Methods Critic → Planner → Builder → Validator → Results Critic ─► code
                    │        │         │        │         │            │
                    ▼        ▼         ▼        ▼         ▼            ▼
                 Atlas (LLM‑maintained markdown wiki; compounds across projects)
                    │        │         │        │         │            │
                    ●────────●─────────●────────●─────────●────────────●   snapshot at
                                  │                    │                  every transition
                                  ●──●─►              ●──●─►  branches
   Claude Code ──── MCP (planned) / CLI (today) ────► Helix ─► Forge · Atlas · Snapshots
```

Three pillars, one surface on top. Today the surface is the `helix` CLI plus
the relay/MCP roadmap below; the pillars themselves are built and working.

## Status: built vs planned

| Capability | State |
|---|---|
| Forge pipeline, 6 markdown agents, deterministic Validator | **built** |
| HITL gate after every stage; send‑back to any stage with feedback; `autonomy_until`; cost‑ceiling pause (resumable) | **built** |
| Atlas wiki (sources/concepts/entities/projects + index/log), sandboxed writes | **built** |
| Snapshots v2: content‑addressed objects, parent/branch DAG, list/show/diff/diagram/revert/resume | **built** |
| Dual orchestrator (plain loop default; LangGraph behind `helix[sdk]`) with conformance test | **built** |
| **Frictionless `atlas/inbox/` ingest (manifest delta, idempotent)** | **built (this change)** |
| Relay engine (interactive agent powers the stages; no `claude -p`) | planned — design frozen |
| MCP‑centered control plane (pipeline/atlas/snapshot tools, fail‑closed) | planned — design frozen |
| Localhost status + control dashboard | planned — design frozen |
| Ecosystem optimizations (body search, bi‑temporal, auto‑routing recall) | planned — optional |

## Pillar 1 — Forge (the pipeline)

Six agents, each a markdown file in `helix/builtin_agents/`. A gate runs after
every stage. The deterministic Validator is a numeric bounds check (no LLM).

```bash
helix run .                                 # review after every stage
helix run . --autonomous-until builder      # auto until a stage, then ask
helix run . --auto                          # fully autonomous
helix run . --engine sdk                    # same pipeline, LangGraph runner
```

At a gate you answer `p` (proceed), `g` (send back to any stage with a note,
which is injected into that stage on re‑run), or `s` (stop). There is no
iteration cap; the bound is a configurable cost ceiling that pauses
(resumably) rather than failing. See [docs/pipeline.md](docs/pipeline.md).

## Pillar 2 — Atlas (the LLM wiki)

A markdown wiki that every stage reads and writes and that persists across
projects — the Karpathy "LLM wiki" pattern: knowledge is maintained, not
re‑derived per query.

```
atlas/
├── index.md  log.md            # catalog + chronological, both greppable
├── inbox/                      # DROP ZONE  (+ .manifest.json)
├── raw/inbox/                  # archived originals after ingest
├── sources/ concepts/ entities/
└── projects/<id>/              # per‑project notes, decisions, timeline
```

```bash
helix atlas ingest                # process the whole inbox (see below)
helix atlas search cardiac        # keyword search over the index
helix status                      # page count, projects, inbox backlog
helix log <project>               # the decision narrative
```

The wiki stays simple on purpose: an `index.md` the LLM reads first, plain
markdown pages, no vector DB. Retrieval improvements (body search, tiers) are
roadmap items, not prerequisites.

## Pillar 3 — Snapshots (git‑style version control)

A snapshot is minted after every stage and every send‑back. It costs no LLM
calls (it reuses the stage's own decision text) and artifacts are
content‑addressed, so a snapshot stays a few KB across hundreds of cycles.

```bash
helix snapshots list my-research
helix snapshots show my-research 7
helix snapshots diff my-research 5 7
helix snapshots diagram my-research                 # Mermaid gitGraph
helix snapshots resume my-research 5 --at planner --branch retry
helix snapshots revert my-research 5                # restore that snap's files
```

See [docs/snapshots.md](docs/snapshots.md).

## Frictionless ingest (built)

Drop anything supported into `atlas/inbox/` and it is taken care of: hashed,
archived to `atlas/raw/inbox/`, and written as a first‑class, searchable
`sources/<slug>.md` page. A sha256 `.manifest.json` makes re‑ingest
idempotent and records provenance. No LLM call, no formats to learn.

```bash
# capture: any of these — Obsidian Web Clipper, "Print to PDF", or just:
cp ~/Downloads/chen2025.pdf  ./atlas/inbox/
cp ~/notes/protocol.md       ./atlas/inbox/

helix atlas ingest                       # process everything new
#   + chen2025.pdf  -> sources/chen2025.md
#   + protocol.md   -> sources/protocol.md
#   Ingested 2, skipped 0 (already known), 0 still pending.

helix atlas ingest paper.md              # or process one file
helix status                             # warns if the inbox has a backlog
```

Re‑dropping the same content is a no‑op (recognized by hash). A modified file
(new hash) is re‑ingested. Scout sees these pages via the Atlas index on the
next run and refines them into proper summaries. This is the deterministic
capture layer; the LLM refinement layer is the pipeline.

## The MCP‑centered refactor (planned, design frozen)

The target: Helix is one process exposing every capability — run/progress the
pipeline, search/expand the Atlas, create/branch/diff/revert/version
snapshots — as gated MCP tools. The pipeline is an in‑memory paused coroutine:
at each thinking step and each gate it `await`s an answer. **Who answers is
the only variable** — normally the interactive Claude Code session that is the
MCP client (no `claude -p`, no metered credit, no token handling); optionally
a built‑in engine (`claude -p`/API/local) for standalone/CI.

A human watches and steers the same process through a tiny localhost
dashboard: `GET /state` (render the live stage, reports, current version,
assumptions) and `POST /decision` (the gate decisions only). The agent's
inference and the human's gate decision resolve the *same* awaited value;
everything downstream is the unchanged, sandboxed, snapshotted pipeline — so a
relay run is byte‑for‑byte a normal run. Atlas browsing is Obsidian over
`./atlas/`.

Frozen decisions: engine name `relay`; default = relay inside Claude Code,
unchanged engine resolution in a plain terminal; HTTP‑transport MCP daemon so
the dashboard and agent attach to one process; `helix agent` (Agent‑SDK
driver, the metered path) removed in favor of this; dashboard controls = gate
decisions + stop only; `core/` untouched (the refactor is a new front + an
async seam, not a pipeline rewrite).

### Planned tool surface (summary)

- **pipeline**: `pipeline_start`, `pipeline_next`, `pipeline_submit`,
  `pipeline_status`, `pipeline_stop`
- **atlas**: `atlas_search`, `atlas_get`, `atlas_ingest`, `atlas_put` (gated),
  `atlas_promote` (gated), `atlas_lint`
- **snapshots**: `snapshot_list/show/diff/timeline`, `snapshot_branch`,
  `snapshot_revert`, `snapshot_resume` (mutating ones gated)

All mutating tools pass the existing fail‑closed gate; reads auto‑approve;
unlisted tools (incl. SDK Bash/Write/Edit) denied.

## Improvements adopted from the ecosystem

From a scan of how LLM‑wiki and agent‑memory systems converged in 2026
(Karpathy's LLM‑wiki pattern; SwarmVault/OpenKB; Graphiti's bi‑temporal model;
Cognee's graph‑native recall; Mem0):

| Idea | Decision |
|---|---|
| Drop‑folder + manifest delta ingest | **Adopted now.** Every shipping wiki converged here; it is the simplest correct capture. |
| `index.md` + `log.md`, no RAG infra | **Already ours.** Keep. |
| LLM wiki = maintained, not re‑derived | **Already our core thesis.** |
| Body/lexical search fallback (grep over pages) | **Roadmap.** Today search is index‑only; a grep fallback over page bodies is a small, high‑value add. |
| Bi‑temporal page metadata (Graphiti) — `claim_valid_at` + `last_verified_at` | **Roadmap, optional.** Useful for a future linter; not worth the complexity for v1. |
| Auto‑routing recall (Cognee) — one search tool picks lexical/semantic/graph | **Roadmap, optional.** Revisit only if the index‑first model strains. |
| Hot‑context cache at session boundary | **Roadmap.** Cheap, helps "where were we"; pairs well with the dashboard. |
| Graph DB / embeddings | **Declined for now.** SQLite/markdown handles hundreds of pages; revisit only at scale. |

The throughline: adopt the simple, proven capture pattern now; treat the
graph/temporal/embedding machinery as optional later optimizations, not
foundations.

## Build order

| Phase | Scope | State |
|---|---|---|
| — | Pillars (Forge, Atlas, Snapshots), dual orchestrator, HITL | done |
| **A** | Frictionless inbox ingest + manifest + CLI | **done (this change)** |
| B | Relay coroutine seam (async LLM + gate awaits), behind current API | next |
| C | `helix serve` MCP daemon + pipeline tools + reused fail‑closed gate | |
| D | Atlas + snapshot tools on the server | |
| E | Localhost dashboard (`/state`, `/decision`) | |
| F | Remove `helix agent`; relay default inside Claude Code; docs | |
| G | Optional: body search, hot cache, then revisit temporal/recall | |

Each phase ships standalone with the suite green; `core/` stays untouched.

## Explicitly not doing

- No event‑sourcing rewrite (the snapshot DAG is canonical truth).
- No multi‑user/auth (local‑first, single user).
- No graph DB or self‑hosted embeddings until scale demands.
- No capability tiers / audit subsystem / cost accounting beyond the existing
  ceiling.
- No removal of the CLI — it remains the standalone path alongside MCP.
