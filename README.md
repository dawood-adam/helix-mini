# helix-mini

Research pipelines with a persistent LLM wiki.

Helix Mini runs a 6-agent research pipeline over folders of source material — papers, code, data — identifying approaches, critiquing, planning, building, validating, and synthesizing findings. Every agent reads from and writes to a shared **Atlas**, a persistent markdown wiki that compounds knowledge across projects.

## Features

- **6-agent pipeline** — Scout, critic-methods, planner, builder, validator, and critic-results, orchestrated by LangGraph
- **Persistent Atlas wiki** — Markdown-based knowledge base that grows across projects
- **Multiple run modes** — Lightspeed (fast/cheap), local (Qwen via Ollama), hybrid (local + cloud), Docker sandbox
- **Provider-agnostic** — Anthropic, OpenAI, or local Ollama models via litellm
- **Full audit trail** — Decision logs and state snapshots at every pipeline stage

## Quickstart

```bash
pip install -e .
helix-mini setup
helix-mini init my-research
# Add source files to my-research/
helix-mini run ./my-research --lightspeed
```

## Documentation

- **[Architecture](docs/architecture.md)** — System overview, component map, data flow, Mermaid diagrams
- **[Getting Started](docs/getting-started.md)** — Installation, configuration, verification
- **[API Reference](docs/reference/)** — All public modules, classes, and functions
- **[Usage Guides](docs/guides/)** — Tutorials for each run mode and Atlas exploration
- **[Contributing](CONTRIBUTING.md)** — Dev setup, conventions, how to extend

## Requirements

- Python >= 3.11
- One of: Anthropic API key, OpenAI API key, or [Ollama](https://ollama.com) with a Qwen model
