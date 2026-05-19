"""helix-mcp — the stdio MCP server. The one drive surface.

- **Tools**: thin wrappers over the pure helpers in ``agent_iface``.
- **Resources**: Atlas pages + snapshots, read-only, by URI.
- **Gated tools** run the FULL pipeline through the calling client: model
  calls go out as MCP *sampling*, every HITL gate as standardized
  *elicitation* (`helix.io.gate_asker`). One seam, used uniformly.

Fail-closed by construction: only this curated tool set exists, and the
host (Claude Code) prompts the user before any state-changing tool.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

from .. import agent_iface, config
from ..core.snapshots import load_snapshot

mcp = FastMCP("helix")


# --- Read tools -------------------------------------------------------------


@mcp.tool()
def hx_atlas_recall(query: str, k: int = 8, mode: str = "auto") -> str:
    """Auto-routing Atlas search (lexical/semantic/graph/community). Returns
    REFS only — call hx_atlas_get for a body. mode: auto|lexical|semantic|
    graph|community."""
    from ..core.recall import recall

    refs = recall(config.atlas_path(), query, k=max(1, min(k, 25)), mode=mode)
    if not refs:
        return f"No Atlas matches for: {query}"
    return "\n".join(
        f"[{r['mode']}] {r['id']} ({r['tier']}) — {r['title']}: "
        f"{r['summary']}  ·{r['score']}" for r in refs)


@mcp.tool()
def hx_atlas_get(id: str) -> str:
    """Fetch one Atlas page's body (capped) by id 'atlas:..:..' or path."""
    from ..core.recall import get

    p = get(config.atlas_path(), id)
    if p is None:
        return f"No Atlas page: {id}"
    return f"# {p['title']}  [{p['tier']}]  ({p['id']})\n\n{p['body']}"


@mcp.tool()
def atlas_status() -> str:
    """Atlas page count + known projects."""
    return agent_iface.atlas_status_text()


@mcp.tool()
def hx_atlas_ingest(path: str = "") -> str:
    """Process new/changed files dropped in atlas/inbox/ (idempotent via a
    sha256 manifest). No path = whole inbox; path = one file. Each becomes a
    `type: source` page and its original moves to atlas/raw/."""
    from ..core.atlas import Atlas
    from ..core.ingest import ingest_inbox

    res = ingest_inbox(Atlas(config.atlas_path()), only=path.strip() or None)
    if res["new"] == 0:
        return f"Inbox: nothing new ({res['skipped']} already ingested)."
    return (f"Ingested {res['new']} source(s): {', '.join(res['ingested'])} "
            f"→ sources/ (originals moved to raw/).")


@mcp.tool()
def hx_atlas_neighbors(page: str, k: int = 1) -> str:
    """k-hop neighbours of an Atlas page over the link graph (by id
    'atlas:..:..' or path 'concepts/x.md'). Returns refs, not bodies."""
    from ..core.atlas_index import neighbors

    res = neighbors(config.atlas_path(), page, max(1, min(k, 5)))
    if not res:
        return f"No neighbours for '{page}' within {k} hop(s)."
    return "\n".join(
        f"{n['hops']}h  {n['id']} [{n['tier']}] {n['title']}" for n in res)


@mcp.tool()
def hx_atlas_lint() -> str:
    """Atlas health check: orphan / contradiction / stale / missing-page /
    unaliased / orphan-community, each with a suggested fix."""
    from ..core.lint import lint

    issues = lint(config.atlas_path())
    if not issues:
        return "Atlas lint: clean."
    out = [f"{len(issues)} issue(s):"]
    for i in issues:
        ctx = i.get("page") or i.get("id") or ", ".join(i.get("pages", []))
        out.append(f"- [{i['kind']}] {ctx} → {i['suggestion']}")
    return "\n".join(out)


def _put(path, title, content, summary, type_, tier, aliases_csv) -> str:
    from ..core.atlas import Atlas
    from ..sandbox import sanitize_atlas_writes

    raw = {"path": path, "title": title, "content": content,
           "summary": summary or title}
    if type_:
        raw["type"] = type_
    if tier:
        raw["tier"] = tier
    if aliases_csv.strip():
        raw["aliases"] = [a.strip() for a in aliases_csv.split(",") if a.strip()]
    writes = sanitize_atlas_writes([raw], config.atlas_path())
    if not writes:
        return f"Rejected (sandbox): {path}"
    Atlas(config.atlas_path()).write(writes, "put | manual page")
    from ..core.atlas import _page_id

    return f"Wrote {_page_id(path)} ({path})."


@mcp.tool()
def hx_atlas_put(path: str, title: str, content: str, summary: str = "",
                 type: str = "", tier: str = "", aliases_csv: str = "") -> str:
    """Create/update an Atlas page (merges if the path exists; the creation
    clock is preserved). path must start with sources/concepts/entities/
    projects."""
    return _put(path, title, content, summary, type, tier, aliases_csv)


@mcp.tool()
def hx_atlas_save(title: str, content: str, type: str = "comparison",
                  project: str = "", tier: str = "active") -> str:
    """File an LLM synthesis/comparison answer back into the Atlas as a
    proper page."""
    from ..core.ingest import _slug

    slug = _slug(title)
    path = (f"projects/{_slug(project)}/syntheses/{slug}.md"
            if project.strip() else f"concepts/{slug}.md")
    return _put(path, title, content, f"synthesis: {title}", type, tier, "")


@mcp.tool()
def decision_log(project: str) -> str:
    """The stage-by-stage decision log for a project."""
    return agent_iface.decision_log_text(project)


@mcp.tool()
def snapshot_list(project: str) -> str:
    """List a project's snapshots (git-log style)."""
    return agent_iface.snapshot_list_text(project)


@mcp.tool()
def snapshot_show(project: str, snap_id: str) -> str:
    """Show one snapshot's key state."""
    return agent_iface.snapshot_show_text(project, snap_id)


@mcp.tool()
def snapshot_diff(project: str, a: str, b: str) -> str:
    """Diff two snapshots."""
    return agent_iface.snapshot_diff_text(project, a, b)


@mcp.tool()
def snapshot_timeline(project: str) -> str:
    """Mermaid gitGraph of the snapshot DAG."""
    return agent_iface.snapshot_timeline_text(project)


@mcp.tool()
def hx_snap_branch(project: str, snapshot: str, name: str) -> str:
    """Name a branch ref at a snapshot. (Continue it later with
    resume_pipeline(..., branch=name).)"""
    from ..core.snapshots import make_branch

    ok = make_branch(project, snapshot, name)
    return (f"Branch '{name}' → snap-{snapshot}." if ok
            else f"No snap-{snapshot} for '{project}'.")


@mcp.tool()
def hx_snap_freeze(project: str, snapshot: str, tag: str) -> str:
    """Tag a snapshot immutable for publication."""
    from ..core.snapshots import freeze

    ok = freeze(project, snapshot, tag)
    return (f"Frozen snap-{snapshot} as '{tag}'." if ok
            else f"No snap-{snapshot} for '{project}'.")


@mcp.tool()
def hx_snap_fork(project: str, name: str) -> str:
    """Export the project's full snapshot history as a portable, reproducible
    bundle under forks/."""
    from ..core.snapshots import fork

    dest = fork(project, name)
    return f"Bundle: {dest} ({dest.stat().st_size} bytes)."


# --- Resources --------------------------------------------------------------


@mcp.resource("atlas://{path}")
def atlas_page(path: str) -> str:
    """An Atlas page by repo-relative path (traversal-safe)."""
    root = config.atlas_path().resolve()
    fp = (root / path).resolve()
    if not fp.is_relative_to(root) or not fp.is_file():
        return f"(no atlas page: {path})"
    return fp.read_text()


@mcp.resource("snapshot://{project}/{snap_id}")
def snapshot_resource(project: str, snap_id: str) -> str:
    """A snapshot's metadata as JSON."""
    snap = load_snapshot(project, snap_id)
    return json.dumps(snap, indent=2, default=str) if snap else f"(no snapshot {snap_id})"


@mcp.resource("hot://{project}")
def hot_resource(project: str) -> str:
    """The project's hot cache — read this first on "where were we?"."""
    from ..core.hot import read_hot

    return read_hot(project)


# --- Prompts: canonical workflows (the substitute for v3's intent tools) ----


@mcp.prompt()
def helix_ingest() -> str:
    """Frictionless capture workflow."""
    return (
        "Ingest sources into the Atlas:\n"
        "1. Files were dropped in atlas/inbox/ (PDF/md/txt/...).\n"
        "2. Call hx_atlas_ingest() for the whole inbox, or "
        "hx_atlas_ingest(path='inbox/<file>') for one. It is idempotent "
        "(sha256 manifest); new files become `type: source` pages and the "
        "originals move to atlas/raw/.\n"
        "3. Then hx_atlas_recall('<topic>') to see what's now known and "
        "hx_atlas_lint to catch dangling links from the new material."
    )


@mcp.prompt()
def helix_run(folder: str = "") -> str:
    """Start a pipeline run, four control modes."""
    tgt = f" on {folder}" if folder else ""
    return (
        f"Run the research pipeline{tgt}:\n"
        "- Guided: call hx_start — it elicits name / description / control "
        "mode, then runs.\n"
        "- Direct: run_pipeline(folder, autonomy_until=''). '' = pause and "
        "ask at every gate (elicitation); a stage name = auto until there; "
        "'END' = fully autonomous.\n"
        "- Mid-run: steer with hx_run_plan_set; observe with hx_run_status / "
        "hx_run_events. Each stage emits a Decision Card + a snapshot; a "
        "declined gate pauses resumably."
    )


@mcp.prompt()
def helix_lint() -> str:
    """Atlas hygiene sweep."""
    return (
        "Health-check the Atlas:\n"
        "1. hx_atlas_lint — orphan / contradiction / stale / missing-page / "
        "unaliased / orphan-community, each with a fix.\n"
        "2. Per issue: draft a missing page (hx_atlas_put or hx_atlas_save), "
        "re-verify a stale page, add aliases, link/archive an orphan, or "
        "write a synthesis page for an orphan community.\n"
        "3. Re-run hx_atlas_lint to confirm it's clean."
    )


@mcp.prompt()
def helix_freeze() -> str:
    """Freeze-and-fork-for-publication checklist."""
    return (
        "Publish a reproducible bundle:\n"
        "1. hx_atlas_lint and resolve blockers.\n"
        "2. hx_atlas_promote(ids, 'published') — confirms via elicitation.\n"
        "3. hx_snap_freeze(project, snapshot, tag) to mark it immutable.\n"
        "4. hx_snap_fork(project, name) — exports forks/<name>.tar.gz "
        "(snaps + objects + index + refs). Share that one file."
    )


@mcp.prompt()
def helix_resume(project: str = "") -> str:
    """"Where were we?" recovery."""
    p = project or "<project>"
    return (
        "Resume a project:\n"
        f"1. Read the hot cache first — resource hot://{p} (current head, "
        "open question, working hypothesis, live branches).\n"
        f"2. hx_run_status('{p}') for the last run; snapshot_timeline('{p}') "
        "for the DAG.\n"
        f"3. resume_pipeline('{p}', <snapshot>, branch=...) — re-enter at any "
        "stage; use a new branch to explore an alternative without touching "
        "main."
    )


# --- Gated tools: drive the full pipeline through the client ----------------


async def _drive(ctx: Context, fn, *args) -> str:
    """Run a blocking pipeline call in a worker thread with the standardized
    client IO bound, so sampling + elicitation both route back to ``ctx``."""
    import anyio

    from ..io import use
    from .client_io import McpClientIO

    io = McpClientIO(ctx)

    def work() -> str:
        with use(io):
            return fn(io, *args)

    return await anyio.to_thread.run_sync(work)


def _summary(r) -> str:
    status = "error" if r.error else (
        "paused" if r.next_action.startswith("paused") else "done")
    out = (f"{r.project_name}: {status} "
           f"(stages={len(r.completed_stages)}, verdict={r.verdict or '-'})")
    if r.error:
        out += f"\n  error: {r.error}"
    if r.next_action.startswith("paused"):
        out += f"\n  {r.next_action} — resume from the latest snapshot"
    return out


def _run_blocking(io, folder: str, question: str, autonomy_until: str) -> str:
    from .. import app, runs
    from ..config import ModelConfig
    from ..core.plan import Plan
    from ..io import gate_asker

    fp = Path(folder).expanduser()
    if not fp.is_dir():
        return f"Error: not a directory: {folder}"
    plan = Plan.from_autonomy_until(autonomy_until)
    run_id = runs.start_run(fp.stem, plan)
    r = app.run(
        fp.resolve(), model_config=ModelConfig(),
        research_question=question, plan=plan,
        ask=gate_asker(io), interactive=True,
        progress_fn=lambda s, p, t: runs.record_event(run_id, s, t),
    )
    runs.finish_run(run_id, r)
    return f"[{run_id}] " + _summary(r)


def _resume_blocking(io, project: str, snapshot: str, at: str, branch: str) -> str:
    from .. import app, runs
    from ..config import ModelConfig
    from ..core.plan import Plan
    from ..io import gate_asker

    plan = Plan.from_autonomy_until("")
    run_id = runs.start_run(project, plan)
    try:
        r = app.resume(
            project, snapshot, model_config=ModelConfig(),
            start_at=at or None, branch=branch, plan=plan,
            ask=gate_asker(io), interactive=True,
            progress_fn=lambda s, p, t: runs.record_event(run_id, s, t),
        )
    except ValueError as e:
        runs.abort_run(run_id, str(e))
        return f"Error: {e}"
    runs.finish_run(run_id, r)
    return f"[{run_id}] " + _summary(r)


def _start_wizard(io, folder: str) -> str:
    from .. import app, runs
    from ..config import ModelConfig
    from ..core.plan import Plan
    from ..core.transitions import stages
    from ..io import ask_choice, ask_text, gate_asker

    def _ask(req):
        r = io.elicit(req)
        return r.data if r.action == "accept" else None

    nm = _ask(ask_text(
        "What should we call this project? (lowercase, digits, hyphens)",
        "name", pattern="[a-z0-9-]+"))
    if not nm:
        return "Setup cancelled."
    name = str(nm.get("name", "")).strip()

    ds = _ask(ask_text(
        "One-sentence research question / description?", "description")) or {}
    description = str(ds.get("description", "")).strip()

    md = _ask(ask_choice("How should it run?", [
        "step-by-step (ask at every gate)",
        "auto up to a stage, then ask",
        "fully autonomous"], "mode"))
    if not md:
        return "Setup cancelled."
    choice = str(md.get("mode", ""))
    if "autonomous" in choice:
        autonomy_until = "END"
    elif "auto up to" in choice:
        st = _ask(ask_choice(
            "Auto-proceed until which stage?", list(stages()), "stage"))
        if not st:
            return "Setup cancelled."
        autonomy_until = str(st.get("stage", ""))
    else:
        autonomy_until = ""

    src = folder
    if not src:
        fd = _ask(ask_text("Source folder to ingest (path)", "folder"))
        if not fd:
            return "Setup cancelled."
        src = str(fd.get("folder", ""))
    fp = Path(src).expanduser()
    if not fp.is_dir():
        return f"Error: not a directory: {src}"

    plan = Plan.from_autonomy_until(autonomy_until)
    run_id = runs.start_run(name, plan)
    r = app.run(
        fp.resolve(), model_config=ModelConfig(), project_name=name,
        research_question=description, plan=plan,
        ask=gate_asker(io), interactive=True,
        progress_fn=lambda s, p, t: runs.record_event(run_id, s, t),
    )
    runs.finish_run(run_id, r)
    return f"[{run_id}] started '{name}' ({choice}) — " + _summary(r)


@mcp.tool()
async def run_pipeline(
    folder: str, ctx: Context, question: str = "", autonomy_until: str = ""
) -> str:
    """Run the pipeline on a folder. Default: pause at every gate and ask you
    (via elicitation). Set autonomy_until to a stage name, or "END", to
    auto-proceed. Gated — the host confirms before this runs."""
    return await _drive(ctx, _run_blocking, folder, question, autonomy_until)


@mcp.tool()
async def resume_pipeline(
    project: str, snapshot: str, ctx: Context, at: str = "", branch: str = "main"
) -> str:
    """Resume a project from a snapshot, re-entering at any stage. Gated."""
    return await _drive(ctx, _resume_blocking, project, snapshot, at, branch)


@mcp.tool()
async def hx_start(ctx: Context, folder: str = "") -> str:
    """Guided project setup: elicits name / description / control mode (and
    the source folder if not given), builds the Plan, then runs the pipeline.
    Gated — the host confirms before this runs."""
    return await _drive(ctx, _start_wizard, folder)


def _promote_blocking(io, ids: str, tier: str) -> str:
    from ..core.atlas import TIERS, Atlas
    from ..core.recall import get
    from ..io import ask_confirm

    if tier not in TIERS:
        return f"Bad tier '{tier}'. One of: {', '.join(TIERS)}."
    wanted = [x.strip() for x in ids.replace(",", " ").split() if x.strip()]
    if not wanted:
        return "No page ids/paths given."
    if tier in ("canonical", "published"):
        r = io.elicit(ask_confirm(
            f"Promote {len(wanted)} page(s) to '{tier}'? {', '.join(wanted)}"))
        if r.action != "accept" or not (r.data or {}).get("proceed"):
            return "Promotion cancelled."
    root = config.atlas_path()
    atlas = Atlas(root)
    done, missing = [], []
    for ref in wanted:
        pg = get(root, ref)
        if pg and atlas.retier(pg["path"], tier):
            done.append(pg["id"])
        else:
            missing.append(ref)
    msg = f"Promoted {len(done)} → {tier}: {', '.join(done) or '-'}"
    return msg + (f"\n  not found: {', '.join(missing)}" if missing else "")


@mcp.tool()
async def hx_atlas_promote(ids: str, tier: str, ctx: Context) -> str:
    """Bump page tier(s) (comma/space-separated ids or paths). Promoting to
    canonical/published asks you to confirm first (elicitation)."""
    return await _drive(ctx, _promote_blocking, ids, tier)


@mcp.tool()
def snapshot_revert(project: str, snapshot: str) -> str:
    """Restore a snapshot's artifacts into the project dir. Gated."""
    return agent_iface.snapshot_revert_text(project, snapshot)


@mcp.tool()
def hx_run_status(project: str) -> str:
    """Status of the latest run for a project (survives a server restart)."""
    from .. import runs

    rec = runs.get_record(project=project)
    if rec is None:
        return f"No runs recorded for '{project}'."
    line = (f"[{rec.run_id}] {rec.status} stage={rec.current_stage or '-'} "
            f"tokens~{rec.tokens_used} snap={rec.last_snapshot or '-'}")
    return line + (f"\n  note: {rec.note}" if rec.note else "")


@mcp.tool()
def hx_run_events(project: str, since: int = 0) -> str:
    """Tail the latest run's transition events since sequence ``since``."""
    from .. import runs

    evs = runs.tail_events(project=project, since=since)
    if not evs:
        return f"No events for '{project}' since seq {since}."
    return "\n".join(
        f"{e['seq']}: {e['stage']} (tokens~{e['tokens']})" for e in evs)


@mcp.tool()
def hx_run_plan_set(project: str, autonomy_until: str = "", steps_json: str = "") -> str:
    """Steer the active run's Plan (effective at the next gate). Provide
    ``autonomy_until`` ('' = pure HITL, a stage name, or 'END') OR
    ``steps_json``: a JSON list of {agent, directive?, autonomy, n?}."""
    from .. import runs

    steps = None
    if steps_json.strip():
        try:
            steps = json.loads(steps_json)
        except json.JSONDecodeError as e:
            return f"Bad steps_json: {e}"
    elif not autonomy_until.strip():
        return "Provide autonomy_until or steps_json."
    return runs.set_plan(
        project=project,
        autonomy_until=None if steps else autonomy_until,
        steps=steps,
    )


def main() -> None:
    """Entry point for the ``helix-mcp`` console script / ``helix mcp``."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
