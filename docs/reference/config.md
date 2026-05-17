# helix_mini.config

Model selection, provider registry, environment loading, and settings management.

---

## `ModelConfig`

**Module:** `helix_mini.config.models`

```python
@dataclass
class ModelConfig:
    model: str
    stage_overrides: dict[str, str] = field(default_factory=dict)
```

Central model configuration. The `model` field is the default model for all pipeline stages. `stage_overrides` maps specific stage names to different models.

---

### `ModelConfig.model_for_stage`

```python
def model_for_stage(self, stage: str) -> str
```

**Parameters:**
- `stage` (`str`) — Pipeline stage name (e.g., `"scout"`, `"planner"`).

**Returns:** The model string from `stage_overrides[stage]` if present, otherwise `self.model`.

---

### `ModelConfig.load`

```python
@classmethod
def load(cls, lightspeed: bool = False) -> ModelConfig
```

**Parameters:**
- `lightspeed` (`bool`, default: `False`) — If `True`, uses the `[lightspeed]` section from `config.toml` (Claude Haiku). Otherwise uses `[default]` (Claude Sonnet).

**Returns:** `ModelConfig` loaded from `~/.helix-mini/config.toml`, falling back to `DEFAULT_CONFIG` if the file is missing.

---

### `ModelConfig.local`

```python
@classmethod
def local(cls, size: str = "medium") -> ModelConfig
```

**Parameters:**
- `size` (`str`) — One of `"small"`, `"medium"`, `"large"`. Maps to Qwen models via `QWEN_SIZES`.

**Returns:** `ModelConfig` using a local Ollama model for all stages.

---

### `ModelConfig.local_recommended`

```python
@classmethod
def local_recommended(
    cls,
    size: str = "medium",
    lightspeed: bool = False,
) -> ModelConfig
```

**Parameters:**
- `size` (`str`) — Qwen model size for local stages.
- `lightspeed` (`bool`) — If `True`, uses the cheaper cloud model (Haiku) for critical stages.

**Returns:** `ModelConfig` with local Qwen for simple stages (`LOCAL_RECOMMENDED_STAGES`: scout, builder, validator) and a cloud model for critical stages (`CLOUD_STAGES`: critic_methods, planner, critic_results).

**Example:**
```python
from helix_mini.config import ModelConfig

mc = ModelConfig.local_recommended("small", lightspeed=True)
print(mc.model_for_stage("scout"))           # ollama/qwen3:1.7b
print(mc.model_for_stage("planner"))         # anthropic/claude-haiku-4-5-20251001
```

---

## Constants

### `PROVIDERS`

**Module:** `helix_mini.config.providers`

```python
PROVIDERS = {
    "anthropic": {
        "env_var": "ANTHROPIC_API_KEY",
        "default_model": "anthropic/claude-sonnet-4-20250514",
        "lightspeed_model": "anthropic/claude-haiku-4-5-20251001",
    },
    "openai": {
        "env_var": "OPENAI_API_KEY",
        "default_model": "openai/gpt-4o",
        "lightspeed_model": "openai/gpt-4o-mini",
    },
}
```

### `QWEN_SIZES`

**Module:** `helix_mini.config.models`

```python
QWEN_SIZES = {
    "small": "ollama/qwen3:1.7b",
    "medium": "ollama/qwen3:8b",
    "large": "ollama/qwen3:32b",
}
```

### `CLOUD_STAGES` / `LOCAL_RECOMMENDED_STAGES`

**Module:** `helix_mini.config.models`

```python
CLOUD_STAGES = {"critic_methods", "planner", "critic_results"}
LOCAL_RECOMMENDED_STAGES = {"scout", "builder", "validator"}
```

### `HELIX_HOME`

**Module:** `helix_mini.config.settings`

```python
HELIX_HOME = Path(os.environ.get("HELIX_MINI_HOME", Path.home() / ".helix-mini"))
```

Default root directory for all persistent data. Override with `HELIX_MINI_HOME` environment variable.

### `DEFAULT_CONFIG`

**Module:** `helix_mini.config.settings`

```python
DEFAULT_CONFIG = {
    "default": {"model": "anthropic/claude-sonnet-4-20250514"},
    "lightspeed": {"model": "anthropic/claude-haiku-4-5-20251001"},
}
```

---

## Functions

### `has_api_key`

```python
def has_api_key() -> bool
```

Returns `True` if any provider's API key environment variable is set.

### `validate_api_key`

```python
def validate_api_key(provider: str, api_key: str) -> bool
```

**Parameters:**
- `provider` (`str`) — Provider name (`"anthropic"` or `"openai"`).
- `api_key` (`str`) — The API key to validate.

**Returns:** `True` if a minimal LLM call succeeds, `False` on any exception.

### `validate_ollama`

```python
def validate_ollama(model: str = "") -> bool
```

**Parameters:**
- `model` (`str`) — Ollama model string. Defaults to `QWEN_SIZES["medium"]`.

**Returns:** `True` if Ollama responds to a minimal completion call.

### `ensure_config`

```python
def ensure_config(home: Path | None = None) -> Path
```

**Parameters:**
- `home` (`Path | None`) — Directory to create config in. Defaults to `HELIX_HOME`.

**Returns:** Path to `config.toml`. Creates the file with default model settings if it doesn't exist.
