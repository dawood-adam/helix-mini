# Driving helix-mini with a Claude Agent

## Goal

Operate **the whole of helix-mini** conversationally. A Claude agent (built on
the **Claude Agent SDK**) is given helix-mini's operations as tools, so you can
ask it — in natural language — to source a folder and run the pipeline, search
the Atlas, browse/diff the git-style snapshot history, render the development
timeline, and **resume the forge cycle** from a chosen stage.

## Prerequisites

- helix-mini installed with the agent extra: `pip install -e '.[agent]'`
- Auth configured once in `~/.helix-mini/.env` — a Claude subscription token is
  recommended (see [Getting Started](../getting-started.md#first-run-setup--pick-one)
  or [Claude Subscription / CLI Engine](claude-cli-engine.md)).

## Steps

### 1. One-shot — just type the request, no quotes

```bash
helix-mini agent what do we know about cardiac modeling
helix-mini agent run the pipeline on ./new-papers and summarize the verdict
helix-mini agent show the snapshot timeline for cardiac-sim
helix-mini agent pick cardiac-sim back up from snap-5 and re-run from the builder
```

### 2. Interactive

```bash
helix-mini agent
# you> search the atlas for PINNs
# you> show the decision log for cardiac-research
# you> exit
```

`--max-turns N` (default 30) bounds a session.

## Tools the agent has

| Tool | Access | Notes |
|------|--------|-------|
| `atlas_search` | auto-approved | Keyword search over the wiki |
| `atlas_status` | auto-approved | Page count + project list |
| `decision_log` | auto-approved | Rendered decision log for a project |
| `snapshot_list` | auto-approved | Git-style snapshot log |
| `snapshot_show` | auto-approved | One snapshot's key state |
| `snapshot_diff` | auto-approved | Diff two snapshots |
| `snapshot_timeline` | auto-approved | Mermaid `gitGraph` of development over time |
| `run_pipeline` | **human-gated** | Expensive; terminal confirm, denied non-interactively |
| `resume_pipeline` | **human-gated** | Resume the forge cycle from a snapshot; terminal confirm, denied non-interactively |

These nine are exposed as in-process MCP tools (`mcp__helix__*`) — no separate
server process. The permission gate is **fail-closed**: every other tool
(including the SDK's built-in `Bash`/`Write`/`Edit`) is denied *and*
hard-blocked, so the agent can never escape to arbitrary commands.

## How It Works

1. `helix-mini agent` clears the nested-session guard (so the SDK's bundled
   `claude` runs even inside Claude Code) and prefers subscription auth via
   `claude_code_auth()` (drops `ANTHROPIC_API_KEY` when a token is set).
2. `build_helix_server()` registers all nine tools and creates an in-process
   SDK MCP server.
3. `ClaudeAgentOptions` auto-approves the seven read tools via `allowed_tools`;
   `run_pipeline`/`resume_pipeline` are intentionally omitted so they fall
   through to a fail-closed `can_use_tool` confirmation, and the SDK built-ins
   are listed in `disallowed_tools`.
4. A `ClaudeSDKClient` loop runs your prompt (one-shot) or an interactive
   session. A launched run/resume reuses `ModelConfig.default()` (OAuth wins),
   falling back to `cli/claude` so it needs no provider key.

## Variations

- **No SDK installed**: the command exits with a clear
  `pip install 'helix-mini[agent]'` hint.
- **Non-interactive** (CI, piped input): `run_pipeline`/`resume_pipeline` are
  denied automatically; the seven read tools still work.
- **Browse then resume**: ask for the timeline/diff first, then "resume from
  snap-N at builder" — see [Snapshots as Git-Style Version Control](snapshots.md).
- **Power the pipeline itself via the CLI instead**: see
  [Claude Subscription / CLI Engine](claude-cli-engine.md).
