# Atlas — the wiki

The Atlas is the LLM-maintained research memory. It is plain markdown on
disk, so it is greppable and git-friendly, with a typed frontmatter header
that turns a folder of notes into a queryable knowledge base that compounds
across projects.

## Layout

```
atlas/
├── ATLAS.md          the schema, in plain English (the only config agents read)
├── index.md          one line per page
├── log.md            chronological write log
├── inbox/            drop zone + .manifest.json
├── raw/              ingested originals (immutable)
├── sources/  concepts/  entities/  projects/
└── projects/<id>/_hot.md     session working state
```

## Page schema

Every page is markdown with a YAML frontmatter header:

```yaml
id: atlas:concepts:rppg          # derived from the path
type: concept                    # concept|entity|source|method|finding|comparison
tier: canonical                  # scratch|active|canonical|published|archived
aliases: [rPPG, "remote photoplethysmography"]   # ≥1, mandatory
created_at / updated_at
claim_valid_at                   # when the strongest claim was made
last_verified_at                 # when reconciled against sources
provenance: {source, run_id}
links: {derived_from, related_to, contradicts, cites}
embeddings: {model, hash}
```

Three details matter:

- **Tiers** are a maturity ladder. A scratch note is not a published
  finding; `hx_atlas_promote` moves a page up and confirms at canonical or
  published.
- **Aliases** (at least one, enforced) drive duplicate detection across
  abbreviations and spellings. If an agent omits them, the title is used as
  the default — which the linter then flags as un-aliased.
- The **bi-temporal pair** records two clocks: when a claim was made versus
  when it was last re-verified. This is what makes "stale" a fact rather
  than a guess.

Writes are backward-tolerant: an agent may emit just
`{path, title, content, summary}` and the store fills sensible defaults, so
the schema never blocks a run. All writes pass the sandbox first.

## Ingest

Drop files (PDF, markdown, text, code, data) into `atlas/inbox/` and call
`hx_atlas_ingest` — the whole inbox, or one file by path. A
`.manifest.json` records each file's sha256, so re-running is idempotent and
a changed file is re-ingested. Each new file becomes a `type: source` page
and its original moves to `atlas/raw/`, keeping the inbox a clean drop zone.

## The graph

Page `links:` form a three-level structure:

- **Episodes** — the immutable sources in `raw/`.
- **Entities** — the pages, with typed edges declared in frontmatter.
- **Communities** — thematic clusters, computed on demand by label
  propagation; not stored.

The markdown is the source of truth. `atlas_index.build` materializes the
edges into an in-memory SQLite graph, rebuilt per query (milliseconds at this
scale), so `Atlas.write` carries no index cost. `hx_atlas_neighbors` returns
the k-hop neighbourhood of a page.

## Recall

`hx_atlas_recall` is one entry point with a query-shape router:

| Query shape | Mode | Method |
|---|---|---|
| an id or path | graph | k-hop traversal from that node |
| "everything / overview about X" | community | the cluster around the best hit |
| relational ("how does X relate to Y") | graph | seeded from the best lexical hit |
| five or more words | semantic | embedding cosine |
| short, specific | lexical | BM25 |

Recall returns **references only** — id, title, tier, ~120-char summary,
score. Bodies are fetched separately with `hx_atlas_get` (capped). This
find/fetch split keeps a search from flooding the model's context. If a
richer mode cannot run (no embeddings, no resolvable node) recall falls back
to lexical, so it never hard-fails.

### Embeddings

Semantic mode needs vectors. The client agent answers only in text, so
embeddings use a local model — `fastembed`, an optional extra (`pip install
'helix[embed]'`). This is the only model dependency in the system; without
it, semantic queries fall back to lexical. Vectors are cached in
`.helix/embeddings.json`, keyed by the page body's sha256, so only changed
pages are re-embedded.

## Lint

`hx_atlas_lint` is the hygiene sweep. Each check is exact or a cheap
heuristic, never fuzzy, so the output is trustworthy:

| Kind | Means |
|---|---|
| orphan | A page nothing links to and that links nowhere. |
| contradiction | An explicit `contradicts` edge between two pages. |
| stale | `last_verified_at` overdue; counts newer sources since. |
| missing-page | An internal link pointing at a page that does not exist. |
| unaliased | Only the auto-default alias (the title). |
| orphan-community | A cluster of ≥3 with no synthesis/comparison page. |

Each issue carries a suggested fix.

## Hot cache

At the end of a run, `atlas/projects/<id>/_hot.md` is regenerated from the
snapshot trail (zero-LLM — it reuses the last Decision Card): current head,
summary, open questions, the directive for the next stage, recently touched
stages, and live branches. It is a cache, overwritten each run, distinct
from the append-only snapshot history. Read the `hot://<project>` resource
first when resuming.

## Writing back

- `hx_atlas_put` — create or update a page; writing the same path merges and
  preserves the creation clock.
- `hx_atlas_save` — file a synthesis or comparison answer as a proper page.
- `hx_atlas_promote` — move pages up the tier ladder; promotion to canonical
  or published asks for confirmation.

`ATLAS.md` documents the schema in plain English and is the only
configuration the agents read; edit it to change conventions.
