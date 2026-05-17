# helix_mini.llm_cli

CLI-backed LLM engine. A `cli/<engine>[:<model>]` model string makes
[`call_llm`](llm.md) spawn an LLM **CLI** in headless mode instead of calling
the litellm HTTP API. `claude` is the built-in engine; more are added by a
`[cli.<name>]` block in `config.toml` — no code change.

---

## `CLIEngine`

```python
@dataclass
class CLIEngine:
    name: str
    bin: str
    prompt_via: str = "arg"            # "stdin" | "arg"
    base_args: list[str] = []          # headless flags
    model_flag: str | None = None      # flag that selects the native model
    system_flag: str | None = None     # flag for the system prompt (else prepended)
    output_format: str = "text"        # "json" | "text"
    json_content_path: str = "result"  # dotted paths into JSON output
    json_cost_path: str | None = None
    json_usage_path: str | None = None
    json_error_path: str | None = None
    reports_cost: bool = False         # controls cost-cap vs call-cap
    strip_env: list[str] = []          # extra env vars to drop (guard vars always dropped)
    uses_claude_code_auth: bool = False # prefer OAuth token over API key
    timeout: int = 600
```

Declarative description of how to drive one CLI. The built-in `CLAUDE` engine:
`claude -p --output-format json --max-turns 1`, prompt via stdin, system via
`--append-system-prompt`, `reports_cost=True`, `uses_claude_code_auth=True`.

---

## `call_cli_llm`

```python
def call_cli_llm(
    *, model: str, system: str, user: str,
    temperature: float = 0.3, max_tokens: int = 4096,
    timeout: int | None = None,
) -> LLMResponse
```

Resolves the engine from `model`, builds the child environment via
`claude_subprocess_env(strip=engine.strip_env, prefer_oauth=engine.uses_claude_code_auth)`,
spawns the binary, and parses output through the engine's JSON paths (or raw
text). Raises `CLIEngineError` on a missing binary, non-zero exit, timeout,
invalid JSON, or an engine-reported error flag. `temperature`/`max_tokens` are
accepted for signature parity and ignored (most CLIs don't expose them).

---

## `get_engine` / `parse_cli_model`

```python
def parse_cli_model(model: str) -> tuple[str, str | None]   # "cli/claude:opus" -> ("claude","opus")
def get_engine(name: str) -> CLIEngine                       # built-ins win over config
```

`get_engine` raises `CLIEngineError` for an unknown engine. Config-defined
engines are loaded once per process (`_load_config_engines` is `lru_cache`d).

---

## `call_cap_for`

```python
def call_cap_for(model: str, stage_models: list[str] | None = None,
                  default: int = DEFAULT_CLI_CALL_CAP) -> int
```

Returns `DEFAULT_CLI_CALL_CAP` (24) if any model is a `cli/` engine that does
not report dollar cost (so the $ cap is meaningless and a per-run call-count
guardrail is armed), else `0`. Surfaced via `ModelConfig.call_cap()` and
enforced by `_check_caps` in `pipeline/graph.py`.

---

## `CLIEngineError`

`RuntimeError` subclass raised when a CLI engine is misconfigured or its
invocation fails.

---

## Adding an engine via `config.toml`

```toml
[cli.mycli]
bin = "mycli"
prompt_via = "arg"
output_format = "text"
# json_content_path / json_cost_path / reports_cost / uses_claude_code_auth ...
```

Built-in engines always win over a same-named config block.
