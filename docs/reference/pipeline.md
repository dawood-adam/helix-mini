# helix_mini.pipeline

Forge pipeline — state management, LLM agents, graph execution, routing, decisions, and snapshots.

---

## `ForgeState`

**Module:** `helix_mini.pipeline.state`

```python
@dataclass
class ForgeState:
    project_name: str = ""
    research_question: str = ""
    input_folder: str = ""
    autonomy: dict[str, str] = field(default_factory=dict)
    source_content: list[dict] = field(default_factory=list)
    candidate_approaches: list[dict] = field(default_factory=list)
    chosen_approach_id: str | None = None
    chosen_approach: dict = field(default_factory=dict)
    project_plan: dict[str, Any] = field(default_factory=dict)
    code_artifacts: list[dict] = field(default_factory=list)
    experiment_results: list[dict] = field(default_factory=list)
    sanity_check_flags: list[str] | None = None
    critiques: list[dict] = field(default_factory=list)
    next_action: str = ""
    verdict: str = ""              # critic_results: ship|iterate|abandon
    build_iterations: int = 0      # completed refine loops
    max_iterations: int = 3        # cap on the critic_results->builder loop
    cost_so_far: float = 0.0
    cost_cap: float = 5.0
    call_cap: int = 0
    current_stage: str = "start"
    completed_stages: list[str] = field(default_factory=list)
    error: str | None = None
```

All data flowing through the pipeline. Each agent reads from and writes to subsets of these fields. The `autonomy` dict maps gate names to `"auto"` or `"always_ask"`. `call_cap` is the fallback guardrail: `0` means the dollar `cost_cap` governs; a positive value (set from `ModelConfig.call_cap()` in the runner) caps LLM-backed nodes per run when the engine doesn't report cost.

---

## `GraphState`

**Module:** `helix_mini.pipeline.state`

```python
class GraphState(TypedDict, total=False):
    ...  # mirrors ForgeState fields
```

LangGraph state schema. Uses `total=False` so nodes can return partial updates.

---

## `to_state`

**Module:** `helix_mini.pipeline.state`

```python
def to_state(d: dict) -> ForgeState
```

Converts a dict (from LangGraph) to a `ForgeState`, ignoring extra keys.

---

## `Agents`

**Module:** `helix_mini.pipeline.agents`

### Constructor

```python
Agents(model_config: ModelConfig, atlas: Atlas, raw_root: Path)
```

**Parameters:**
- `model_config` (`ModelConfig`) — Controls which LLM model is used per stage.
- `atlas` (`Atlas`) — Shared wiki for reading context and writing findings.
- `raw_root` (`Path`) — Directory for raw input file copies.

### Agent Methods

All agent methods accept a `ForgeState` and return a `dict` of state updates.

#### `Agents.scout(state: ForgeState) -> dict`
Ingests files from `state.input_folder` via `ingest_folder()`, reads existing Atlas knowledge, calls the LLM to identify candidate approaches. Returns `source_content`, `candidate_approaches`, and `cost`. Writes source pages to Atlas.

#### `Agents.critic_methods(state: ForgeState) -> dict`
Evaluates candidate approaches for feasibility. Returns `critiques`, `chosen_approach_id`, `chosen_approach`, and `cost`.

#### `Agents.planner(state: ForgeState) -> dict`
Designs a validation plan with steps, success criteria, and validation bands. Returns `project_plan` and `cost`.

#### `Agents.builder(state: ForgeState) -> dict`
Implements the plan — produces code artifacts and experiment results, and
**writes the artifacts to disk** under `projects/<name>/artifacts/` via
`sanitize_code_artifacts()` (path-confined, size-capped, never executed). On a
refine pass (`build_iterations > 0`) the prior artifacts + reviewer feedback +
validator flags are fed back so it revises in place. Returns `code_artifacts`,
`experiment_results`, `artifact_files`, and `cost`.

#### `Agents.validator(state: ForgeState) -> dict`
**Deterministic (no LLM call).** Checks `experiment_results` against `validation_bands` from the plan. Returns `sanity_check_flags` (list of `"HARD: ..."` or `"SOFT: ..."` strings, or `None` if all pass) and `cost` (always `0.0`).

#### `Agents.critic_results(state: ForgeState) -> dict`
Final assessment of results. Returns `critiques`, `verdict` (`"ship"`, `"iterate"`, or `"abandon"`), and `cost`. Writes a project overview page to Atlas.

---

## `run_project`

**Module:** `helix_mini.pipeline.runner`

```python
def run_project(
    folder: Path,
    atlas: Atlas,
    model_config: ModelConfig,
    lightspeed: bool = False,
    research_question: str = "",
    ask_fn=None,
    home: Path | None = None,
    progress_fn=None,
    max_iterations: int = 3,
) -> ForgeState
```

**Parameters:**
- `folder` (`Path`) — Input directory.
- `atlas` (`Atlas`) — Shared wiki instance.
- `model_config` (`ModelConfig`) — Model selection.
- `lightspeed` (`bool`) — If `True`, all gates auto-proceed.
- `research_question` (`str`) — Guides the scout agent.
- `ask_fn` — Callback for interactive gates. Currently unused by CLI (always `None`).
- `home` (`Path | None`) — Override for `HELIX_HOME`.
- `progress_fn` — Called at each stage with `(stage, project_name, cost)`.
- `max_iterations` (`int`) — Cap on the `builder`↔`critic_results` refine loop. Sizes the LangGraph `recursion_limit` (`30 + max_iterations * 8`).

**Returns:** `ForgeState` with final pipeline results.

**Behavior:** Creates `Agents`, builds a blank initial state, and delegates to the shared `_execute()` core (compile + invoke from `start_at="scout"`). If `CostCapExceeded` is raised, returns a `ForgeState` with the error message.

---

## `resume_project`

**Module:** `helix_mini.pipeline.runner`

```python
def resume_project(
    project_name: str,
    atlas: Atlas,
    model_config: ModelConfig,
    *,
    snapshot_state: dict,
    start_at: str,
    lightspeed: bool = False,
    ask_fn=None,
    home: Path | None = None,
    progress_fn=None,
    max_iterations: int = 3,
) -> ForgeState
```

Resume a project from a saved snapshot, re-entering the graph at `start_at`
(any of the 12 `GRAPH_NODES`) seeded with the snapshot's full `ForgeState`.

**Parameters:**
- `snapshot_state` (`dict`) — The `state` dict from a loaded snapshot. Used as the initial graph state.
- `start_at` (`str`) — Node to re-enter at. Raises `ValueError` (with the valid node list) if not in `GRAPH_NODES`.
- Other params mirror `run_project`.

**Behavior:** Copies `snapshot_state`, then overrides the run controls
(`project_name`, `autonomy`, `max_iterations`, `call_cap`, `error`,
`current_stage`) so cost/history carry forward (git-like) while autonomy and
caps are refreshed. Delegates to the shared `_execute()` core.

---

## `_execute`

**Module:** `helix_mini.pipeline.runner`

```python
def _execute(
    *, agents, home, ask_fn, progress_fn,
    initial_state: GraphState, start_at: str, max_iterations: int,
) -> ForgeState
```

Shared core for both `run_project` and `resume_project`: builds the graph from
`start_at`, compiles, invokes with `recursion_limit = 30 + max_iterations * 8`,
and converts `CostCapExceeded` into an error `ForgeState`.

---

## `run_parallel`

**Module:** `helix_mini.pipeline.runner`

```python
async def run_parallel(
    folders: list[Path],
    atlas: Atlas,
    model_config: ModelConfig,
    lightspeed: bool = False,
    research_question: str = "",
    home: Path | None = None,
    progress_fn=None,
    max_iterations: int = 3,
) -> list[ForgeState]
```

Runs `run_project()` for each folder concurrently via `asyncio.gather()` in a thread executor (forwarding `max_iterations`). All runs share the same `Atlas` instance (writes are thread-safe).

---

## `build_graph`

**Module:** `helix_mini.pipeline.graph`

```python
def build_graph(
    agents: Agents, home: Path, ask_fn=None, progress_fn=None,
    start_at: str = "scout",
) -> StateGraph
```

Constructs the 12-node LangGraph `StateGraph`. `start_at` sets the entry point
(`graph.set_entry_point(start_at)`): `"scout"` for a fresh run, or any node to
resume. Returns an uncompiled graph — call `.compile()` before invoking.

---

## `GRAPH_NODES`

**Module:** `helix_mini.pipeline.graph`

```python
GRAPH_NODES = (
    "scout", "gate_scope", "critic_methods", "gate_methods",
    "planner", "gate_plan", "builder", "gate_build",
    "validator", "sanity_route", "critic_results", "gate_results",
)
```

The 12 valid pipeline nodes — the allowed `start_at` / resume targets.
`resume_project` validates `start_at` against this tuple.

---

## `CostCapExceeded`

**Module:** `helix_mini.pipeline.graph`

```python
class CostCapExceeded(Exception):
    """Raised when cumulative LLM cost exceeds the configured cap."""
```

`_check_caps()` runs before each LLM-calling node (scout, critic_methods, planner, builder, critic_results) and raises `CostCapExceeded` when either the dollar `cost_cap` is hit **or**, when `call_cap` is active (engine doesn't report cost), the count of completed `LLM_STAGES` reaches `call_cap`.

---

## Router Functions

**Module:** `helix_mini.pipeline.router`

### `gate_decision`

```python
def gate_decision(state: ForgeState, gate_name: str, ask_fn=None) -> str
```

Returns `"proceed"`, `"revise"`, or `"abort"`. Logic:
- If there are blocking critiques:
  - If autonomy is `"auto"`: returns `"revise"`.
  - If `ask_fn` is provided: delegates to `ask_fn(gate_name, blocking_critiques)`.
  - Otherwise: returns `"revise"`.
- If no blocking critiques:
  - If autonomy is `"auto"`: returns `"proceed"`.
  - If `ask_fn` is provided: delegates to `ask_fn(gate_name, all_critiques)`.
  - Otherwise: returns `"proceed"`.

### `sanity_route`

```python
def sanity_route(state: ForgeState) -> str
```

Returns `"pass"` or `"fail"`. Any flag starting with `"HARD:"` causes a fail, routing back to the builder node.

### `iterate_decision`

```python
def iterate_decision(state: ForgeState) -> str
```

Pure rule for the post-`critic_results` gate. Returns `"iterate"` only when
`state.verdict == "iterate"` **and** `state.build_iterations < state.max_iterations`;
otherwise `"stop"` (ship/abandon/unknown verdict, or the loop cap reached).
`gate_results` applies it: `"iterate"` increments `build_iterations` and routes
back to **builder** (which receives the prior artifacts + reviewer feedback for
in-place revision); `"stop"` ends the run. When the `gate_results` autonomy is
not `"auto"` and stdin is a TTY, the gate instead prompts the human
ship/iterate/abandon (overriding the model verdict).

### `make_autonomy`

```python
def make_autonomy(lightspeed: bool) -> dict[str, str]
```

Returns a dict mapping all 5 gates to `"auto"` (if `lightspeed=True`) or `"always_ask"`.

---

## Decision Functions

**Module:** `helix_mini.pipeline.decisions`

### `append_decision`

```python
def append_decision(
    decisions_path: Path,
    stage: str,
    decision: str,
    rationale: str,
    data: dict | None = None,
) -> None
```

Appends a JSON entry `{timestamp, stage, decision, rationale, data}` to the decisions file.

### `render_decisions_md`

```python
def render_decisions_md(decisions_path: Path) -> str
```

Renders the JSON decision log as markdown. Returns `"No decisions recorded yet."` if the file doesn't exist.

### `save_decisions_md`

```python
def save_decisions_md(project_dir: Path, decisions_path: Path) -> None
```

Writes `decisions.md` to `project_dir` by rendering the JSON log.

---

## Snapshot Functions

**Module:** `helix_mini.pipeline.snapshots`

### `mint_snapshot`

```python
def mint_snapshot(state: ForgeState, project_dir: Path) -> Path
```

Saves the full `ForgeState` as `project_dir/.snapshots/snap-N.json` (one per major pipeline node, plus one per builder pass in the refine loop). Returns the snapshot path.

### `load_snapshot`

```python
def load_snapshot(snap_path: Path) -> dict
```

Reads and returns a snapshot as a dict.

### `list_snapshots`

```python
def list_snapshots(project_dir: Path) -> list[Path]
```

Returns all `snap-*.json` files for a project, ordered by snapshot number (so
`snap-10` follows `snap-9`, not lexically before `snap-2`).

### `_snap_num` / `find_snapshot`

```python
def _snap_num(path: Path) -> int            # N from snap-N.json (0 if unparseable)
def find_snapshot(project_dir: Path, num: int) -> Path | None
```

`find_snapshot` returns the path to `snap-<num>.json` if it exists, else
`None`. Used by the CLI/agent to resolve a snapshot by number.

### `snapshot_summary`

```python
def snapshot_summary(snap: dict) -> dict
```

Compact, display-friendly view of one loaded snapshot:
`{stage, timestamp, cost, build_iterations, verdict, approaches, artifacts,
error}`. Backs `snapshots list`, `show`, and the diagram labels.

### `diff_snapshots`

```python
def diff_snapshots(a: dict, b: dict) -> dict[str, tuple]
```

Field-level diff returning `{field: (old, new)}`. Scalars
(`current_stage`, `verdict`, `build_iterations`, `cost_so_far`,
`chosen_approach_id`, `next_action`, `error`) are compared by value; list
fields (`candidate_approaches`, `code_artifacts`, `experiment_results`,
`critiques`, `completed_stages`, `sanity_check_flags`) by length — a readable
git-status-style diff, not a deep dump. `{}` means no tracked differences.

### `snapshot_gitgraph`

```python
def snapshot_gitgraph(snaps: list[dict]) -> str
```

Renders snapshots as a fenced **Mermaid `gitGraph`** — one
`commit id: "snap-N <stage> $<cost> [verdict]"` per snapshot. Refine-loop
passes appear as repeated builder/critic commits. Returns a placeholder
`(no snapshots yet)` commit for an empty history. Standard Mermaid, so it
renders unchanged in GitHub/Obsidian/VS Code/`mermaid.live`.
