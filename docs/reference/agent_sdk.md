# helix_mini.agent_sdk

Drives helix-mini through a Claude agent built on the **Claude Agent SDK**.
The whole flow is reachable conversationally: source a folder and run the
pipeline, inspect the Atlas and the git-style snapshot history, and resume the
forge cycle from a chosen stage. The pure `*_text` helpers carry no SDK
dependency and are unit-tested directly; only the agent plumbing imports
`claude-agent-sdk` lazily, so the package stays an optional extra
(`pip install 'helix-mini[agent]'`).

---

## Pure helpers (SDK-free)

```python
def atlas_search_text(query: str, home: Path | None = None) -> str
def atlas_status_text(home: Path | None = None) -> str
def decision_log_text(project: str, home: Path | None = None) -> str
def run_pipeline_text(folder: str, question: str = "",
                      lightspeed: bool = True, home: Path | None = None) -> str
def snapshot_list_text(project: str, home: Path | None = None) -> str
def snapshot_show_text(project: str, num: int, home: Path | None = None) -> str
def snapshot_diff_text(project: str, a: int, b: int,
                       home: Path | None = None) -> str
def snapshot_timeline_text(project: str, home: Path | None = None) -> str
def resume_pipeline_text(project: str, snapshot: int, at: str = "",
                         lightspeed: bool = True,
                         home: Path | None = None) -> str
```

Each backs one MCP tool and reuses `pipeline.snapshots` /
`pipeline.runner.resume_project` (no logic duplicated from the CLI).
`run_pipeline_text` and `resume_pipeline_text` resolve the engine via
`ModelConfig.default()` (OAuth wins), falling back to `cli/claude` so an
agent-launched run never needs a provider key. `resume_pipeline_text`
defaults `at` to the snapshot's own stage and returns the `ValueError` text
if an unknown stage is requested.

---

## `run_permission_decision`

```python
def run_permission_decision(
    tool_name: str, *, interactive: bool, approver=None
) -> tuple[bool, str]
```

**Fail-closed** gate. The seven read tools (`atlas_*`, `decision_log`,
`snapshot_*`) auto-approve. The two gated tools (`run_pipeline`,
`resume_pipeline`) consult `approver` if given, else **deny** — and deny
outright in a non-interactive session. **Every other tool name — including the
SDK's built-in `Bash`/`Write`/`Edit` — is denied**, so a prompt-injected agent
cannot reach an arbitrary tool even if it slips past
`allowed_tools`/`disallowed_tools`. The gate matches both bare and
`mcp__helix__`-prefixed names.

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

`build_helix_server` registers all nine `@tool` wrappers (3 Atlas + 4 snapshot
read + `run_pipeline` + `resume_pipeline`) and returns an in-process SDK MCP
server (`mcp__helix__*`). `run_agent` builds `ClaudeAgentOptions` (the 7 read
tools in `allowed_tools`; the 2 gated tools omitted so they fall through to a
`can_use_tool` confirmation; built-ins in `disallowed_tools`), then runs a
`ClaudeSDKClient` loop — one-shot if `prompt` is given, interactive otherwise.
The `_confirm_run` terminal prompt describes either the folder run or the
`resume project '<p>' from snap-<n> [at '<stage>']`. Raises `RuntimeError`
with an install hint if the SDK is absent.

---

## Tool constants

```python
RUN_TOOL    = "run_pipeline"
_READ_TOOLS  = ("atlas_search", "atlas_status", "decision_log",
                "snapshot_list", "snapshot_show", "snapshot_diff",
                "snapshot_timeline")
_GATED_TOOLS = ("run_pipeline", "resume_pipeline")
```

`_READ_TOOLS` auto-approve; `_GATED_TOOLS` are the costly / state-mutating
tools requiring confirmation. `_READ_TOOL_NAMES` / `_GATED_TOOL_NAMES`
additionally hold the `mcp__helix__`-prefixed forms so the gate recognizes
both. `_DISALLOWED_TOOLS` hard-blocks the SDK built-ins
(`Bash`/`Write`/`Edit`/…) as defense-in-depth.
