# helix_mini.agent_sdk

Drives helix-mini through a Claude agent built on the **Claude Agent SDK**.
helix-mini operations are exposed as in-process MCP tools so a Claude agent can
search the Atlas, inspect status/decision logs, and (gated) launch pipeline
runs. The pure `*_text` helpers carry no SDK dependency and are unit-tested
directly; only the agent plumbing imports `claude-agent-sdk` lazily, so the
package stays an optional extra (`pip install 'helix-mini[agent]'`).

---

## Pure helpers (SDK-free)

```python
def atlas_search_text(query: str, home: Path | None = None) -> str
def atlas_status_text(home: Path | None = None) -> str
def decision_log_text(project: str, home: Path | None = None) -> str
def run_pipeline_text(folder: str, question: str = "",
                      lightspeed: bool = True, home: Path | None = None) -> str
```

Each backs one MCP tool. `run_pipeline_text` resolves the engine via
`ModelConfig.default()` (OAuth wins), falling back to `cli/claude` so an
agent-launched run never needs a provider key.

---

## `run_permission_decision`

```python
def run_permission_decision(
    tool_name: str, *, interactive: bool, approver=None
) -> tuple[bool, str]
```

Pure gate for the costly run tool. Read tools never reach it (they are
auto-approved via `allowed_tools`). For `run_pipeline`: consult `approver` if
given; otherwise **deny** — and deny outright in a non-interactive session.

---

## `claude_code_auth`

```python
def claude_code_auth() -> tuple[dict[str, str], list[str]]
```

Returns `(env_to_pass, env_keys_to_drop)` for the SDK subprocess. With a token
set: `({"CLAUDE_CODE_OAUTH_TOKEN": <token>}, ["ANTHROPIC_API_KEY"])` so
subscription auth wins; otherwise `({}, [])`. Mirrors the precedence in
`config.claude_subprocess_env`.

---

## `build_helix_server` / `run_agent`

```python
def build_helix_server(home: Path | None = None)          # create_sdk_mcp_server
def run_agent(prompt: str | None = None, home: Path | None = None,
              max_turns: int = 30) -> None                  # sync entry point
```

`build_helix_server` registers the four `@tool` wrappers and returns an
in-process SDK MCP server (`mcp__helix__*`). `run_agent` builds
`ClaudeAgentOptions` (read tools in `allowed_tools`; `run_pipeline` omitted so
it falls through to a `can_use_tool` confirmation), then runs a
`ClaudeSDKClient` loop — one-shot if `prompt` is given, interactive otherwise.
Raises `RuntimeError` with an install hint if the SDK is absent.

---

## `RUN_TOOL`

```python
RUN_TOOL = "run_pipeline"
```

The single costly / state-mutating tool — the one gated by
`run_permission_decision`.
