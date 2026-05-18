"""`helix` CLI — run the pipeline, drive it with a HITL terminal, browse and
resume the git-style snapshot history, or hand the wheel to a Claude agent."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import click

from . import app, config
from .core.atlas import Atlas
from .core.gates import GateDecision, GateReport
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
4. Only then run `helix run <that folder>` (or `.` for this folder).

## Driving the pipeline

`helix run <folder>` pauses at a gate after **every** stage. Relay each gate
report to me and wait for my decision: proceed / send the run back to ANY
earlier stage with feedback / stop. A snapshot is minted at every stage and
every send-back. Use `--autonomous-until <stage>` or `--auto` only if I ask.

## History & resume (git-style)

- `helix snapshots list|show|diff|diagram <project>`
- `helix snapshots resume <project> <id> [--at STAGE] [--branch NAME]`
- `helix snapshots revert <project> <id>` restores that snapshot's artifacts.

## Atlas (persistent wiki, compounds across projects)

`helix status`, `helix atlas search <query>`, `helix log <project>`.
"""


def _progress(stage: str, project: str, cost: float) -> None:
    click.echo(f"  [{project}] {stage} (${cost:.4f})")


def _resolve_model_config(
    *, lightspeed, local, local_recommended, model_size, cli_engine, cli_model
):
    from .config import ModelConfig

    if cli_engine:
        from .llm_cli import CLIEngineError, get_engine

        try:
            eng = get_engine(cli_engine)
        except CLIEngineError as e:
            raise click.ClickException(str(e))
        if not eng.available():
            raise click.ClickException(
                f"CLI engine '{cli_engine}' not on PATH (looked for '{eng.bin}')."
            )
        return ModelConfig.cli(cli_engine, native_model=cli_model), f"cli:{cli_engine}"
    if local or local_recommended:
        size = model_size or "medium"
        if local:
            return ModelConfig.local(size), f"local ({size})"
        if not config.has_api_key():
            raise click.ClickException(
                "--local-recommended needs an API key. Run 'helix setup' or use --local."
            )
        return ModelConfig.local_recommended(size, lightspeed), f"local-recommended"
    mc = ModelConfig.default(lightspeed=lightspeed)
    if mc is None:
        raise click.ClickException(
            "No Claude OAuth token or API key. Run 'claude setup-token', "
            "'helix setup', or use --local."
        )
    label = "claude-subscription" if mc.model.startswith("cli/") else (
        "lightspeed" if lightspeed else "normal"
    )
    return mc, label


def _engine_options(func):
    opts = [
        click.option("--lightspeed", is_flag=True, help="Auto-gates + cheapest model"),
        click.option("--local", is_flag=True, help="All stages local via Ollama/Qwen"),
        click.option("--local-recommended", "local_recommended", is_flag=True,
                     help="Simple stages local, critical stages via cloud API"),
        click.option("--model-size", type=click.Choice(["small", "medium", "large"]),
                     default=None, help="Qwen size for local inference"),
        click.option("--cli", "cli_engine", default=None, metavar="ENGINE",
                     help="Pilot the pipeline through an LLM CLI (e.g. 'claude')"),
        click.option("--cli-model", "cli_model", default=None, metavar="MODEL",
                     help="Engine-native model for --cli"),
        click.option("--engine", type=click.Choice(["loop", "sdk"]), default="loop",
                     show_default=True, help="Orchestrator: plain loop or LangGraph"),
        click.option("--auto", is_flag=True, help="Fully autonomous (no HITL gates)"),
        click.option("--autonomous-until", "autonomous_until", default="",
                     metavar="STAGE", help="Auto-proceed gates before STAGE, then ask"),
    ]
    for opt in reversed(opts):
        func = opt(func)
    return func


def _autonomy(auto: bool, autonomous_until: str) -> str:
    return "END" if auto else (autonomous_until or "")


def _terminal_ask(report: GateReport) -> GateDecision:
    """Interactive HITL: proceed / send back to any stage / stop."""
    click.echo(f"\n── gate after {report.stage} ──", err=True)
    click.echo(f"  decision : {report.decision}", err=True)
    click.echo(f"  rationale: {report.rationale}", err=True)
    if report.note:
        click.echo(f"  note     : {report.note}", err=True)
    for k, v in report.summary.items():
        click.echo(f"  {k:9}: {v}", err=True)

    if report.stage == "cost-ceiling":
        return GateDecision(
            "stop" if not click.confirm(
                "Cost ceiling reached. Continue (doubles the ceiling)?",
                default=False) else "proceed"
        )

    choice = click.prompt(
        "[p]roceed / [g]o back to a stage / [s]top",
        type=click.Choice(["p", "g", "s"]), default="p", show_default=True,
    )
    if choice == "s":
        return GateDecision("stop")
    if choice == "p":
        return GateDecision("proceed")
    target = click.prompt(
        f"Send back to which stage? ({', '.join(stages())})",
        type=click.Choice(list(stages())),
    )
    note = click.prompt("Feedback for that stage", default="")
    return GateDecision("goto", target, note or None)


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
@click.argument("folders", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("-q", "--question", default="", help="Research question")
@_engine_options
def run(folders, question, lightspeed, local, local_recommended, model_size,
        cli_engine, cli_model, engine, auto, autonomous_until):
    """Run the pipeline on one or more folders (HITL by default)."""
    mc, label = _resolve_model_config(
        lightspeed=lightspeed, local=local, local_recommended=local_recommended,
        model_size=model_size, cli_engine=cli_engine, cli_model=cli_model,
    )
    interactive = sys.stdin.isatty()
    autonomy = _autonomy(auto, autonomous_until)
    for f in folders:
        fp = Path(f).resolve()
        click.echo(f"helix — {fp.name} (mode={label}, engine={engine}, "
                   f"autonomy={autonomy or 'full-HITL'})")
        try:
            r = app.run(
                fp, model_config=mc, autonomy_until=autonomy,
                research_question=question,
                ask=_terminal_ask if interactive else None,
                interactive=interactive, progress_fn=_progress, engine=engine,
            )
        except Exception as e:
            click.echo(f"Pipeline failed: {type(e).__name__}: {e}", err=True)
            sys.exit(1)
        status = "error" if r.error else (
            "paused" if r.next_action == "paused-cost" else "done")
        click.echo(f"  {r.project_name}: {status} "
                   f"(stages={len(r.completed_stages)}, cost=${r.cost_so_far:.4f})")
        if r.error:
            click.echo(f"    error: {r.error}", err=True)
        if r.next_action == "paused-cost":
            click.echo("    resume: helix snapshots resume "
                       f"{r.project_name} <id> --auto", err=True)


@cli.command()
def status():
    """Show Atlas status and known projects."""
    root = config.atlas_path()
    if not root.exists():
        click.echo("No Atlas yet. Run 'helix run <folder>' first.")
        return
    a = Atlas(root)
    pages = sum(1 for ln in a.read_all_summaries().splitlines() if ln.startswith("- ["))
    click.echo(f"Atlas: {root}\nPages: {pages}")
    pdir = root / "projects"
    if pdir.exists():
        names = sorted(d.name for d in pdir.iterdir() if d.is_dir())
        if names:
            click.echo(f"Projects: {', '.join(names)}")


@cli.command("log")
@click.argument("project")
def show_log(project):
    """Print the decision log for a project."""
    from .core.decisions import render_decisions_md

    p = config.atlas_path() / "projects" / project / ".decisions.json"
    if not p.exists():
        click.echo(f"No decision log for project: {project}")
        return
    click.echo(render_decisions_md(p))


@cli.group()
def atlas():
    """Atlas wiki commands."""


@atlas.command("search")
@click.argument("query")
def atlas_search(query):
    """Keyword search over the Atlas."""
    root = config.atlas_path()
    if not root.exists():
        click.echo("No Atlas yet.")
        return
    pages = Atlas(root).read(query)
    if not pages:
        click.echo(f"No results for: {query}")
        return
    for pg in pages:
        click.echo(f"\n--- {pg.title} ({pg.path}) ---")
        click.echo(pg.content[:500] + ("\n..." if len(pg.content) > 500 else ""))


@cli.group()
def snapshots():
    """Git-style snapshot history: list/show/diff/diagram/branch/revert/resume."""


@snapshots.command("list")
@click.argument("project")
def snap_list(project):
    """List snapshots (like `git log`)."""
    from .core.snapshots import list_snapshots

    snaps = list_snapshots(project)
    if not snaps:
        click.echo(f"No snapshots for '{project}'.")
        return
    for m in snaps:
        click.echo(f"snap-{m['id']:<3} {m.get('branch','main'):<8} "
                   f"{m.get('stage',''):<15} parent={m.get('parent') or '-'} "
                   f"{m.get('ts','')}")


@snapshots.command("show")
@click.argument("project")
@click.argument("snap_id")
def snap_show(project, snap_id):
    """Show one snapshot's key state (like `git show`)."""
    from .core.snapshots import load_snapshot, snapshot_summary

    snap = load_snapshot(project, snap_id)
    if not snap:
        raise click.ClickException(f"No snap-{snap_id} for '{project}'.")
    for k, v in snapshot_summary(snap).items():
        click.echo(f"  {k:11}: {v}")


@snapshots.command("diff")
@click.argument("project")
@click.argument("a")
@click.argument("b")
def snap_diff(project, a, b):
    """Diff two snapshots (like `git diff A B`)."""
    from .core.snapshots import diff_snapshots, load_snapshot

    sa, sb = load_snapshot(project, a), load_snapshot(project, b)
    if not sa or not sb:
        raise click.ClickException(f"Need both snap-{a} and snap-{b}.")
    changes = diff_snapshots(sa, sb)
    if not changes:
        click.echo(f"snap-{a} -> snap-{b}: no tracked differences")
        return
    click.echo(f"snap-{a} -> snap-{b}:")
    for f, (o, n) in changes.items():
        click.echo(f"  {f}: {o!r} -> {n!r}")


@snapshots.command("diagram")
@click.argument("project")
@click.option("--output", default=None, type=click.Path())
def snap_diagram(project, output):
    """Render the snapshot DAG as a Mermaid gitGraph."""
    from .core.snapshots import snapshot_gitgraph

    mermaid = snapshot_gitgraph(project)
    dest = Path(output) if output else (
        config.atlas_path() / "projects" / project / "timeline.md")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(f"# {project} — snapshot timeline\n\n{mermaid}\n")
    click.echo(mermaid)
    click.echo(f"\nWrote {dest}", err=True)


@snapshots.command("revert")
@click.argument("project")
@click.argument("snap_id")
def snap_revert(project, snap_id):
    """Restore a snapshot's artifacts into the project dir (git checkout)."""
    from .core.snapshots import restore_artifacts

    dest = config.atlas_path() / "projects" / project / "artifacts"
    written = restore_artifacts(project, snap_id, dest)
    click.echo(f"Restored {len(written)} file(s) from snap-{snap_id} to {dest}")
    click.echo(f"Continue with: helix snapshots resume {project} {snap_id}")


@snapshots.command("resume")
@click.argument("project")
@click.argument("snap_id")
@click.option("--at", "start_at", default=None, metavar="STAGE")
@click.option("--branch", default="main", help="Branch label for the new run")
@_engine_options
def snap_resume(project, snap_id, start_at, branch, lightspeed, local,
                local_recommended, model_size, cli_engine, cli_model, engine,
                auto, autonomous_until):
    """Resume the pipeline from a snapshot (re-enter at any stage)."""
    mc, label = _resolve_model_config(
        lightspeed=lightspeed, local=local, local_recommended=local_recommended,
        model_size=model_size, cli_engine=cli_engine, cli_model=cli_model,
    )
    interactive = sys.stdin.isatty()
    click.echo(f"Resuming '{project}' from snap-{snap_id} "
               f"(branch={branch}, mode={label}, engine={engine})")
    try:
        r = app.resume(
            project, snap_id, model_config=mc, start_at=start_at,
            autonomy_until=_autonomy(auto, autonomous_until), branch=branch,
            ask=_terminal_ask if interactive else None, interactive=interactive,
            progress_fn=_progress, engine=engine,
        )
    except ValueError as e:
        raise click.ClickException(str(e))
    status = "error" if r.error else (
        "paused" if r.next_action == "paused-cost" else "done")
    click.echo(f"  {project}: {status} "
               f"(stages={len(r.completed_stages)}, cost=${r.cost_so_far:.4f})")


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
        f"[limits]\ncost_cap = {config.COST_CAP_DEFAULT}\n"
        f"call_cap = {config.CALL_CAP_DEFAULT}\n"
    )
    click.echo(f"Created: {d}/")
    click.echo(f"  1. Edit {name}/question.md")
    click.echo(f"  2. Add source files to {name}/")
    click.echo(f"  3. cd {name} && helix run . ")


@cli.command()
def setup():
    """Interactive setup — pick a provider, enter and validate an API key."""
    names = list(config.PROVIDERS)
    for i, n in enumerate(names, 1):
        click.echo(f"  {i}. {n}")
    provider = names[click.prompt("Provider", type=click.IntRange(1, len(names)),
                                  default=1) - 1]
    env_var = config.PROVIDERS[provider]["env_var"]
    key = click.prompt(f"Enter {env_var}", hide_input=True)
    click.echo("Validating...")
    try:
        ok = config.validate_api_key(provider, key)
    except RuntimeError as e:
        raise click.ClickException(str(e))
    if not ok and not click.confirm("Could not validate. Save anyway?", default=False):
        return
    env_path = config.helix_dir() / ".env"
    lines = [
        ln for ln in (env_path.read_text().splitlines() if env_path.exists() else [])
        if not ln.startswith(f"{env_var}=")
    ]
    lines.append(f"{env_var}={key}")
    env_path.write_text("\n".join(lines) + "\n")
    config.ensure_helix_toml()
    click.echo(f"Saved to {env_path}. Try: helix run ./your-folder")


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("prompt", nargs=-1)
@click.option("--max-turns", default=30, show_default=True)
def agent(prompt, max_turns):
    """Drive helix conversationally via a Claude agent (no quotes needed)."""
    for v in config.CLAUDE_NESTED_GUARD_VARS:
        os.environ.pop(v, None)
    from .agent_iface import run_agent_session

    try:
        run_agent_session(" ".join(prompt) or None, max_turns=max_turns)
    except RuntimeError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\nInterrupted.", err=True)
        sys.exit(130)


if __name__ == "__main__":
    cli()
