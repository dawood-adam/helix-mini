# Local and Hybrid Mode

## Goal

Run helix-mini using local Qwen models via Ollama — either entirely local (no API key needed) or in hybrid mode (local for simple stages, cloud for critical ones).

## Prerequisites

- helix-mini installed
- [Ollama](https://ollama.com) installed and running
- A Qwen model pulled (see below)

## Setup

### Pull a Qwen model

```bash
# Medium (default, recommended) — 8B parameters
ollama pull qwen3:8b

# Small — 1.7B, fastest, lower quality
ollama pull qwen3:1.7b

# Large — 32B, best quality, slowest
ollama pull qwen3:32b
```

## Fully Local Mode

No API key required. All 6 pipeline stages run on your local Qwen model.

```bash
helix-mini run ./my-folder --local --lightspeed
```

Specify a model size:

```bash
helix-mini run ./my-folder --local --model-size small --lightspeed
helix-mini run ./my-folder --local --model-size large --lightspeed
```

| Size | Model | Parameters | Speed | Quality |
|------|-------|------------|-------|---------|
| `small` | `ollama/qwen3:1.7b` | 1.7B | Fastest | Lower |
| `medium` | `ollama/qwen3:8b` | 8B | Moderate | Good |
| `large` | `ollama/qwen3:32b` | 32B | Slowest | Best |

## Hybrid Mode (Local-Recommended)

Uses local Qwen for simpler stages and a cloud model for stages that need stronger reasoning. Requires an API key for the cloud stages.

```bash
helix-mini run ./my-folder --local-recommended --lightspeed
```

### Stage Routing

| Stage | Mode | Rationale |
|-------|------|-----------|
| scout | Local (Qwen) | File summarization is straightforward |
| builder | Local (Qwen) | Code generation from a clear plan |
| validator | Local (Qwen) | Deterministic — no LLM call |
| critic_methods | Cloud (Claude/GPT) | Requires nuanced feasibility assessment |
| planner | Cloud (Claude/GPT) | Requires strategic planning |
| critic_results | Cloud (Claude/GPT) | Requires critical evaluation |

### With lightspeed cloud model

When `--lightspeed` is combined with `--local-recommended`, the cloud stages use the cheaper model (Claude Haiku instead of Sonnet):

```bash
helix-mini run ./my-folder --local-recommended --model-size small --lightspeed
```

## Another no-API-key option: Claude subscription

If you have a Claude plan, `--cli claude` runs every stage on your
**subscription** rate limits — no API key, no local model. One-time: put a
token in `~/.helix-mini/.env` (see
[Claude Subscription / CLI Engine](claude-cli-engine.md) for the secure
setup), then:

```bash
helix-mini run ./my-folder --cli claude --lightspeed
```

## Variations

- **Without `--lightspeed`**: The model selection is the same, but gates are set to `always_ask` mode.
- **Different Qwen sizes for hybrid**: `--model-size` controls the local model size. Cloud model is determined by `--lightspeed` flag.
