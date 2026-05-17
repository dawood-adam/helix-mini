# Claude Subscription / CLI Engine

## Goal

Run the full pipeline on your **Claude subscription** instead of a metered API
key, by pointing every stage at the `claude` CLI (`cli/claude` engine). Same
12-node pipeline, same Atlas — only the inference backend changes.

## Prerequisites

- helix-mini installed
- The `claude` binary on PATH (install Claude Code)
- A Claude subscription token (recommended): `claude setup-token`

## Steps

### 1. Mint a subscription token

```bash
claude setup-token
export CLAUDE_CODE_OAUTH_TOKEN="..."        # or add to ~/.helix-mini/.env
```

This is **not** an API key — litellm/the HTTP API can't use it. It
authenticates the bundled `claude` CLI against your Claude plan's rate limits.

### 2. Run

```bash
# Explicit:
helix-mini run ./my-folder --cli claude --lightspeed

# Or just run — with the token set, this auto-selects cli/claude (OAuth wins):
helix-mini run ./my-folder --lightspeed
```

Pick an engine-native model with `--cli-model`:

```bash
helix-mini run ./my-folder --cli claude --cli-model opus
```

## How It Works

1. `ModelConfig.cli("claude")` sets every stage's model to `cli/claude`.
2. `call_llm` sees the `cli/` prefix and dispatches to `llm_cli.call_cli_llm`
   instead of litellm — the pipeline is unchanged.
3. The child env is built by `claude_subprocess_env()`: the nested-session
   guard vars are stripped (so it runs even inside Claude Code), and when an
   OAuth token is set, `ANTHROPIC_API_KEY` is **dropped** so a stray key can't
   silently switch you to pay-per-token billing (**OAuth wins**).
4. `claude -p --output-format json --max-turns 1` runs per stage; its JSON
   `result` / `total_cost_usd` / `usage` are parsed back. Because Claude
   reports real cost, the $5 cost cap still works.

## Variations

- **No token, just the binary**: `--cli claude` still works using whatever auth
  the `claude` CLI already has; without a token the OAuth-wins drop is skipped.
- **Other CLIs**: add a `[cli.<name>]` block to `~/.helix-mini/config.toml`
  (declarative `CLIEngine` fields) and use `--cli <name>` — no code change.
  Engines that don't report cost get a per-run call-count cap (24) instead of
  the dollar cap.
- **Conversational instead**: see
  [Driving helix-mini with a Claude Agent](claude-agent.md).
