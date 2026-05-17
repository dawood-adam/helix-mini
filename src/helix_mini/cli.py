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
def run(
    folders: tuple[str, ...],
    lightspeed: bool,
    question: str,
    sandbox: bool,
    local: bool,
    local_recommended: bool,
    model_size: str | None,
) -> None:
    """Run Forge pipeline on one or more folders."""
    # Resolve model config based on flags
    if local or local_recommended:
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
        if not has_api_key():
            click.echo("No API key found. Run 'helix-mini setup' first.")
            click.echo("Or use --local to run entirely with a local Qwen model.")
            sys.exit(1)
        model_config = ModelConfig.load(lightspeed=lightspeed)
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
        click.echo(f"Pipeline failed: {type(e).__name__}: {e}", err=True)
        if logging.getLogger().level == logging.DEBUG:
            import traceback

            # Print only the chain of frame summaries (file/line/function),
            # not local variable values, to avoid leaking API keys or
            # other secrets that may be in scope.
            click.echo("Traceback (most recent call last):", err=True)
            for line in traceback.format_tb(e.__traceback__):
                click.echo(line, err=True, nl=False)
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


if __name__ == "__main__":
    cli()
