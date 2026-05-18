# Helix

Helix turns a folder of source material into validated, contextualized code.
It runs six agents in sequence and stops for your review after each one. A
persistent wiki accumulates what it learns across projects, and every step is
saved as a git-style snapshot you can diff, branch, and resume.

<p align="center">
  <img src="docs/workflow_process_and_version_control_diagram.svg" alt="Helix workflow and version-control diagram" width="100%">
</p>

## How it works

- **Six stages.** Scout, Methods Critic, Planner, Builder, Validator, Results
  Critic. Validator is deterministic; the rest call an LLM.
- **You are in the loop.** A gate runs after every stage. You can proceed,
  send the run back to any earlier stage with a note, or stop. The note is
  given to that stage when it re-runs.
- **The Atlas wiki compounds.** Every stage reads and writes a markdown wiki
  that persists across projects.
- **Every step is a snapshot.** Snapshots are taken automatically. They cost
  no LLM calls and form a branchable history you can resume from any point.
- **Two engines, one pipeline.** By default an agentic CLI (such as Claude
  Code) is the model, so no API key is needed. The same pipeline also runs as
  a LangGraph graph for programmatic use.

## Install

| Command | Adds |
|---|---|
| `pip install -e .` | CLI mode. Dependency-light: `click`, `python-dotenv`, `pyyaml`. |
| `pip install -e '.[sdk]'` | LangGraph orchestrator and the litellm API path. |
| `pip install -e '.[agent]'` | `helix agent` (Claude Agent SDK). |
| `pip install -e '.[pdf]'` | PDF ingestion. |

## Get started

```bash
helix init my-research          # scaffold the project
cd my-research

claude setup-token              # one-time; prints a token
mkdir -p .helix
printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "<paste token>" > .helix/.env
chmod 600 .helix/.env

# add your source files (PDF, markdown, code, data) to this folder, then:
helix run .
```

`helix run .` pauses after every stage and prints a report. Answer the prompt:
`p` to proceed, `g` to send the run back to a stage with feedback, or `s` to
stop.

No Claude subscription? Run `helix setup` for an API key, or `helix run .
--local` to use Ollama offline. Auth precedence is OAuth first: a subscription
token always wins over a stray `ANTHROPIC_API_KEY`, so you are never billed
for the API by accident.

## Everyday commands

```bash
helix run .                                   # human-in-the-loop (default)
helix run . --autonomous-until builder        # auto until a stage, then ask
helix run . --auto                            # fully autonomous
helix run . --engine sdk                      # same pipeline, LangGraph runner
helix snapshots list my-research              # history
helix snapshots diff my-research 3 7
helix snapshots diagram my-research           # Mermaid gitGraph
helix snapshots resume my-research 5 --at planner --branch retry
helix snapshots revert my-research 5          # restore that snapshot's files
helix agent show the timeline for my-research # conversational, gated
helix status                                  # Atlas overview
helix log my-research                         # decision log
helix atlas search cardiac                    # search the wiki
```

## Documentation

| Doc | Read it for |
|---|---|
| [docs/usage.md](docs/usage.md) | Day-to-day: gates, autonomy, engines, the agent |
| [docs/architecture.md](docs/architecture.md) | How the pieces fit (with diagrams) |
| [docs/snapshots.md](docs/snapshots.md) | The git-style snapshot model |
| [docs/agents.md](docs/agents.md) | Editing or adding an agent |
| [REFACTOR.md](REFACTOR.md) | What changed from helix-mini |

## Develop

```bash
pip install -e '.[sdk,dev]'
pytest -q          # 17 passed, including dual-orchestrator conformance
```
