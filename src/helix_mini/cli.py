"""CLI commands for helix-mini."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import click

from .app import HelixMini
from .atlas import Atlas
from .config import HELIX_HOME, PROVIDERS, QWEN_SIZES, ModelConfig, ensure_config, has_api_key
from .pipeline.decisions import render_decisions_md


def _cli_progress(stage: str, project: str, cost: float) -> None:
    """Progress callback for CLI output."""
    click.echo(f"  [{project}] {stage} (${cost:.4f})")


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
def cli(verbose: bool) -> None:
    """Helix Mini — research pipelines with a persistent LLM wiki."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@cli.command()
@click.argument("folders", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--lightspeed", is_flag=True, help="Auto-gates + cheapest model")
@click.option("-q", "--question", default="", help="Research question to guide analysis")
@click.option("--sandbox", is_flag=True, help="Run inside a Docker sandbox")
@click.option(
    "--local", is_flag=True,
    help="Run all stages locally using Qwen via Ollama (no API key needed)",
)
@click.option(
    "--local-recommended", "local_recommended", is_flag=True,
    help="Run simple stages locally (Qwen), critical stages via cloud API",
)
@click.option(
    "--model-size",
    type=click.Choice(list(QWEN_SIZES.keys()), case_sensitive=False),
    default=None,
    help="Qwen model size for local inference (small/medium/large)",
)
@click.option(
    "--cli", "cli_engine", default=None, metavar="ENGINE",
    help="Pilot the pipeline through an LLM CLI (e.g. 'claude'). No API key "
    "needed; the CLI handles its own auth. Define more in config.toml.",
)
@click.option(
    "--cli-model", "cli_model", default=None, metavar="MODEL",
    help="Engine-native model for --cli (e.g. 'opus', 'sonnet', 'haiku').",
)
def run(
    folders: tuple[str, ...],
    lightspeed: bool,
    question: str,
    sandbox: bool,
    local: bool,
    local_recommended: bool,
    model_size: str | None,
    cli_engine: str | None,
    cli_model: str | None,
) -> None:
    """Run Forge pipeline on one or more folders."""
    # Resolve model config based on flags
    if cli_engine:
        from .llm_cli import CLIEngineError, get_engine

        try:
            eng = get_engine(cli_engine)
        except CLIEngineError as e:
            click.echo(str(e), err=True)
            sys.exit(1)
        if not eng.available():
            click.echo(
                f"CLI engine '{cli_engine}' is not on PATH (looked for "
                f"'{eng.bin}'). Install it first.",
                err=True,
            )
            sys.exit(1)
        model_config = ModelConfig.cli(cli_engine, native_model=cli_model)
        mode_label = f"cli:{cli_engine}" + (f":{cli_model}" if cli_model else "")
    elif local or local_recommended:
        size = model_size or "medium"
        if local:
            model_config = ModelConfig.local(size)
            mode_label = f"local ({QWEN_SIZES[size]})"
        else:
            if not has_api_key():
                click.echo("--local-recommended needs an API key for critical stages.")
                click.echo("Run 'helix-mini setup' first, or use --local for fully local.")
                sys.exit(1)
            model_config = ModelConfig.local_recommended(size, lightspeed=lightspeed)
            mode_label = f"local-recommended ({QWEN_SIZES[size]} + cloud)"
    else:
        model_config = ModelConfig.default(lightspeed=lightspeed)
        if model_config is None:
            click.echo("No Claude OAuth token or API key found.")
            click.echo(
                "Run 'claude setup-token' and export CLAUDE_CODE_OAUTH_TOKEN "
                "to use your Claude subscription,"
            )
            click.echo(
                "or 'helix-mini setup' for an API key, or --local for a "
                "local Qwen model."
            )
            sys.exit(1)
        if model_config.model.startswith("cli/"):
            from .llm_cli import get_engine

            if not get_engine("claude").available():
                click.echo(
                    "Claude CLI not found on PATH — reinstall Claude Code.",
                    err=True,
                )
                sys.exit(1)
            mode_label = "claude-subscription" + (
                " lightspeed" if lightspeed else ""
            )
        else:
            mode_label = "lightspeed" if lightspeed else "normal"

    folder_paths = [Path(f).resolve() for f in folders]

    if sandbox:
        from .docker import run_sandboxed

        click.echo(f"Helix Mini (sandbox) — {len(folder_paths)} folder(s), mode={mode_label}")
        try:
            run_sandboxed(folder_paths, lightspeed=lightspeed, question=question)
        except Exception as e:
            click.echo(f"Sandbox failed: {e}", err=True)
            sys.exit(1)
        return

    click.echo(f"Helix Mini — {len(folder_paths)} folder(s), mode={mode_label}")
    for fp in folder_paths:
        click.echo(f"  -> {fp.name}")

    app = HelixMini()
    try:
        results = app.run(
            folder_paths,
            lightspeed=lightspeed,
            research_question=question,
            progress_fn=_cli_progress,
            model_config=model_config,
        )

        click.echo("\n--- Results ---")
        for r in results:
            status = "error" if r.error else "done"
            click.echo(
                f"  {r.project_name}: {status} "
                f"(stages: {len(r.completed_stages)}, cost: ${r.cost_so_far:.4f})"
            )
            if r.error:
                click.echo(f"    Error: {r.error}")
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Pipeline failed: {e}", err=True)
        if logging.getLogger().level == logging.DEBUG:
            import traceback

            traceback.print_exc()
        sys.exit(1)


@cli.command()
def status() -> None:
    """Show Atlas status and recent projects."""
    atlas_root = HELIX_HOME / "atlas"
    if not atlas_root.exists():
        click.echo("No Atlas found. Run 'helix-mini run <folder>' first.")
        return

    atlas = Atlas(atlas_root)
    index = atlas.read_all_summaries()
    page_count = sum(1 for line in index.splitlines() if line.startswith("- ["))

    click.echo(f"Atlas: {atlas_root}")
    click.echo(f"Pages: {page_count}")

    projects_dir = atlas_root / "projects"
    if projects_dir.exists():
        projects = [d.name for d in projects_dir.iterdir() if d.is_dir()]
        if projects:
            click.echo(f"\nProjects: {', '.join(projects)}")


@cli.command("log")
@click.argument("project")
def show_log(project: str) -> None:
    """Print decision log for a project."""
    decisions_path = HELIX_HOME / "atlas" / "projects" / project / ".decisions.json"
    if not decisions_path.exists():
        click.echo(f"No decisions found for project: {project}")
        return

    click.echo(render_decisions_md(decisions_path))


@cli.group()
def atlas() -> None:
    """Atlas wiki commands."""


@atlas.command("search")
@click.argument("query")
def atlas_search(query: str) -> None:
    """Search the Atlas wiki."""
    atlas_root = HELIX_HOME / "atlas"
    if not atlas_root.exists():
        click.echo("No Atlas found.")
        return

    a = Atlas(atlas_root)
    results = a.read(query)
    if not results:
        click.echo(f"No results for: {query}")
        return

    for page in results:
        click.echo(f"\n--- {page.title} ({page.path}) ---")
        preview = page.content[:500]
        if len(page.content) > 500:
            preview += "\n..."
        click.echo(preview)


@cli.command()
def setup() -> None:
    """Interactive setup — pick provider, enter API key, validate."""
    click.echo("Helix Mini Setup")
    click.echo("=" * 40)

    # 1. Pick provider
    provider_names = list(PROVIDERS.keys())
    click.echo("\nAvailable providers:")
    for i, name in enumerate(provider_names, 1):
        click.echo(f"  {i}. {name}")

    choice = click.prompt(
        "Choose provider",
        type=click.IntRange(1, len(provider_names)),
        default=1,
    )
    provider = provider_names[choice - 1]
    provider_info = PROVIDERS[provider]

    # 2. Enter API key
    env_var = provider_info["env_var"]
    existing = os.environ.get(env_var)
    if existing:
        click.echo(f"\n{env_var} is already set.")
        if not click.confirm("Replace it?", default=False):
            api_key = existing
        else:
            api_key = click.prompt(f"Enter {env_var}", hide_input=True)
    else:
        api_key = click.prompt(f"\nEnter {env_var}", hide_input=True)

    # 3. Validate
    click.echo("\nValidating API key...")
    from .config import validate_api_key

    if validate_api_key(provider, api_key):
        click.echo("  API key is valid!")
    else:
        click.echo("  Warning: Could not validate key (network issue or invalid key)")
        if not click.confirm("Save anyway?", default=False):
            click.echo("Setup cancelled.")
            return

    # 4. Save to ~/.helix-mini/.env
    HELIX_HOME.mkdir(parents=True, exist_ok=True)
    env_path = HELIX_HOME / ".env"

    env_lines: list[str] = []
    if env_path.exists():
        env_lines = [
            line
            for line in env_path.read_text().splitlines()
            if not line.startswith(f"{env_var}=")
        ]
    env_lines.append(f"{env_var}={api_key}")
    env_path.write_text("\n".join(env_lines) + "\n")

    # 5. Ensure config.toml exists
    config_path = ensure_config()

    click.echo(f"\nSaved to: {env_path}")
    click.echo(f"Config: {config_path}")
    click.echo("\nReady! Try: helix-mini run ./your-folder --lightspeed")


@cli.command()
@click.argument("name", default="my-research")
def init(name: str) -> None:
    """Create a new project folder ready for research."""
    project_dir = Path(name)
    if project_dir.exists():
        click.echo(f"Error: '{name}' already exists", err=True)
        sys.exit(1)

    project_dir.mkdir()
    (project_dir / "question.md").write_text(
        "# Research Question\n\n"
        "Replace this with your research question, then add your\n"
        "source files (PDFs, papers, data) to this folder.\n\n"
        f"Run: helix-mini run ./{name} --lightspeed\n"
    )

    click.echo(f"Created: {project_dir}/")
    click.echo(f"  1. Edit {name}/question.md with your research question")
    click.echo(f"  2. Add source files to {name}/")
    click.echo(f"  3. Run: helix-mini run ./{name} --lightspeed")


@cli.command()
@click.argument("prompt", required=False)
@click.option(
    "--max-turns", default=30, show_default=True,
    help="Max agent turns before the session stops",
)
def agent(prompt: str | None, max_turns: int) -> None:
    """Drive helix-mini conversationally via a Claude agent (Agent SDK).

    With PROMPT, runs one-shot; without it, opens an interactive session.
    The agent can search the Atlas and (with confirmation) run the pipeline.
    Needs the optional extra: pip install 'helix-mini[agent]'

    Auth: set CLAUDE_CODE_OAUTH_TOKEN ('claude setup-token') to run on your
    Claude subscription rate limits instead of API billing.
    """
    # The Agent SDK spawns its bundled `claude` CLI; clear the nested-session
    # guard so this works even when launched from Claude Code.
    from .config import CLAUDE_NESTED_GUARD_VARS

    for _v in CLAUDE_NESTED_GUARD_VARS:
        os.environ.pop(_v, None)

    from .agent_sdk import run_agent

    try:
        run_agent(prompt, max_turns=max_turns)
    except RuntimeError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\nInterrupted.", err=True)
        sys.exit(130)


if __name__ == "__main__":
    cli()
