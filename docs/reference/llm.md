# helix_mini.llm

Thin wrapper around [litellm](https://github.com/BerriAI/litellm) for LLM calls with timeout, retry, and JSON parsing. This is the single chokepoint every pipeline LLM call funnels through — which is why alternate Claude backends (the [llm_cli](llm_cli.md) engine, the [agent_sdk](agent_sdk.md) driver) plug in without a forked code path.

---

## `call_llm`

```python
def call_llm(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    timeout: int = 120,
    max_retries: int = 3,
) -> LLMResponse
```

**Parameters:**
- `model` (`str`) — litellm model string (e.g., `"anthropic/claude-sonnet-4-20250514"`, `"ollama/qwen3:8b"`).
- `system` (`str`) — System prompt.
- `user` (`str`) — User message.
- `temperature` (`float`, default: `0.3`) — Sampling temperature.
- `max_tokens` (`int`, default: `4096`) — Maximum response tokens.
- `timeout` (`int`, default: `120`) — Request timeout in seconds.
- `max_retries` (`int`, default: `3`) — Number of retries on failure.

**Returns:** `LLMResponse` with `content`, `usage`, and `cost`.

**Behavior:** A `cli/`-prefixed `model` short-circuits to `llm_cli.call_cli_llm()` (the CLI engine) before litellm is touched. Otherwise calls `litellm.completion()`; cost is computed via `litellm.completion_cost()`.

---

## `call_llm_json`

```python
def call_llm_json(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> tuple[dict[str, Any], float]
```

**Parameters:** Same as `call_llm` (minus `timeout`/`max_retries` which use defaults).

**Returns:** `(parsed_dict, cost)` — The LLM response parsed as JSON, plus the cost.

**Behavior:**
1. Appends a JSON instruction to the system prompt.
2. Calls `call_llm()`.
3. Strips markdown code fences (` ```json ... ``` `) if present.
4. Parses the response as JSON.
5. On `JSONDecodeError`, returns `{"raw": text}` as a fallback.

**Example:**
```python
from helix_mini.llm import call_llm_json

data, cost = call_llm_json(
    model="anthropic/claude-sonnet-4-20250514",
    system="You are a research analyst. Respond with JSON.",
    user="Summarize this paper...",
)
print(data.keys(), f"cost=${cost:.4f}")
```

---

## `LLMResponse`

```python
@dataclass
class LLMResponse:
    content: str                   # raw text response
    usage: dict[str, int]          # {"prompt_tokens": N, "completion_tokens": N}
    cost: float                    # USD cost from litellm
```
