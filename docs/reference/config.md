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

**Returns:** `ModelConfig` loaded from `~/.helix-mini/config.toml` (via `load_config_toml()`), falling back to `DEFAULT_CONFIG` if the file is missing.

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

### `ModelConfig.cli`

```python
@classmethod
def cli(cls, engine: str = "claude", native_model: str | None = None) -> ModelConfig
```

**Parameters:**
- `engine` (`str`) — CLI engine name (built-in: `"claude"`; more via `[cli.<name>]` in `config.toml`).
- `native_model` (`str | None`) — Engine-native model passed through (e.g. `"haiku"`, `"opus"`).

**Returns:** `ModelConfig` whose model is `cli/<engine>[:<native_model>]`. Every stage is run by spawning the engine's binary instead of the litellm HTTP API — no API key required. See [llm_cli](llm_cli.md).

---

### `ModelConfig.default`

```python
@classmethod
def default(cls, lightspeed: bool = False) -> ModelConfig | None
```

Resolves the engine when no mode flag is given, with a strict precedence
(**OAuth wins**):

1. `CLAUDE_CODE_OAUTH_TOKEN` set → `cli/claude` (subscription), even if an API
   key is also present — `:haiku` when `lightspeed`
2. else an API key set → `ModelConfig.load(lightspeed)`
3. else → `None` (caller decides: error, or `cli/claude` fallback from the agent)

Used by `helix-mini run` (no flag), `HelixMini.run()`, and the agent's
`run_pipeline` tool.

---

### `ModelConfig.call_cap`

```python
def call_cap(self) -> int
```

**Returns:** `DEFAULT_CLI_CALL_CAP` (24) if any model in use is a `cli/` engine
that does not report dollar cost (the $ cap is meaningless then, so a per-run
call-count guardrail is armed); otherwise `0` (the cost cap governs). Enforced
by `_check_caps` in `pipeline/graph.py`.

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

### `CLOUD_STAGES` / `LOCAL_RECOMMENDED_STAGES` / `LLM_STAGES`

**Module:** `helix_mini.config.models`

```python
CLOUD_STAGES = {"critic_methods", "planner", "critic_results"}
LOCAL_RECOMMENDED_STAGES = {"scout", "builder", "validator"}
# Stages that actually invoke an LLM (validator is deterministic); used to
# enforce the call-count guardrail when an engine doesn't report cost.
LLM_STAGES = {"scout", "critic_methods", "planner", "builder", "critic_results"}
```

### `CLAUDE_CODE_OAUTH_ENV` / `CLAUDE_NESTED_GUARD_VARS`

**Module:** `helix_mini.config.providers`

```python
CLAUDE_CODE_OAUTH_ENV = "CLAUDE_CODE_OAUTH_TOKEN"
CLAUDE_NESTED_GUARD_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")
```

The OAuth token (minted by `claude setup-token`) authenticates the bundled
`claude` CLI against your Claude **subscription** rate limits. It is **not** an
API key — litellm/the HTTP API cannot use it. The guard vars are stripped from
any spawned `claude` so it runs even when helix-mini is launched from Claude
Code.

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

Returns `True` if any provider's API key environment variable is set. (An
OAuth token is *not* an API key — `has_api_key()` ignores it.)

### `claude_code_oauth_token`

```python
def claude_code_oauth_token() -> str | None
```

Returns the trimmed `CLAUDE_CODE_OAUTH_TOKEN` from the environment, or `None`
if unset/blank.

### `has_claude_code_oauth`

```python
def has_claude_code_oauth() -> bool
```

`True` when subscription auth (`claude setup-token`) is configured.

### `claude_subprocess_env`

```python
def claude_subprocess_env(
    strip: tuple[str, ...] = (), *, prefer_oauth: bool = False
) -> dict[str, str]
```

Builds the environment for spawning the `claude` binary: a copy of
`os.environ` minus `CLAUDE_NESTED_GUARD_VARS` (plus any extra `strip`). When
`prefer_oauth` and a token is set, drops `ANTHROPIC_API_KEY` and injects the
token so subscription auth wins. Scoped to the child only. The single home for
this rule — used by `llm_cli` and (via `agent_sdk.claude_code_auth`) the Agent
SDK path.

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

### `load_config_toml`

```python
def load_config_toml(home: Path | None = None) -> dict
```

**Parameters:**
- `home` (`Path | None`) — Directory containing `config.toml`. Defaults to `HELIX_HOME`.

**Returns:** Parsed `config.toml` as a dict, or `{}` if absent or unreadable. The
single shared TOML reader — consumed by `ModelConfig.load` and the
`[cli.<name>]` engine loader in `llm_cli`.
