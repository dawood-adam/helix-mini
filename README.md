# helix-mini

Run a research pipeline over folders of source material, capture every
decision, and build a persistent LLM wiki (**Atlas**) that compounds across
projects. A 12-node LangGraph pipeline (scout → critic → planner → builder →
validator → critic-results) reads from and writes to a shared markdown wiki.

See [HELIX_MINI_PLAN.md](HELIX_MINI_PLAN.md) for the full design.

## Install

```bash
pip install -e .                 # core
pip install -e '.[pdf]'          # + PDF ingestion
pip install -e '.[agent]'        # + `helix-mini agent` (Claude Agent SDK)
```

## Quickstart

```bash
helix-mini init my-research          # scaffold a folder
helix-mini run ./my-research --lightspeed
helix-mini status                    # Atlas stats + projects
helix-mini atlas search "cardiac"    # search the wiki
helix-mini log my-research           # decision log
```

## Auth — pick one

The pipeline is engine-agnostic; every LLM call funnels through one chokepoint.

| Auth | How | Powers |
|---|---|---|
| **Claude subscription** | `claude setup-token` → `export CLAUDE_CODE_OAUTH_TOKEN=…` | `--cli claude`, `helix-mini agent` — no API key |
| **API key** | `helix-mini setup` (Anthropic/OpenAI) | default litellm path |
| **Local** | Ollama + Qwen | `--local` / `--local-recommended` |

With a token set, `helix-mini run ./folder` (no flags) auto-uses your
subscription — **OAuth wins**: a stray `ANTHROPIC_API_KEY` never silently
switches you to pay-per-token billing. Explicit `--cli` / `--local` override.

## Modes

```bash
helix-mini run ./a ./b --lightspeed              # auto-gates, cheapest model, parallel
helix-mini run ./a --local --model-size medium   # offline Qwen via Ollama
helix-mini run ./a --cli claude                  # pilot inference through the Claude CLI
helix-mini run ./a --sandbox                     # inside a Docker sandbox
helix-mini agent "search the atlas for PINNs"    # drive it via a Claude agent
helix-mini agent                                 # interactive agent session
```

`helix-mini agent` exposes Atlas search / status / decision-log as auto-approved
tools; launching a pipeline run is human-gated (terminal confirmation).

## Develop

```bash
pip install -e '.[dev]'
pytest -q          # 123 tests
```
