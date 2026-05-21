# Helix

**A collaborative research orchestrator and discovery engine, driven by a Claude Code agent over MCP.**

Helix turns source material — papers, code, data — into a validated
result through a disciplined six-stage pipeline, with a human checkpoint
at every transition. It maintains a typed, frontmatter-driven research
wiki (the **Atlas**) that compounds across projects, and a
content-addressed snapshot DAG (the **Snapshots**) that makes every step
inspectable, diffable, branchable, and resumable.

Helix has **no model of its own and holds no credentials**. The Claude
Code agent *is* the model. Each stage hands its prompt back to the
agent through the tool loop (`hx_step` / `hx_submit`); the server runs
no sampling and stores no API keys.

```
 Scout → Scout Critic → Planner → Builder → Validator → Results Critic
   │           │            │         │          │             │
   └───────────┴────────────┴─── snapshot · gate · transition ─┘
                              (HITL at every gate by default)
```

📖 **Full docs**: [dawood-adam.github.io/helix-mini](https://dawood-adam.github.io/helix-mini/)
(or open `docs/index.html` locally).

---

## Why Helix

Modern research with LLMs has three failure modes:

1. **Drift** — a long chat forgets earlier decisions; rerunning loses
   context; nothing is reproducible.
2. **Opacity** — the model produces an answer; the rationale, the
   sources, and the trade-offs evaporate.
3. **One-off-ness** — knowledge built in one project doesn't show up
   in the next.

Helix addresses these directly:

- **Discipline.** Every stage produces a structured **Decision Card**
  (`summary · key_findings · assumptions · open_questions ·
  directive_for_next · confidence`) that is read aloud at the gate,
  stored in the snapshot, and threaded into the next stage.
- **Provenance.** Every Atlas write carries a closed action vocabulary
  (`ADD · UPDATE · SUPERSEDE · LINK · NOOP`), a one-line `because`,
  the stage / run / snapshot that produced it, and a `spec_refs` link
  back to the spec line it supports / contradicts / extends.
- **Reproducibility.** Every transition is a snapshot. Send-backs are
  snapshots. Branches name alternate paths. `hx_snap_fork` exports the
  full DAG (snapshots + objects + index + refs) as a single
  `forks/<name>.tar.gz` you can hand to a collaborator.
- **Compounding.** The Atlas is workspace-scoped, not project-scoped.
  A second project's Scout reads the first project's findings before
  it starts.

The intent is *agentic engineering* applied to research: Constitution
→ Spec → Clarify → Plan → Tasks (TDD) → Implement → Verify, with the
hypothesis loop (propose → validate → revise) sitting on top.

---

## Architecture at a glance

Three layers, inside out:

| Layer | Module | Responsibility |
|---|---|---|
| Core | `helix/core/` | Pipeline, Atlas, threads, spec, snapshots — dependency-light; no `mcp`, no `fastembed`. |
| Orchestrator | `helix/orchestrator/loop.py` | One runner: run → snapshot → gate → transition. Re-entered per `hx_submit`. |
| Drive surface | `helix/mcp/` | Stdio MCP server. The only module that imports the MCP SDK. |

The Claude Code agent calls the MCP tools. When a stage needs the
model, `hx_step` returns its prompt as the tool output; the agent
answers in its own turn; `hx_submit` feeds the JSON back in. The one
remaining server-to-client callback is **elicitation** at human gates.

Read more: [conceptual architecture](docs/architecture-conceptual.html) ·
[technical architecture](docs/architecture-technical.html).

---

## Requirements

- **Python ≥ 3.11**
- **An MCP client** whose agent drives the tool loop and supports
  *elicitation*. Helix is built for [Claude Code](https://docs.claude.com/en/docs/agents-and-tools/claude-code).

## Install

```bash
pip install -e .                 # core
pip install -e '.[dev]'          # + pytest
pip install -e '.[embed,pdf]'    # optional: semantic recall (fastembed) + PDF ingest
```

## Quick start

Helix uses a **workspace / project** split. Run `helix init` once per
workspace; run `helix new <project>` for each research project inside it.

```bash
# 1. Scaffold the workspace (once per machine / per area of work)
mkdir my-research && cd my-research
helix init
#   → creates helix.toml ([workspace]), atlas/, constitution.md,
#     AGENTS.md (recommended Claude Code skills), .mcp.json, README.md.

# 2. Create your first project
helix new bp-from-rppg
cd bp-from-rppg
#   → creates question.md, helix.toml ([limits]), CLAUDE.md, .mcp.json.

# 3. Open the project folder in Claude Code, then drive in plain language.
```

Inside Claude Code:

```text
you>   start helix
helix> What should we call this project?
you>   bp-from-rppg
helix> One-sentence research question?
you>   Cuffless BP from smartphone rPPG video.
helix> How should it run?  [step-by-step · auto-until-stage · fully autonomous]
you>   step-by-step
helix> Source folder?
you>   ./papers
helix> Scout finished. Decision: 2 candidate approaches; recommends #1.
       Proceed, send back, or stop?
you>   send back to scout — restrict to 2024 papers only
helix> Re-ran Scout with that directive. Scout Critic is done.  …
```

At every gate you may **proceed**, **send back** to any earlier stage
with a directive, or **stop**. A send-back is itself a snapshot. The
plan can be changed mid-run with `hx_run_plan_set`.

## What lives where

```
<workspace>/
├── helix.toml             # workspace marker + Atlas config
├── .mcp.json              # registers the helix MCP server
├── constitution.md        # non-negotiables (lang/framework/testing/"done")
├── AGENTS.md              # recommended Claude Code skills
├── atlas/                 # the cross-project knowledge base
│   ├── inbox/  raw/       # ingest drop-zone + immutable originals
│   ├── sources/  concepts/  entities/  entities/datasets/
│   ├── concepts/glossary/ # workspace-shared Ubiquitous Language
│   └── projects/<id>/     # per-project pages (spec, plan, threads, reports)
└── <project>/             # one per `helix new <project>`
    ├── question.md
    ├── helix.toml         # per-project [limits]
    ├── CLAUDE.md
    ├── .mcp.json
    └── .helix/            # snapshots, runs, pending step (per project)
```

## What you get

| Surface | What |
|---|---|
| **Pipeline** ([forge](docs/forge.html)) | Six stages, agent-driven, with the Validator deterministic in-loop. Each stage emits a Decision Card + self-contained **HTML report** with an embedded annotation overlay you can mark up and send back. |
| **Atlas** ([atlas](docs/atlas.html)) | Markdown-on-disk wiki with typed frontmatter. Closed action vocabulary, mandatory provenance, spec cross-references. Auto-routing recall (BM25 / semantic / graph / community). Hygiene linter (11 checks). |
| **Threads** ([atlas](docs/atlas.html#threads)) | First-class longitudinal artifacts (`hypothesis · data · spec · plan · design · code-org · glossary`) updated by every stage; bi-temporal `thread://<project>/<name>?at=<snap>` reads. |
| **Snapshots** ([snapshots](docs/snapshots.html)) | Content-addressed DAG with branch / freeze / fork. A snapshot calls no model and stays a few kilobytes. |
| **Gates** ([gates](docs/gates.html)) | HITL at every transition by default. The run-scoped `Plan` controls per-gate autonomy. Send-back routes back to any earlier stage with a directive. |
| **MCP** ([mcp](docs/mcp.html)) | One stdio server. Curated tool set (no general code-exec). All filesystem writes pass the sandbox. |
| **Hypothesis loop** ([gates](docs/gates.html#rediscover)) | `autonomy_until: "rediscover"` reruns the pipeline up to 3× with the hypothesis thread carried forward. |
| **TDD task loop** ([forge](docs/forge.html#builder-tdd)) | The Builder advances one task at a time, test-first; the orchestrator rejects batched submits, phase-jumps, and test-disabling patterns. |

## Documentation

Hosted at **[dawood-adam.github.io/helix-mini](https://dawood-adam.github.io/helix-mini/)**.

| Doc | Audience |
|---|---|
| [Quickstart](docs/quickstart.html) | First run in 5 minutes |
| [Usage guide](docs/usage.html) | End-to-end, day-to-day |
| [Conceptual architecture](docs/architecture-conceptual.html) | Non-technical overview |
| [Technical architecture](docs/architecture-technical.html) | Module boundaries, invariants, request flow |
| [Forge — the pipeline](docs/forge.html) | Each stage in detail |
| [Gates & control](docs/gates.html) | HITL, autonomy, send-back, rediscover |
| [Atlas — the wiki](docs/atlas.html) | Schema, write protocol, threads, recall, lint |
| [Snapshots — version control](docs/snapshots.html) | DAG, branch, freeze, fork, resume |
| [MCP surface](docs/mcp.html) | Tools, resources, prompts |

## Project status

- **Test suite**: `pytest -q` → 206 passing, 1 optional (semantic recall).
- **Maturity**: actively developed. The MCP drive surface, six-stage pipeline,
  Atlas (with the Workstream-G write protocol), threads, snapshots, and
  the TDD task loop are all production-shape; the HTML report round-trip and
  discovery (rediscover) loop are recent additions.

## Development

```bash
pip install -e '.[dev]'
pytest -q

# In a git worktree the editable install resolves to the main checkout:
PYTHONPATH="$PWD/src" pytest -q
```

The project follows the invariants in [`CLAUDE.md`](CLAUDE.md):

- `helix.core`, `helix.io`, and `helix.orchestrator.loop` import without
  `mcp` or `fastembed`. SDK contact is confined to `helix/mcp/`.
- All routing goes through `core.transitions.next_stage`.
- A snapshot never calls a model.
- LLM-controlled strings reaching the filesystem pass `sandbox.sanitize_*`;
  project / run / bundle names go through `validate_project_name` at every
  filesystem path root.

## Contributing

Issues and PRs welcome. A few conventions:

- Keep `helix.core` dependency-light; new core modules
  (`core/spec.py`, `core/threads.py`, `core/hypothesis.py`,
  `core/constitution.py`, `core/reports.py`) all obey this.
- Add a test in `tests/` for every new behavior — the in-process
  `app.run` harness (with `conftest.fake_llm`) covers the pipeline
  model-free; the in-memory MCP client harness covers tool wiring.
- Send-back paths go through `record_feedback` + `next_stage("goto", …)`.
  Never add a parallel router.
- Workspace-scoped, model-controlled paths go through
  `validate_project_name`. The `core/spec.py` and `core/threads.py`
  validators are the recent additions of this pattern.

## License

[MIT](LICENSE).
