# Helix

Helix is an MCP-native research orchestrator. It turns a collection of source
material into validated, contextualized code through a six-stage pipeline,
maintains a persistent research wiki that compounds across projects, and keeps
a git-style snapshot history of every step.

You drive it by talking to an MCP client such as Claude Code. Helix holds no
model credentials: every model call is delegated back to the client through
MCP sampling, so there are no API keys to configure.

Three components behind one MCP server:

- **Forge** — the pipeline: Scout → Methods Critic → Planner → Builder →
  Validator → Results Critic, with a human checkpoint at every transition.
- **Atlas** — the wiki: frontmatter-typed pages, frictionless ingest,
  auto-routing recall, and hygiene linting.
- **Snapshots** — a content-addressed DAG of every transition, with branch,
  freeze, fork, and resume.

<p align="center">
  <img src="docs/workflow_process_and_version_control_diagram.svg" alt="Helix workflow and version-control diagram" width="100%">
</p>


## Requirements

- Python ≥ 3.11
- An MCP client that supports sampling and elicitation (Claude Code)

## Quick start

```bash
pip install -e .                 # core
pip install -e '.[embed,pdf]'    # optional: semantic recall + PDF ingest

helix init my-research
cd my-research
```

`helix init` writes `question.md`, `helix.toml`, `CLAUDE.md`, and an
`.mcp.json` that registers the server:

```json
{ "mcpServers": { "helix": { "command": "helix-mcp" } } }
```

Open the project folder in Claude Code. It launches `helix-mcp`
automatically; there is nothing else to configure. (`helix mcp` runs the
server by hand for debugging.)

## Quick usage

Work in plain language. Claude Code calls Helix's MCP tools for you.

```text
start helix
    Runs the hx_start wizard: it asks for a project name, the research
    question, a control mode, and the source folder, then starts the run.

[drop a PDF into atlas/inbox/]  process my inbox
    Ingests the file as a typed source page and moves the original to
    atlas/raw/. Re-running is idempotent.

what do we know about rPPG?
    Auto-routing recall returns ranked references; bodies are fetched
    on demand.

health-check the atlas
    Lints for orphans, contradictions, stale pages, dangling links,
    missing aliases, and un-synthesized clusters.

where were we?
    Reads the hot cache and the last run's status.
```

A run pauses at every gate by default. At a gate you can proceed, send the
run back to any earlier stage with a directive, or stop. You can also let it
run automatically up to a chosen stage, or fully unattended.

## Documentation

| Document | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | The system and its layers |
| [docs/usage.md](docs/usage.md) | Driving Helix end to end |
| [docs/mcp.md](docs/mcp.md) | The MCP surface: tools, resources, prompts |
| [docs/forge.md](docs/forge.md) | The pipeline |
| [docs/atlas.md](docs/atlas.md) | The wiki |
| [docs/snapshots.md](docs/snapshots.md) | Version control |

## Development

```bash
pip install -e '.[dev]'
pytest -q
```

In a git worktree the editable install resolves to the main checkout; run
tests with `PYTHONPATH="$PWD/src" pytest -q`.
