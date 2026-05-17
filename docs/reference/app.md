# helix_mini.app

Facade that wires Atlas, config, and the pipeline runner together.

---

## `HelixMini`

**Module:** `helix_mini.app`

### Constructor

```python
HelixMini(home: Path | None = None)
```

**Parameters:**
- `home` (`Path | None`, default: `HELIX_HOME`) — Root directory for all persistent data. Defaults to `~/.helix-mini` (or `$HELIX_MINI_HOME`).

**Behavior:** Creates the home directory if absent, initializes an `Atlas` at `home/atlas/`, and calls `ensure_config()` to create `config.toml` if it doesn't exist.

**Example:**
```python
from helix_mini.app import HelixMini

app = HelixMini()                    # uses ~/.helix-mini
app = HelixMini(home=Path("/tmp/h")) # custom home
```

---

### `HelixMini.run`

```python
def run(
    self,
    folders: list[Path],
    lightspeed: bool = False,
    research_question: str = "",
    progress_fn: Callable[[str, str, float], None] | None = None,
    model_config: ModelConfig | None = None,
) -> list[ForgeState]
```

**Parameters:**
- `folders` (`list[Path]`) — Input directories containing source material. Each must exist and be a directory.
- `lightspeed` (`bool`, default: `False`) — If `True`, all gates auto-proceed and the cheaper model is used.
- `research_question` (`str`, default: `""`) — Guides the scout agent's analysis. Falls back to "General analysis" if empty.
- `progress_fn` (`Callable[[str, str, float], None] | None`) — Called at each pipeline stage with `(stage_name, project_name, cost_so_far)`.
- `model_config` (`ModelConfig | None`) — Override model selection. If `None`, resolves via `ModelConfig.default(lightspeed)` (OAuth/subscription wins, then API key), falling back to `ModelConfig.load(lightspeed)`.

**Returns:** `list[ForgeState]` — One result per folder. Each `ForgeState` contains `current_stage`, `completed_stages`, `cost_so_far`, `error`, and all agent outputs.

**Raises:**
- `FileNotFoundError` — If any folder path does not exist or is not a directory.

**Behavior:** For a single folder, calls `run_project()` directly. For multiple folders, runs them in parallel via `asyncio.run(run_parallel())` with a shared Atlas instance.

**Example:**
```python
from pathlib import Path
from helix_mini.app import HelixMini

app = HelixMini()
results = app.run(
    [Path("./my-research")],
    lightspeed=True,
    research_question="How to model cardiac flow?",
)
for r in results:
    print(f"{r.project_name}: {r.current_stage}, cost=${r.cost_so_far:.4f}")
```
