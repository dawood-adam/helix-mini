"""`helix` CLI — two scaffolders + an MCP launcher.

* ``helix init`` (run *once* after cloning the tool) scaffolds a Helix
  **workspace** in the current directory: the cross-project Atlas root,
  the workspace marker, and a `.mcp.json`.
* ``helix new <project>`` scaffolds a **project** (run root) inside the
  workspace: a source folder, ``question.md``, a per-project
  ``helix.toml``, and a `.mcp.json` so Claude Code finds the server when
  the user opens the project folder.
* ``helix mcp`` launches the MCP server (Claude Code normally spawns this
  via ``.mcp.json``).

The pipeline itself is driven through the MCP server, not the CLI."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import click

from . import atlas_init, config
from .core import constitution
from .core.transitions import stages

CLAUDE_MD = """# Helix project

This folder is a Helix research project. The pipeline is:

`{stages}`

## Starting ("start helix")

When I say **start helix** (or similar), do NOT run the pipeline yet. First:

1. Ask me to point out the **collection of source material** to begin with —
   a folder or set of files (papers, PDFs, code, data). If none are here yet,
   tell me to add them to this folder (or a subfolder) and wait.
2. List what you find there so I can confirm the collection is right.
3. Check `question.md`; ask me to confirm or fill in the research question.
4. Only then drive the pipeline over that collection.

## Driving the pipeline

Helix is driven through its MCP server: a gate pauses after **every** stage.
Relay each gate report to me and wait for my decision: proceed / send the run
back to ANY earlier stage with feedback / stop. A snapshot is minted at every
stage and every send-back, so history is a real DAG you can resume from.
"""

AGENTS_MD = """# AGENTS.md — recommended Claude Code skills/plugins

This Helix workspace's agents (Scout · Scout Critic · Planner · Builder
· Validator · Results Critic) will *use* Claude Code skills and plugins
if they're installed in your environment — gracefully, "use if
available". Install whichever you want; nothing is required.

## Recommended

- **WebSearch / WebFetch** — built into Claude Code. Scout uses these
  for the lit-dive sub-phase to fill source-coverage gaps.
- **`superpowers`** ([obra/superpowers](https://github.com/obra/superpowers)
  — MIT, by Jesse Vincent) — structured-extraction skills that pair
  well with Scout's frame/source/synthesize loop.
- **`simplify`** — code-review style refactor pass. Builder is
  instructed to apply it after the impl phase, before the refactor
  submit.
- **`review`** — general code/spec critique. Useful for Scout Critic
  on the spec and Results Critic on the artifacts.
- **`security-review`** — secrets / injection / unsafe deps. Results
  Critic invokes it when artifacts contain code.

## Conventions

- Agents are told to *prefer* an installed skill but to proceed
  without one. A missing skill should never block a submit.
- Skills run in the agent's environment (Claude Code), not on the
  Helix server — Helix has no model and no skills of its own. Costs
  and rate limits live with the agent.

This file is part of the open
[AGENTS.md](https://github.com/openai/agents.md) convention.
"""


WORKSPACE_README = """# Helix workspace

This directory is a Helix **workspace** — the shared root for one or more
research projects. The Atlas (cross-project knowledge base) lives at
`atlas/`; each project lives in its own subfolder, created by:

```
helix new <project-name>
```

## Layout

```
{ws}/
├── helix.toml          # workspace marker + Atlas config
├── .mcp.json           # registers the helix MCP server for Claude Code
├── atlas/              # the shared knowledge base (cross-project)
│   ├── inbox/  raw/  sources/  concepts/  entities/  projects/
│   └── ...
└── <project>/          # one per `helix new <project>`
    ├── question.md
    ├── helix.toml      # per-project limits
    ├── .mcp.json       # so Claude Code finds the server here too
    └── .helix/         # per-project snapshots / runs / pending
```

`helix init` is run **once**; `helix new` is run per project.
"""


def _mcp_json() -> str:
    # Absolute interpreter + `-m helix.mcp.server` is PATH-independent:
    # the client resolves a bare `command` against its own PATH, which
    # need not include the env's bin dir.
    return json.dumps({"mcpServers": {"helix": {
        "command": sys.executable,
        "args": ["-m", "helix.mcp.server"],
    }}}, indent=2) + "\n"


def _scaffold_workspace(root: Path) -> None:
    """Idempotent workspace scaffolder. Writes the workspace marker, the
    Atlas tree, the `.mcp.json`, and a README. Existing files are left
    alone (so re-running `helix init` after editing is safe)."""
    root.mkdir(parents=True, exist_ok=True)
    toml = root / "helix.toml"
    if not toml.exists():
        toml.write_text(
            '[workspace]\n# workspace marker — see `helix init`\n\n'
            '[atlas]\npath = "atlas"\n'
        )
    atlas_init.ensure_atlas_tree(root / "atlas")
    constitution.ensure_constitution(root)
    mcp = root / ".mcp.json"
    if not mcp.exists():
        mcp.write_text(_mcp_json())
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(WORKSPACE_README.format(ws=root.name))
    agents = root / "AGENTS.md"
    if not agents.exists():
        agents.write_text(AGENTS_MD)


def _scaffold_project(root: Path, name: str) -> Path:
    """Scaffold a project folder ``name`` under ``root`` (the workspace).
    Refuses to overwrite an existing folder."""
    d = root / name
    if d.exists():
        raise click.ClickException(
            f"'{name}' already exists at {d}. Pick a different name or "
            "remove the folder.")
    d.mkdir()
    (d / "question.md").write_text(
        "# Research Question\n\nReplace this with your question, then add "
        "source files (PDFs, papers, data) to this folder.\n"
    )
    (d / "CLAUDE.md").write_text(CLAUDE_MD.format(stages=" → ".join(stages())))
    (d / "helix.toml").write_text(
        f"[limits]\ntoken_cap = {config.TOKEN_CAP_DEFAULT}\n"
        f"call_cap = {config.CALL_CAP_DEFAULT}\n"
    )
    # Per-project .mcp.json so Claude Code finds the server when the user
    # opens this project folder. Same content as the workspace's; the
    # server's atlas_path() resolves to the workspace via the marker walk.
    (d / ".mcp.json").write_text(_mcp_json())
    return d


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging")
def cli(verbose: bool) -> None:
    """Helix — a collaborative research orchestrator + discovery engine."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@cli.command()
def init() -> None:
    """Scaffold a Helix *workspace* in the current directory (run once).

    Creates a workspace marker (`helix.toml [workspace]`), the shared
    Atlas tree (`atlas/`), a `.mcp.json`, and a README. Idempotent."""
    cwd = Path.cwd()
    _scaffold_workspace(cwd)
    click.echo(f"Workspace ready: {cwd}")
    click.echo("  Atlas at: atlas/")
    click.echo("  Next:     helix new <project-name>")


@cli.command()
@click.argument("name")
def new(name: str) -> None:
    """Scaffold a new research *project* inside the current workspace.

    Creates `<name>/question.md`, `<name>/helix.toml`, `<name>/.mcp.json`,
    `<name>/CLAUDE.md`. The project's run state (snapshots, runs,
    pending) is created on demand under `<name>/.helix/`; its Atlas
    contributions land in the workspace's shared `atlas/`."""
    cwd = Path.cwd()
    if not config._has_workspace_marker(cwd):
        raise click.ClickException(
            f"{cwd} is not a Helix workspace. Run `helix init` first.")
    d = _scaffold_project(cwd, name)
    click.echo(f"Project ready: {d}")
    click.echo(f"  1. Edit  {name}/question.md")
    click.echo(f"  2. Add   source files to {name}/")
    click.echo(f"  3. cd    {name}  && open in Claude Code, then: start helix")


@cli.command()
def mcp() -> None:
    """Launch the helix MCP server over stdio.

    Claude Code normally spawns this for you via .mcp.json; run it by hand
    only to debug the server."""
    from .mcp.server import main

    main()


if __name__ == "__main__":
    cli()
