# Helix

A self-auditing research pipeline. Point it at a folder of source material; it
runs six agents — Scout → Methods Critic → Planner → Builder → Validator →
Results Critic — pausing at a human gate after every stage. A persistent
**Atlas** wiki compounds knowledge across projects, and every stage mints an
immutable, git-style **snapshot** you can diff, branch, revert, and resume.

<p align="center">
  <img src="docs/workflow_process_and_version_control_diagram.svg" alt="Helix workflow and version-control diagram" width="100%">
</p>

Two ways to run the **same** pipeline:

- **CLI-driven (default, no API key):** an agentic CLI such as Claude Code is
  the engine. Near-zero dependencies — `click`, `python-dotenv`, `pyyaml`.
- **SDK/library (`helix[sdk]`):** the same pipeline as a LangGraph graph over
  the litellm API path, for programmatic/automated use.

Agents are **markdown files** — edit a prompt, no code change. Snapshots cost
**zero LLM calls**. Cycling is **unbounded**, bounded only by a configurable
cost ceiling that *pauses* (resumable) instead of failing.

## Install

```bash
pip install -e .              # CLI mode — dependency-light
pip install -e '.[sdk]'       # + LangGraph orchestrator / litellm API path
pip install -e '.[agent]'     # + `helix agent` (Claude Agent SDK)
pip install -e '.[pdf]'       # + PDF ingestion
```

## Quickstart (Claude subscription — no API key)

```bash
claude setup-token                                   # one-time
mkdir -p .helix && "${EDITOR:-nano}" .helix/.env     # add: CLAUDE_CODE_OAUTH_TOKEN=<token>
chmod 600 .helix/.env

helix init my-research                               # scaffold a project
cd my-research                                       # has question.md + CLAUDE.md + helix.toml
# add source files, then:
helix run .                                          # pauses at every stage for you
```

Auth precedence is **OAuth wins**: a subscription token always beats a stray
`ANTHROPIC_API_KEY`, so you are never silently billed for the API. API keys
(`helix setup`) and fully-offline Ollama (`--local`) also work.

## Quick usage

```bash
helix run .                          # full HITL — proceed / send back to ANY stage / stop
helix run . --autonomous-until builder   # auto early gates, then ask
helix run . --auto                   # fully autonomous
helix run . --engine sdk             # same pipeline via the LangGraph runner
helix snapshots list my-research     # git-style history
helix snapshots diff my-research 3 7
helix snapshots diagram my-research  # Mermaid gitGraph
helix snapshots resume my-research 5 --at planner --branch retry
helix snapshots revert my-research 5 # restore that snapshot's artifacts
helix agent show the timeline for my-research   # conversational (gated)
helix status | helix log <p> | helix atlas search <q>
```

At any gate you can send the run back to **any** earlier stage with a note;
that feedback is fed into that stage on re-run. The history branches and
resumes like git.

## Docs

| Doc | What |
|-----|------|
| [docs/architecture.md](docs/architecture.md) | Two orchestrators over one core (Mermaid) |
| [docs/usage.md](docs/usage.md) | Detailed usage: HITL, autonomy, engines, CLI-driven mode |
| [docs/snapshots.md](docs/snapshots.md) | Git-style snapshot model + cost rationale |
| [docs/agents.md](docs/agents.md) | Authoring the markdown agents |
| [REFACTOR.md](REFACTOR.md) | What changed from helix-mini and why it's lighter |

## Develop

```bash
pip install -e '.[sdk,dev]'
pytest -q          # 17 passed (incl. dual-orchestrator conformance)
```
