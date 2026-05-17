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
Implements the plan — produces code artifacts and experiment results. Returns `code_artifacts`, `experiment_results`, and `cost`.

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

**Returns:** `ForgeState` with final pipeline results.

**Behavior:** Creates `Agents`, builds the 12-node LangGraph, compiles it, and invokes with an initial state. If `CostCapExceeded` is raised, returns a `ForgeState` with the error message.

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
) -> list[ForgeState]
```

Runs `run_project()` for each folder concurrently via `asyncio.gather()` in a thread executor. All runs share the same `Atlas` instance (writes are thread-safe).

---

## `build_graph`

**Module:** `helix_mini.pipeline.graph`

```python
def build_graph(agents: Agents, home: Path, ask_fn=None, progress_fn=None) -> StateGraph
```

Constructs the 12-node LangGraph `StateGraph`. Returns an uncompiled graph — call `.compile()` before invoking.

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

Saves the full `ForgeState` as `project_dir/.snapshots/snap-N.json`. Returns the snapshot path.

### `load_snapshot`

```python
def load_snapshot(snap_path: Path) -> dict
```

Reads and returns a snapshot as a dict.

### `list_snapshots`

```python
def list_snapshots(project_dir: Path) -> list[Path]
```

Returns sorted list of all `snap-*.json` files for a project.
