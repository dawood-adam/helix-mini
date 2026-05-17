# Driving helix-mini with a Claude Agent

## Goal

Operate helix-mini conversationally. A Claude agent (built on the **Claude
Agent SDK**) is given helix-mini's operations as tools, so you can ask it to
search the Atlas, summarize a project's decisions, or kick off a pipeline run —
in natural language.

## Prerequisites

- helix-mini installed with the agent extra: `pip install -e '.[agent]'`
- Auth for the bundled `claude` CLI — a Claude subscription token is
  recommended: `claude setup-token` → `export CLAUDE_CODE_OAUTH_TOKEN=...`

## Steps

### 1. One-shot

```bash
helix-mini agent "what do we know about cardiac modeling?"
helix-mini agent "run the pipeline on ./new-papers and summarize the verdict"
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
| `run_pipeline` | **human-gated** | Expensive; prompts for terminal confirmation, denied in non-interactive sessions |

These are exposed as in-process MCP tools (`mcp__helix__*`) — no separate
server process.

## How It Works

1. `helix-mini agent` clears the nested-session guard (so the SDK's bundled
   `claude` runs even inside Claude Code) and prefers subscription auth via
   `claude_code_auth()` (drops `ANTHROPIC_API_KEY` when a token is set).
2. `build_helix_server()` registers the four tools and creates an in-process
   SDK MCP server.
3. `ClaudeAgentOptions` auto-approves the read tools via `allowed_tools`;
   `run_pipeline` is intentionally omitted so it falls through to a
   `can_use_tool` confirmation.
4. A `ClaudeSDKClient` loop runs your prompt (one-shot) or an interactive
   session. A launched run reuses `ModelConfig.default()` (OAuth wins).

## Variations

- **No SDK installed**: the command exits with a clear
  `pip install 'helix-mini[agent]'` hint.
- **Non-interactive** (CI, piped input): `run_pipeline` is denied automatically;
  the read tools still work.
- **Power the pipeline itself via the CLI instead**: see
  [Claude Subscription / CLI Engine](claude-cli-engine.md).
