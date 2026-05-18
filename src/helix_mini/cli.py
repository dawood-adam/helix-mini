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


def _project_dir(project: str) -> Path:
    return HELIX_HOME / "atlas" / "projects" / project


def _resolve_model_config(
    *,
    lightspeed: bool,
    local: bool = False,
    local_recommended: bool = False,
    model_size: str | None = None,
    cli_engine: str | None = None,
    cli_model: str | None = None,
) -> tuple[ModelConfig, str]:
    """Resolve (ModelConfig, mode_label) from engine flags.

    Shared by `run` and `snapshots resume`. Raises click.ClickException on an
    unrecoverable misconfiguration (missing engine binary, no auth, etc.).
    """
    if cli_engine:
        from .llm_cli import CLIEngineError, get_engine

        try:
            eng = get_engine(cli_engine)
        except CLIEngineError as e:
            raise click.ClickException(str(e))
        if not eng.available():
            raise click.ClickException(
                f"CLI engine '{cli_engine}' is not on PATH (looked for "
                f"'{eng.bin}'). Install it first."
            )
        return (
            ModelConfig.cli(cli_engine, native_model=cli_model),
            f"cli:{cli_engine}" + (f":{cli_model}" if cli_model else ""),
        )
    if local or local_recommended:
        size = model_size or "medium"
        if local:
            return ModelConfig.local(size), f"local ({QWEN_SIZES[size]})"
        if not has_api_key():
            raise click.ClickException(
                "--local-recommended needs an API key for critical stages. "
                "Run 'helix-mini setup' first, or use --local."
            )
        return (
            ModelConfig.local_recommended(size, lightspeed=lightspeed),
            f"local-recommended ({QWEN_SIZES[size]} + cloud)",
        )

    model_config = ModelConfig.default(lightspeed=lightspeed)
    if model_config is None:
        raise click.ClickException(
            "No Claude OAuth token or API key found. Run 'claude setup-token' "
            "and export CLAUDE_CODE_OAUTH_TOKEN to use your Claude "
            "subscription, or 'helix-mini setup' for an API key, or --local."
        )
    if model_config.model.startswith("cli/"):
        from .llm_cli import get_engine

        if not get_engine("claude").available():
            raise click.ClickException(
                "Claude CLI not found on PATH — reinstall Claude Code."
            )
        return model_config, "claude-subscription" + (
            " lightspeed" if lightspeed else ""
        )
    return model_config, ("lightspeed" if lightspeed else "normal")


def _engine_options(func):
    """Shared engine-selection options for `run` and `snapshots resume`.

    Keeps the two commands' engine flags identical from one definition.
    """
    opts = [
        click.option("--lightspeed", is_flag=True,
                     help="Auto-gates + cheapest model"),
        click.option("--local", is_flag=True,
                     help="Run all stages locally using Qwen via Ollama "
                     "(no API key needed)"),
        click.option("--local-recommended", "local_recommended", is_flag=True,
                     help="Run simple stages locally (Qwen), critical stages "
                     "via cloud API"),
        click.option("--model-size",
                     type=click.Choice(list(QWEN_SIZES.keys()),
                                       case_sensitive=False),
                     default=None,
                     help="Qwen model size for local inference "
                     "(small/medium/large)"),
        click.option("--cli", "cli_engine", default=None, metavar="ENGINE",
                     help="Pilot the pipeline through an LLM CLI (e.g. "
                     "'claude'). No API key needed; the CLI handles its own "
                     "auth. Define more in config.toml."),
        click.option("--cli-model", "cli_model", default=None, metavar="MODEL",
                     help="Engine-native model for --cli (e.g. 'opus', "
                     "'sonnet', 'haiku')."),
        click.option("--max-iterations", default=3, show_default=True,
                     metavar="N",
                     help="Max builder<->critic_results refine loops (0 "
                     "disables the loop). Auto under --lightspeed; otherwise "
                     "prompts ship/iterate/abandon."),
    ]
    for opt in reversed(opts):
        func = opt(func)
    return func


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
@click.option("-q", "--question", default="", help="Research question to guide analysis")
@click.option("--sandbox", is_flag=True, help="Run inside a Docker sandbox")
@_engine_options
def run(
    folders: tuple[str, ...],
    question: str,
    sandbox: bool,
    lightspeed: bool,
    local: bool,
    local_recommended: bool,
    model_size: str | None,
    cli_engine: str | None,
    cli_model: str | None,
    max_iterations: int,
) -> None:
    """Run Forge pipeline on one or more folders."""
    model_config, mode_label = _resolve_model_config(
        lightspeed=lightspeed, local=local, local_recommended=local_recommended,
        model_size=model_size, cli_engine=cli_engine, cli_model=cli_model,
    )

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
            max_iterations=max_iterations,
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


@cli.group()
def snapshots() -> None:
    """Git-style snapshot history: list / show / diff / diagram / resume."""


def _require_snap(project: str, num: int) -> dict:
    from .pipeline.snapshots import find_snapshot, load_snapshot

    p = find_snapshot(_project_dir(project), num)
    if p is None:
        raise click.ClickException(
            f"No snap-{num} for project '{project}'. "
            f"Try: helix-mini snapshots list {project}"
        )
    return load_snapshot(p)


@snapshots.command("list")
@click.argument("project")
def snap_list(project: str) -> None:
    """List a project's snapshots (like `git log`)."""
    from .pipeline.snapshots import (
        _snap_num, list_snapshots, load_snapshot, snapshot_summary,
    )

    snaps = list_snapshots(_project_dir(project))
    if not snaps:
        click.echo(f"No snapshots for '{project}'. Run the pipeline first.")
        return
    for p in snaps:
        s = snapshot_summary(load_snapshot(p))
        click.echo(
            f"snap-{_snap_num(p):<3} {s['timestamp']:<27} "
            f"{s['stage']:<15} ${s['cost']:.4f}  "
            f"verdict={s['verdict']}  iters={s['build_iterations']}"
            + ("  ERROR" if s["error"] else "")
        )


@snapshots.command("show")
@click.argument("project")
@click.argument("num", type=int)
def snap_show(project: str, num: int) -> None:
    """Show one snapshot's key state (like `git show`)."""
    snap = _require_snap(project, num)
    st = snap.get("state", {})
    click.echo(f"snap-{num}  stage={snap.get('stage')}  {snap.get('timestamp')}")
    click.echo(f"  cost_so_far     : ${float(st.get('cost_so_far', 0) or 0):.4f}")
    click.echo(f"  verdict         : {st.get('verdict') or '-'}")
    click.echo(f"  build_iterations: {st.get('build_iterations', 0)}")
    click.echo(f"  chosen_approach : {st.get('chosen_approach_id') or '-'}")
    click.echo(f"  plan            : {st.get('project_plan', {}).get('title', '-')}")
    click.echo(f"  candidates      : {len(st.get('candidate_approaches') or [])}")
    click.echo(f"  artifacts       : {len(st.get('code_artifacts') or [])}")
    click.echo(f"  results         : {len(st.get('experiment_results') or [])}")
    click.echo(f"  completed_stages: {', '.join(st.get('completed_stages') or []) or '-'}")
    if st.get("error"):
        click.echo(f"  error           : {st['error']}")


@snapshots.command("diff")
@click.argument("project")
@click.argument("a", type=int)
@click.argument("b", type=int)
def snap_diff(project: str, a: int, b: int) -> None:
    """Diff two snapshots' state (like `git diff A B`)."""
    from .pipeline.snapshots import diff_snapshots

    changes = diff_snapshots(_require_snap(project, a), _require_snap(project, b))
    if not changes:
        click.echo(f"snap-{a} -> snap-{b}: no tracked differences")
        return
    click.echo(f"snap-{a} -> snap-{b}:")
    for field, (old, new) in changes.items():
        click.echo(f"  {field}: {old!r} -> {new!r}")


@snapshots.command("diagram")
@click.argument("project")
@click.option("--output", "output", type=click.Path(), default=None,
              help="Write the Mermaid file here (default: the project dir)")
def snap_diagram(project: str, output: str | None) -> None:
    """Render the snapshot history as a Mermaid gitGraph."""
    from .pipeline.snapshots import (
        list_snapshots, load_snapshot, snapshot_gitgraph,
    )

    snaps = [load_snapshot(p) for p in list_snapshots(_project_dir(project))]
    mermaid = snapshot_gitgraph(snaps)
    dest = Path(output) if output else _project_dir(project) / "timeline.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(f"# {project} — snapshot timeline\n\n{mermaid}\n")
    click.echo(mermaid)
    click.echo(f"\nWrote {dest}", err=True)


@snapshots.command("resume")
@click.argument("project")
@click.argument("num", type=int)
@click.option("--at", "start_at", default=None, metavar="STAGE",
              help="Pipeline node to re-enter at (default: the snapshot's stage)")
@_engine_options
def snap_resume(
    project: str, num: int, start_at: str | None, lightspeed: bool,
    local: bool, local_recommended: bool, model_size: str | None,
    cli_engine: str | None, cli_model: str | None, max_iterations: int,
) -> None:
    """Resume the forge cycle from a snapshot, re-entering at a chosen stage."""
    snap = _require_snap(project, num)
    st = snap.get("state", {})
    stage = start_at or snap.get("stage") or st.get("current_stage") or "scout"

    model_config, mode_label = _resolve_model_config(
        lightspeed=lightspeed, local=local, local_recommended=local_recommended,
        model_size=model_size, cli_engine=cli_engine, cli_model=cli_model,
    )

    from .pipeline.runner import resume_project

    click.echo(
        f"Resuming '{project}' at '{stage}' from snap-{num} (mode={mode_label})"
    )
    try:
        result = resume_project(
            project, Atlas(HELIX_HOME / "atlas"), model_config,
            snapshot_state=st, start_at=stage, lightspeed=lightspeed,
            home=HELIX_HOME, progress_fn=_cli_progress,
            max_iterations=max_iterations,
        )
    except ValueError as e:
        raise click.ClickException(str(e))
    status = "error" if result.error else "done"
    click.echo(
        f"\n  {result.project_name}: {status} "
        f"(stages: {len(result.completed_stages)}, "
        f"cost: ${result.cost_so_far:.4f})"
    )
    if result.error:
        click.echo(f"    Error: {result.error}")


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


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("prompt", nargs=-1)
@click.option(
    "--max-turns", default=30, show_default=True,
    help="Max agent turns before the session stops",
)
def agent(prompt: tuple[str, ...], max_turns: int) -> None:
    """Drive helix-mini conversationally via a Claude agent.

    Just type your request after `agent` — no quotes needed:

      helix-mini agent search the atlas for cardiac modeling

    With no text, opens an interactive session. The agent can search the
    Atlas and (with confirmation) run the pipeline. Needs the optional
    extra: pip install 'helix-mini[agent]'. Auth: see the docs — set up a
    Claude subscription token or an API key first.
    """
    # The Agent SDK spawns its bundled `claude` CLI; clear the nested-session
    # guard so this works even when launched from Claude Code.
    from .config import CLAUDE_NESTED_GUARD_VARS

    for _v in CLAUDE_NESTED_GUARD_VARS:
        os.environ.pop(_v, None)

    from .agent_sdk import run_agent

    try:
        run_agent(" ".join(prompt) or None, max_turns=max_turns)
    except RuntimeError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\nInterrupted.", err=True)
        sys.exit(130)


if __name__ == "__main__":
    cli()
