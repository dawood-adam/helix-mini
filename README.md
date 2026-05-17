# helix-mini

Run a research pipeline over folders of source material, capture every
decision, and build a persistent LLM wiki (**Atlas**) that compounds across
projects. A 12-node LangGraph pipeline (scout → critic → planner → builder →
validator → critic-results) reads from and writes to a shared markdown wiki.

See [HELIX_MINI_PLAN.md](HELIX_MINI_PLAN.md) for the full design, or
[docs/](docs/) for guides and reference.

## Install

```bash
pip install -e .                 # core
pip install -e '.[pdf]'          # + PDF ingestion
pip install -e '.[agent]'        # + `helix-mini agent`
```

## Quick start (Claude subscription — no API key)

```bash
# 1. one-time: mint a subscription token and store it securely
claude setup-token                                   # prints a token
mkdir -p ~/.helix-mini && chmod 700 ~/.helix-mini
"${EDITOR:-nano}" ~/.helix-mini/.env                 # add one line:
                                                     #   CLAUDE_CODE_OAUTH_TOKEN=<paste token>
chmod 600 ~/.helix-mini/.env

# 2. run — helix-mini loads ~/.helix-mini/.env automatically
helix-mini init my-research                          # scaffold a folder
helix-mini run ./my-research --lightspeed
```

That's it — no `export`, no wrapper, no quotes. `~/.helix-mini/.env` (mode
`600`) is the one place helix-mini reads credentials from, every run.

## Auth — pick one

| Method | One-time setup | Notes |
|---|---|---|
| **Claude subscription** (recommended) | `claude setup-token`, then put `CLAUDE_CODE_OAUTH_TOKEN=…` in `~/.helix-mini/.env` | No API key. **OAuth wins**: a stray `ANTHROPIC_API_KEY` never silently bills you. |
| **API key** | `helix-mini setup` (Anthropic/OpenAI) | Metered API billing. |
| **Local** | install [Ollama](https://ollama.com) + `ollama pull qwen3:8b` | Fully offline, no account. |

With any of these configured, `helix-mini run ./folder` just works — no flag
needed. Explicit `--cli` / `--local` override the auto-choice.

## Ways to run

```bash
helix-mini run ./a ./b --lightspeed         # full pipeline (parallel), cheapest model
helix-mini run ./a                          # full pipeline, default model, HITL gates
helix-mini run ./a --cli claude             # force the Claude subscription engine
helix-mini run ./a --local --model-size medium   # offline Qwen via Ollama
helix-mini run ./a --sandbox                # inside a Docker sandbox
helix-mini agent find what we know about PINNs   # conversational — no quotes
helix-mini agent                            # interactive agent session
helix-mini status                           # Atlas stats + projects
helix-mini atlas search cardiac             # search the wiki
helix-mini log my-research                  # decision log
```

`helix-mini agent` auto-approves read-only Atlas tools; launching a pipeline
run from the agent is human-gated (terminal confirmation).

## Develop

```bash
pip install -e '.[dev]'
pytest -q          # 126 passed, 1 skipped (1 opt-in live test)
```
