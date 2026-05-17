# Helix Mini — Plan

A minimal implementation of Forge + Atlas that achieves the core goal: **run a research pipeline over input folders, capture every decision, and build a persistent LLM wiki that compounds across projects.**

---

## Core Concept

You point helix-mini at one or more folders of source material. For each folder, Scout ingests the files, the Forge pipeline runs (identifying approaches, critiquing, planning, building, validating), and every agent reads from and writes to a shared **Atlas** — an LLM-maintained wiki of markdown pages that accumulates knowledge across all projects.

```
helix-mini run ./papers/cardiac ./papers/genomics --lightspeed
```

Two folders = two parallel Forge pipelines, both reading from and writing to the same Atlas.

---

## Atlas — The LLM Wiki (minimal, scalable)

Atlas is the LLM Wiki pattern reduced to its simplest viable form:

### Three layers

```
~/.helix-mini/
├── atlas/                    # THE WIKI (LLM-written, human-readable)
│   ├── index.md              # Catalog of all pages + one-line summaries
│   ├── log.md                # Append-only: what happened and when
│   ├── sources/              # One summary page per ingested source file
│   ├── concepts/             # Cross-cutting ideas, methods, themes
│   ├── entities/             # People, datasets, tools, orgs
│   └── projects/             # One page per Forge project run
├── raw/                      # IMMUTABLE SOURCES (copies/symlinks of input files)
└── config.toml               # Model config + API key env var name
```

### How it works

- **`index.md`** — The LLM reads this first to find relevant pages. A flat list: `- [Page Title](path) — one-line summary`. Updated on every write. At moderate scale (~hundreds of pages), this is sufficient for navigation without embeddings or vector search.

- **`log.md`** — Append-only chronological record. Each entry: `## [2026-05-17] ingest | filename.pdf` or `## [2026-05-17] scout | project-name`. Gives the LLM temporal context.

- **`sources/`** — One markdown page per raw source file. Created during Scout's ingest. Contains: title, key claims, methods used, relevance to research question, cross-references to concept/entity pages.

- **`concepts/`** — Emerge organically. When Scout or any agent identifies a concept mentioned across multiple sources, it gets its own page. Updated by subsequent agents as understanding deepens.

- **`entities/`** — Datasets, tools, authors, organizations that appear across sources. Simple factual pages with back-references.

- **`projects/`** — One page per Forge run. Updated at each gate with the decision rationale, chosen approach, plan, results.

### Atlas operations (what agents do)

Each Forge agent gets two Atlas primitives:

```python
class Atlas:
    def read(self, query: str) -> list[Page]:
        """Read index.md, find relevant pages, return their content."""

    def write(self, writes: list[PageWrite]) -> None:
        """Create/update pages, update index.md, append to log.md."""
```

That's the entire API. `read` is "scan index, read matching pages." `write` is "upsert pages + maintain index + append log." No embedding DB, no vector search, no special infrastructure. Just markdown files and an index.

### Scalability path (built in, not built yet)

The design scales without architectural changes:
- **Small** (~50 pages): index.md scanning is instant
- **Medium** (~500 pages): add a simple grep/ripgrep search over wiki files
- **Large** (~5000+ pages): plug in a search tool (qmd, embeddings, whatever) behind the same `Atlas.read()` interface

The interface stays the same; only the retrieval implementation changes.

---

## Input: Folders as Projects

### How Scout ingests a folder

```
helix-mini run ./my-research-folder --lightspeed
```

1. Recursively read all files in the folder (`.md`, `.txt`, `.pdf`, `.py`, `.json`, etc.)
2. Copy/symlink originals into `raw/` (immutable archive)
3. For each file, create a source summary page in `atlas/sources/`
4. Cross-reference: update concept/entity pages that emerge from the sources
5. Update `index.md` and `log.md`
6. Use the synthesized knowledge to identify candidate approaches

Scout's LLM call gets the file contents (or summaries of large files) as context, plus any existing relevant Atlas pages. It outputs: candidate approaches + Atlas writes (source pages, new concepts).

### Multiple folders = parallel projects

```
helix-mini run ./folder-a ./folder-b ./folder-c --lightspeed
```

Each folder becomes an independent Forge pipeline. They run in parallel (`asyncio.gather` or `concurrent.futures`). All pipelines share the same Atlas — so if folder-b's Scout finds a concept that folder-a already wrote about, it reads and builds on that page rather than starting from scratch.

Atlas writes are serialized with a simple file lock (single-process `threading.Lock`) to prevent clobbering. Reads are lock-free.

---

## Architecture

```
helix-mini/
├── pyproject.toml
├── Dockerfile                          # Docker sandbox image
├── src/
│   └── helix_mini/
│       ├── __init__.py
│       │
│       ├── config/                     # Configuration management
│       │   ├── __init__.py             # Re-exports all config symbols
│       │   ├── settings.py             # HELIX_HOME, .env loading, ensure_config
│       │   ├── models.py              # ModelConfig, QWEN_SIZES, stage mappings
│       │   └── providers.py           # Provider registry, API key validation
│       │
│       ├── atlas/                      # LLM wiki system
│       │   ├── __init__.py             # Re-exports Atlas, Page, PageWrite, ingest_folder
│       │   ├── store.py               # Atlas class (read/write/search/index)
│       │   └── ingest.py             # File ingestion (folder reading, PDF support)
│       │
│       ├── pipeline/                   # Forge pipeline
│       │   ├── __init__.py             # Re-exports ForgeState, run_project, run_parallel
│       │   ├── state.py              # ForgeState + GraphState + converters
│       │   ├── agents.py             # 6 LLM agent bodies + system prompts
│       │   ├── router.py             # Gate decisions + sanity routing (pure rules)
│       │   ├── graph.py              # LangGraph 12-node pipeline definition
│       │   ├── runner.py             # run_project + run_parallel execution
│       │   ├── decisions.py          # Decision log (JSON + markdown render)
│       │   └── snapshots.py          # Lightweight state snapshots
│       │
│       ├── sandbox.py                  # LLM output validation (paths, content, batch limits)
│       ├── llm.py                      # Thin LLM call wrapper (litellm)
│       ├── docker.py                   # Docker sandbox execution
│       ├── app.py                      # Facade: Atlas + config + runner
│       └── cli.py                      # CLI commands (run, setup, status, log, init)
│
└── tests/
    ├── conftest.py                     # Shared fixtures
    ├── test_atlas.py                   # Atlas read/write/ingest tests
    ├── test_lightspeed.py              # Agent + full pipeline tests with fake LLM
    ├── test_sandbox.py                 # Output validation tests
    ├── test_setup.py                   # Config, model, provider tests
    └── test_workflow.py                # Router, decisions, snapshots, state tests
```

**3 packages + 5 top-level modules, ~1800 lines, 66 tests.**

### Module organization principles

- **`config/`** — "How is Helix Mini configured?" Settings, model selection, provider registry. All config in one place.
- **`atlas/`** — "How does the wiki work?" Store (read/write/index) separated from ingestion (file reading/copying).
- **`pipeline/`** — "How does the research pipeline run?" State, agents, routing, graph, execution, logging — all pipeline concerns grouped together.
- **Top-level utilities** — Small, focused modules that serve the whole codebase: `sandbox.py` (security), `llm.py` (LLM calls), `docker.py` (containerization), `app.py` (facade), `cli.py` (entry point).

---

## The Modes

### 1. Normal Mode (default)
- Gates set to `always_ask` — CLI pauses at each gate for human review
- Uses whatever model you configured
- You review Scout's ingest, pick an approach, approve the plan, etc.

### 2. Lightspeed Mode (`--lightspeed`)
- All gates set to `auto` — only pauses on BLOCKING critiques
- Uses the cheapest/fastest model (e.g. haiku, gpt-4o-mini)
- Runs the entire Forge pipeline start-to-finish with no human interaction
- Still writes to Atlas, still logs every decision, still mints snapshots
- ~7 LLM calls per project, ~$0.01-0.05, ~30-60s wall clock

### 3. Local Mode (`--local`)
- All stages run locally using Qwen models via Ollama
- No API key needed
- Choose model size: `--model-size small|medium|large` (1.7B / 8B / 32B)

### 4. Local-Recommended Mode (`--local-recommended`)
- Simple stages (scout, builder, validator) use local Qwen
- Critical reasoning stages (critic_methods, planner, critic_results) use cloud API
- Best balance of cost and quality

### 5. Docker Sandbox Mode (`--sandbox`)
- Runs the entire pipeline inside a Docker container
- Non-root user, read-only source mounts, resource limits
- Security: `--security-opt no-new-privileges`, 2GB memory, 2 CPUs

---

## Detailed Design

### `config/` — Configuration Management

```python
# config/settings.py
HELIX_HOME = Path("~/.helix-mini")     # Base directory
DEFAULT_CONFIG = {...}                   # Default model mappings
def ensure_config() -> Path: ...         # Create config.toml if missing

# config/models.py
@dataclass
class ModelConfig:
    model: str
    stage_overrides: dict[str, str]      # Per-stage model selection
    def model_for_stage(stage) -> str    # Resolve model for a pipeline stage
    @classmethod def load(lightspeed)    # Load from config.toml
    @classmethod def local(size)         # All-local Qwen config
    @classmethod def local_recommended() # Hybrid local/cloud config

# config/providers.py
PROVIDERS = {"anthropic": ..., "openai": ...}
def has_api_key() -> bool
def validate_api_key(provider, key) -> bool
def validate_ollama(model) -> bool
```

### `atlas/` — The LLM Wiki

```python
# atlas/store.py — Wiki storage
@dataclass
class Page:
    path: str; title: str; content: str

@dataclass
class PageWrite:
    path: str; title: str; content: str; summary: str

class Atlas:
    def read(query, limit=20) -> list[Page]    # Keyword search via index.md
    def read_all_summaries() -> str              # Full index for LLM context
    def write(writes, log_entry) -> None         # Atomic batch write

# atlas/ingest.py — File ingestion (separated from wiki ops)
def ingest_folder(folder, raw_root) -> list[Page]   # Read + copy files
def _read_pdf(path) -> str | None                     # Optional PDF support
```

### `pipeline/` — Forge Pipeline

```python
# pipeline/state.py
@dataclass
class ForgeState: ...       # All pipeline data
class GraphState(TypedDict): ...  # LangGraph schema
def to_state(dict) -> ForgeState  # Dict → ForgeState converter

# pipeline/agents.py — Pattern: Atlas.read → LLM call → Atlas.write
class Agents:
    def _call_and_write(stage, system, user, project) -> (dict, float)
    def scout(state) -> dict
    def critic_methods(state) -> dict
    def planner(state) -> dict
    def builder(state) -> dict
    def validator(state) -> dict      # Deterministic, no LLM
    def critic_results(state) -> dict

# pipeline/router.py — Pure rules
def gate_decision(state, gate_name, ask_fn) -> str   # proceed/revise/abort
def sanity_route(state) -> str                         # pass/fail
def make_autonomy(lightspeed) -> dict                  # Gate settings

# pipeline/graph.py — LangGraph definition
def build_graph(agents, home, ask_fn, progress_fn) -> StateGraph
# 12 nodes: scout → gate_scope → critic_methods → gate_methods →
#   planner → gate_plan → builder → gate_build → validator →
#   sanity_route → critic_results → gate_results

# pipeline/runner.py — Execution
def run_project(folder, atlas, model_config, ...) -> ForgeState
async def run_parallel(folders, atlas, model_config, ...) -> list[ForgeState]

# pipeline/decisions.py — Decision log
def append_decision(path, stage, decision, rationale)
def render_decisions_md(path) -> str

# pipeline/snapshots.py — State snapshots
def mint_snapshot(state, project_dir) -> Path
```

### `sandbox.py` — LLM Output Validation

```python
def validate_path(path, atlas_root) -> Path    # No traversal, allowed subdirs only
def validate_title(title) -> str                # Strip control chars, enforce length
def validate_content(content) -> str            # Cap at 500KB
def sanitize_atlas_writes(raw, root) -> list[PageWrite]  # Full validation pipeline
def validate_ingest_source(path, folder) -> bool          # Reject external symlinks
```

### `llm.py` — Thin Wrapper

```python
def call_llm(model, system, user, ...) -> LLMResponse     # Single call with retry
def call_llm_json(model, system, user, ...) -> (dict, float)  # JSON-parsed response
```

Uses `litellm` for provider routing. Timeout: 120s, retries: 3.

### `docker.py` — Docker Sandbox

```python
def run_sandboxed(folders, lightspeed, question) -> None
# Non-root user, read-only mounts, no-new-privileges, 2GB/2CPU limits
```

### `cli.py` — Commands

```
helix-mini run <folder> [<folder>...] [--lightspeed] [--local] [--sandbox]
helix-mini setup                    # Interactive provider + API key wizard
helix-mini init <name>              # Create project folder with question.md
helix-mini status                   # Show Atlas stats + recent projects
helix-mini log <project>            # Print decision log
helix-mini atlas search <query>     # Search the wiki
```

---

## What Happens End-to-End

```bash
$ helix-mini run ./cardiac-papers --lightspeed
```

1. **Scout** reads all files in `./cardiac-papers/` (PDFs, markdown, whatever)
2. Scout creates `atlas/sources/paper-1.md`, `atlas/sources/paper-2.md`, ...
3. Scout identifies concepts → creates `atlas/concepts/cardiac-modeling.md`, etc.
4. Scout proposes 3 candidate approaches
5. **gate_scope** auto-approves (lightspeed)
6. **Critic-Methods** reads relevant Atlas pages, evaluates approaches
7. **gate_methods** auto-picks best approach
8. **Planner** reads Atlas, designs validation plan, writes `atlas/projects/cardiac/plan.md`
9. **gate_plan** auto-approves
10. **Builder** writes code scaffold, updates project page
11. **gate_build** auto-approves
12. **Validator** checks results against plan
13. **Critic-Results** evaluates, updates Atlas with findings
14. **gate_results** ships
15. Done. Atlas is richer. Decision log is complete.

### Output structure

```
~/.helix-mini/
├── atlas/
│   ├── index.md                          # Updated with all new pages
│   ├── log.md                            # 15+ entries from this run
│   ├── sources/
│   │   ├── chen-2024-cardiac-sim.md      # Summary of each input file
│   │   ├── wang-2025-fluid-dynamics.md
│   │   └── ...
│   ├── concepts/
│   │   ├── cardiac-modeling.md           # Emerged from multiple sources
│   │   ├── fluid-structure-interaction.md
│   │   └── ...
│   ├── entities/
│   │   ├── openfoam.md                   # Tool mentioned across papers
│   │   └── ...
│   └── projects/
│       └── cardiac-papers/
│           ├── overview.md               # Project page (updated each stage)
│           ├── plan.md                   # Validation plan
│           ├── .decisions.json           # Structured decision log
│           ├── decisions.md              # Rendered narrative
│           └── .snapshots/
│               └── snap-1.json ... snap-5.json
├── raw/
│   ├── cardiac-papers/                   # Immutable copies of input files
│   │   ├── chen-2024.pdf
│   │   └── ...
└── config.toml
```

---

## Parallel Example

```bash
$ helix-mini run ./cardiac ./genomics ./neuro --lightspeed
```

Three Forge pipelines run concurrently. They share the Atlas:
- If genomics Scout finds a concept that cardiac already wrote, it reads and extends that page
- Cross-project links emerge naturally ("cardiac-modeling" page gets a "see also: genomics" reference)
- Atlas grows richer from the overlap

Writes are serialized (threading.Lock). Reads are concurrent. Simple and correct.

---

## Dependencies

```toml
[project]
name = "helix-mini"
requires-python = ">=3.11"
dependencies = [
    "langgraph>=0.2",
    "litellm>=1.0",
    "click>=8.0",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
pdf = ["pymupdf>=1.24"]   # for PDF ingestion
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]
```

Four core deps. PDF support optional.

---

## Security

### LLM Output Sandbox (`sandbox.py`)
- All LLM-generated Atlas writes pass through `sanitize_atlas_writes()`
- Path validation: no absolute paths, no `..`, must start with allowed subdir
- Content caps: 500KB per page, 200-char titles, 50 writes per batch
- Symlink protection during file ingestion

### Docker Sandbox (`docker.py` + `Dockerfile`)
- Non-root user inside container
- Source folders mounted read-only
- `--security-opt no-new-privileges`
- Resource limits: 2GB memory, 2 CPUs

### Atlas Path Traversal Defense
- `Atlas._safe_resolve()` validates all paths stay within atlas root
- Defense-in-depth: sandbox validates before Atlas, Atlas validates again

---

## Design Principles

1. **Atlas is just markdown files + an index** — no DB, no embeddings, no infrastructure. Scales later by swapping the read implementation.
2. **Every agent reads from and writes to Atlas** — the wiki compounds with every stage of every project.
3. **Folders are the input interface** — drop files in a folder, point helix-mini at it.
4. **Parallel projects share one Atlas** — cross-project knowledge emerges naturally.
5. **One LLM call per stage** — fast, auditable, cheap.
6. **Lightspeed = same pipeline, cheapest model, auto-gates** — not a different code path.
7. **No web access except LLM API** — all knowledge comes from your input files.
8. **No fake success** — if the LLM fails, the pipeline pauses.
9. **Modular packages** — config, atlas, pipeline are self-contained subsystems. Each can be understood independently.
10. **Local-first option** — run entirely offline with Ollama + Qwen, or mix local and cloud models.
