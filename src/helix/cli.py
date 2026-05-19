"""`helix` CLI — scaffolds a project. The pipeline is driven through the MCP
server (added in Phase 1), not the CLI. This stays minimal on purpose."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click

from . import config
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


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging")
def cli(verbose: bool) -> None:
    """Helix — a self-auditing research pipeline with a persistent wiki."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@cli.command()
@click.argument("name", default="my-research")
def init(name):
    """Scaffold a new helix project folder."""
    d = Path(name)
    if d.exists():
        raise click.ClickException(f"'{name}' already exists")
    d.mkdir()
    (d / "question.md").write_text(
        "# Research Question\n\nReplace this with your question, then add "
        "source files (PDFs, papers, data) to this folder.\n"
    )
    (d / "CLAUDE.md").write_text(CLAUDE_MD.format(stages=" → ".join(stages())))
    (d / "helix.toml").write_text(
        '[atlas]\npath = "atlas"\n\n'
        f"[limits]\ntoken_cap = {config.TOKEN_CAP_DEFAULT}\n"
        f"call_cap = {config.CALL_CAP_DEFAULT}\n"
    )
    # Lets Claude Code auto-discover + spawn the helix MCP server here.
    (d / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"helix": {"command": "helix-mcp"}}}, indent=2)
        + "\n"
    )
    click.echo(f"Created: {d}/")
    click.echo(f"  1. Edit {name}/question.md")
    click.echo(f"  2. Add source files to {name}/")
    click.echo(f"  3. cd {name} && open it in Claude Code, then: start helix")


@cli.command()
def mcp():
    """Launch the helix MCP server over stdio.

    Claude Code normally spawns this for you via .mcp.json; run it by hand
    only to debug the server."""
    from .mcp.server import main

    main()


if __name__ == "__main__":
    cli()
