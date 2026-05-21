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


# --- Workstream G — write-protocol helpers (dedup gate + reconciler) -------

# Score above which an ADD is treated as a likely duplicate and proposed
# as an UPDATE / LINK instead. BM25 is unbounded but title-overlap on a
# small Atlas typically lands ~0.3 (1 matched term) → ~1.5 (4 terms);
# 0.75 picks up clear matches and stays quiet on single-token coincidences.
# The gate is advisory, not blocking — false positives are cheap (the
# agent re-submits unchanged); false negatives are what we care about.
_PROPOSE_DUP_SCORE = 0.75


def _propose(write_json: str) -> str:
    from ..core.recall import recall
    from ..sandbox import sanitize_atlas_writes

    try:
        w = json.loads(write_json) if isinstance(write_json, str) else write_json
    except json.JSONDecodeError as e:
        return f"Bad write_json: {e}"
    if not isinstance(w, dict):
        return "write_json must be a JSON object."
    # Run the same sandbox the real write would — surfaces "would have been
    # rejected" *before* the agent commits to it.
    cleaned = sanitize_atlas_writes([w], config.atlas_path())
    if not cleaned:
        return (f"Rejected (sandbox): proposed write to "
                f"{w.get('path', '?')} would not pass.")
    pw = cleaned[0]
    if pw.action and pw.action != "ADD":
        return (f"ok ({pw.action}): not a new page — submit through "
                f"hx_submit's atlas_writes when ready.")
    refs = recall(config.atlas_path(),
                  pw.title + " " + " ".join(pw.aliases or []),
                  k=3)
    near = [r for r in refs if r["score"] >= _PROPOSE_DUP_SCORE]
    if not near:
        return (f"ok: no near duplicates for '{pw.title}' "
                f"({len(refs)} loose match(es)). Submit the ADD through "
                "hx_submit's atlas_writes.")
    lines = [f"DEDUP: '{pw.title}' looks close to existing page(s):"]
    for r in near:
        lines.append(f"  {r['id']} [{r['tier']}] {r['title']} · "
                     f"score {r['score']} — {r['summary']}")
    lines.append(
        "Consider switching action to UPDATE (refine existing), SUPERSEDE "
        "(replace), or LINK (add a related_to edge) instead of ADD. If you "
        "still believe this is genuinely new, re-submit with a clearer "
        "title / aliases.")
    return "\n".join(lines)


def _reconcile() -> str:
    from ..core.atlas import iter_pages
    from ..core.atlas_index import build
    from ..core.lint import lint

    root = config.atlas_path()
    issues = lint(root)
    # Promotion proposals: active pages with ≥3 inbound edges could be
    # canonicalized. Cheap signal, advisory only. We get in-degree from the
    # SQLite edge index and the tier from the page's frontmatter so we
    # don't touch the index schema.
    promos: list[dict] = []
    try:
        con = build(root)
        try:
            indeg: dict[str, int] = {}
            for _src, dst in con.execute("SELECT src, dst FROM edges"):
                indeg[dst] = indeg.get(dst, 0) + 1
        finally:
            con.close()
        for r in iter_pages(root):
            if r.meta.tier == "active" and indeg.get(r.id, 0) >= 3:
                promos.append({"id": r.id, "title": r.title,
                               "in_degree": indeg[r.id],
                               "last_verified_at":
                                   r.meta.last_verified_at or "(unknown)"})
    except Exception as e:  # noqa: BLE001
        promos = [{"error": str(e)}]
    by_kind: dict[str, list[dict]] = {}
    for i in issues:
        by_kind.setdefault(i["kind"], []).append(i)
    out: list[str] = []
    out.append(f"Reconcile: {len(issues)} issue(s) across "
               f"{len(by_kind)} kind(s); {len(promos)} promotion candidate(s).")
    for kind, items in sorted(by_kind.items()):
        out.append(f"\n[{kind}] ({len(items)})")
        for i in items[:10]:
            tag = (i.get("page") or i.get("id") or
                   ", ".join(i.get("pages", [])) or i.get("file", "?"))
            out.append(f"  - {tag} → {i['suggestion']}")
        if len(items) > 10:
            out.append(f"  … and {len(items) - 10} more")
    if promos and "error" not in promos[0]:
        out.append("\n[promotion-candidate] (advisory)")
        for p in promos[:10]:
            out.append(f"  - {p['id']} ({p['title']}) — in_degree="
                       f"{p['in_degree']}, last_verified_at={p['last_verified_at']}")
            out.append("    consider hx_atlas_promote(... , 'canonical')")
        if len(promos) > 10:
            out.append(f"  … and {len(promos) - 10} more")
    return "\n".join(out)


@mcp.tool()
def hx_atlas_propose(write_json: str) -> str:
    """Dedup gate (spec §G) for a proposed atlas write before ADD.

    Takes one atlas write as JSON (the same shape ``hx_submit``'s
    ``atlas_writes`` accepts: path / title / content / summary / action /
    because / spec_refs / provenance / ...). Returns a structured proposal
    the agent should read BEFORE persisting an ADD:

      - if action != ADD, returns ``ok: write through hx_submit``;
      - else runs ``recall(title)`` against the active Atlas, and either
        returns ``no near duplicates → write through hx_submit`` or lists
        the near matches with a suggestion to switch action to UPDATE /
        SUPERSEDE / LINK.

    This tool does NOT write — that's still ``hx_submit``. It's the
    pre-flight the agent runs to avoid duplicate concepts piling up."""
    return _propose(write_json)


@mcp.tool()
def hx_atlas_reconcile() -> str:
    """Periodic Atlas reconciliation sweep (spec §G).

    Runs lint, then for every ``stale`` / ``orphan`` / ``unaliased`` /
    ``orphan-by-policy`` / ``missing-page`` / ``contradiction`` /
    ``orphan-community`` / ``stale-report`` issue suggests a concrete next
    action. Also surfaces any pages whose tier might be promotable
    (high in-degree + ``active`` + recently verified). Read-only — the
    agent is expected to follow up with hx_atlas_put / hx_atlas_promote /
    hx_atlas_save as appropriate."""
    return _reconcile()


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


@mcp.resource("thread://{project}/{name}")
def thread_resource(project: str, name: str) -> str:
    """A project thread's current state (Workstream E).

    ``name`` is one of: hypothesis · data · spec · plan · design ·
    code-org · glossary. Returns the page's frontmatter + body verbatim;
    use ``thread-at://`` for a bi-temporal read at a specific snapshot."""
    from ..core import threads

    try:
        t = threads.load_thread(config.atlas_path(), project, name)
    except threads.ThreadError as e:
        return f"(invalid thread: {e})"
    if t is None:
        return f"(no thread '{name}' for project '{project}')"
    return t.to_text()


@mcp.resource("thread-at://{project}/{name}/{snap_id}")
def thread_at_resource(project: str, name: str, snap_id: str) -> str:
    """Bi-temporal read of a project thread *at* snapshot ``snap_id``
    (Graphiti's snapshot-time model). Returns the thread truncated to the
    section for that snapshot, or the prelude if the snapshot didn't
    touch the thread."""
    from ..core import threads

    try:
        t = threads.read_at(config.atlas_path(), project, name, snap_id)
    except threads.ThreadError as e:
        return f"(invalid thread: {e})"
    if t is None:
        return f"(no thread '{name}' for project '{project}')"
    return t.to_text()


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
    """Drive the pipeline — you are the model (no MCP sampling)."""
    tgt = folder or "<project folder>"
    return (
        "Run the research pipeline. Helix has no model of its own — YOU "
        "(this agent) are the intelligence for every stage, via the tool "
        "loop:\n\n"
        f"1. hx_step(folder={tgt!r}) — initializes the run (reads "
        "question.md) and returns the FIRST stage's SYSTEM + USER prompt, "
        "plus a stage name and pending_token. Or hx_start for the guided "
        "wizard.\n"
        "2. Read that prompt and reason as if you were that agent. Produce "
        "ONLY the JSON its output contract specifies.\n"
        "3. hx_submit(folder, stage, result_json=<your JSON>, "
        "pending_token) — Helix maps it, writes the Atlas, snapshots, runs "
        "the gate, and returns the NEXT stage's prompt (deterministic "
        "stages run server-side; you won't see them).\n"
        "4. Repeat 2–3 until the reply is a run summary instead of another "
        "'NEEDS MODEL' prompt.\n\n"
        "Gates: by default each gate asks you via elicitation; pass "
        "autonomy_until (a stage name or 'END') to auto-proceed. Observe "
        "with hx_run_status / hx_run_events; every stage is snapshotted and "
        "resumable. If interrupted, just call hx_step(folder) again."
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


def _missing_client_caps(ctx: Context, needs: tuple[str, ...]) -> str | None:
    """Return an actionable error if the connected client can't service the
    server→client callbacks a gated tool needs, else ``None``.

    Helix is agent-driven (no sampling); the only callback is *elicitation*
    (gates / confirmations). A client that doesn't advertise it (or a stale
    / standalone ``helix mcp`` process with no interactive client attached)
    would fail the first gate with a raw protocol error after a run had
    already been registered. We check up front so the failure is legible and
    nothing is started.
    """
    from mcp.types import ClientCapabilities, ElicitationCapability

    probes = {
        "elicitation": ClientCapabilities(elicitation=ElicitationCapability()),
    }
    missing = [
        n for n in needs
        if not ctx.session.check_client_capability(probes[n])
    ]
    if not missing:
        return None
    return (
        "Error: this MCP client cannot run the Helix pipeline — it does not "
        f"support MCP {' + '.join(missing)}. Helix asks you at each gate "
        "through elicitation, so the client that launched the helix MCP "
        "server must provide it. Make sure the server is connected to an "
        "interactive client (e.g. Claude Code) and not a stale or standalone "
        "`helix mcp` process, then try again. No run was started; nothing "
        "was lost."
    )


async def _drive(
    ctx: Context, fn, *args, needs: tuple[str, ...] = ("elicitation",)
) -> str:
    """Run a blocking pipeline call in a worker thread with the client IO
    bound, so gate elicitation routes back to ``ctx``.

    Pre-flights ``needs`` so a client lacking elicitation fails fast with
    guidance rather than mid-run with an opaque error."""
    import anyio

    from ..io import use
    from .client_io import McpClientIO

    gap = _missing_client_caps(ctx, needs)
    if gap:
        return gap

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




# --- Agent-driven drive surface (no sampling: the client agent is the model)

def _step_payload(folder: str, project: str, o, token: str) -> str:
    from .. import runs

    # Workstream D: include the previous stage's report (if it exists) as a
    # clickable file:// link so the researcher can review/annotate before
    # the next stage advances. Resolves to the active workspace's atlas.
    report_link = ""
    try:
        prev_html = (config.atlas_path() / "projects" / project / "reports"
                     / f"{o.stage}.html")
        # The OPENING report for this stage doesn't exist yet (this is the
        # NEXT one's prompt); but if we just came from a prior stage the
        # latest snapshot's report does exist. Surface anything we find.
        latest = sorted((config.atlas_path() / "projects" / project /
                         "reports").glob("*.html"), key=lambda p: p.stat().st_mtime,
                        reverse=True) if (config.atlas_path() / "projects"
                        / project / "reports").exists() else []
        if latest:
            report_link = f"\nLatest report: file://{latest[0].resolve()}"
    except Exception:  # noqa: BLE001 - decorative only
        report_link = ""

    # Workstream C: surface any hx_ask clarifications captured against
    # this project so the next stage prompt sees them as inline context.
    clar_block = ""
    try:
        pend = runs.get_pending(project) or {}
        clar = pend.get("clarifications") or []
    except Exception:  # noqa: BLE001
        clar = []
    if clar:
        items = "\n".join(f"- Q: {c.get('q','')}\n  A: {c.get('a','')}"
                          for c in clar[-10:])
        clar_block = (f"\n\n----- RECENT CLARIFICATIONS (via hx_ask) "
                      f"-----\n{items}")
    return (
        f"NEEDS MODEL — project '{project}', stage '{o.stage}'.\n"
        "You are the model for this stage. Read SYSTEM + USER below, then "
        "reply with ONLY the JSON the stage's output contract requires, via:\n"
        f"  hx_submit(folder={folder!r}, stage={o.stage!r}, "
        f"result_json=<your JSON>, pending_token={token!r})"
        f"{report_link}\n"
        f"\n----- SYSTEM -----\n{o.system}\n----- USER -----\n{o.user}"
        f"{clar_block}"
    )


def _handle_outcome(folder, project, run_id, o, branch, autonomy="") -> str:
    from .. import runs

    if o.kind == "needs_model":
        import secrets

        token = secrets.token_hex(4)
        # Workstream C: carry hx_ask clarifications forward across stage
        # advances. The OLD pending step (if any) accumulated answers
        # while the agent walked the previous stage; preserve them so the
        # NEW stage's prompt can show them as context.
        prev = runs.get_pending(project) or {}
        clar = list(prev.get("clarifications") or [])
        runs.set_pending(project, {
            "run_id": run_id, "stage": o.stage, "resume_from": o.last_id,
            "branch": branch, "system": o.system, "user": o.user,
            "token": token, "autonomy": autonomy,
            "clarifications": clar,
        })
        runs.record_event(run_id, o.stage, o.state.tokens_used, kind="await")
        return _step_payload(folder, project, o, token)
    runs.clear_pending(project)
    runs.finish_run(run_id, o.state)
    tail = ("" if o.kind == "done"
            else "\n  (resumable — call hx_step to continue)")
    return f"[{run_id}] " + _summary(o.state) + tail


def _step_blocking(
    io, folder: str, question: str, autonomy_until: str = "",
    project_name: str = "",
) -> str:
    from .. import runs
    from ..config import ModelConfig, atlas_path, token_cap
    from ..core.atlas import Atlas
    from ..core.plan import Plan
    from ..core.snapshots import mint_snapshot
    from ..core.state import PipelineState
    from ..io import gate_asker
    from ..orchestrator import loop

    fp = Path(folder).expanduser()
    if not fp.is_dir():
        return f"Error: not a directory: {folder}"
    with config.use_root(fp.resolve()):
        project = project_name.strip() or fp.stem
        pend = runs.get_pending(project)
        if pend:  # idempotent: re-show the outstanding step
            o = loop.StepOutcome(
                "needs_model", None, pend["resume_from"],
                stage=pend["stage"], system=pend["system"], user=pend["user"])
            return _step_payload(folder, project, o, pend["token"])

        q = question.strip()
        if not q and (fp / "question.md").is_file():
            q = (fp / "question.md").read_text().strip()
        plan = Plan.from_autonomy_until(autonomy_until)
        state = PipelineState(
            project_name=project, research_question=q,
            input_folder=str(fp.resolve()),
            token_cap=token_cap(), call_cap=ModelConfig().call_cap())
        run_id = runs.start_run(project, plan)
        init = mint_snapshot(
            state, project, stage="start",
            report={"decision": "initialized", "rationale": q or "-"},
            parent=None, branch="main")
        o = loop.step_begin(
            state, Atlas(atlas_path()), ModelConfig(),
            last_id=init["id"], ask=gate_asker(io), plan=plan, branch="main")
        return _handle_outcome(folder, project, run_id, o, "main",
                               autonomy=autonomy_until)


def _submit_blocking(
    io, folder: str, stage: str, result_json: str, pending_token: str
) -> str:
    from .. import runs
    from ..config import ModelConfig, atlas_path
    from ..core.atlas import Atlas
    from ..core.plan import Plan
    from ..io import gate_asker
    from ..orchestrator import loop

    fp = Path(folder).expanduser()
    if not fp.is_dir():
        return f"Error: not a directory: {folder}"
    with config.use_root(fp.resolve()):
        project = fp.stem
        pend = runs.get_pending(project)
        if pend is None:
            return (f"No pending step for '{project}'. Call hx_step(folder) "
                    "to (re)start or continue the pipeline.")
        if pending_token != pend["token"]:
            return ("Stale pending_token — the run moved on or restarted. "
                    "Call hx_step(folder) to get the current step.")
        if stage != pend["stage"]:
            return (f"Wrong stage: the pending step is '{pend['stage']}', "
                    f"not '{stage}'. Submit that one.")
        autonomy = pend.get("autonomy", "")
        try:
            o = loop.submit_stage(
                project, pend["resume_from"], stage, result_json,
                Atlas(atlas_path()), ModelConfig(),
                ask=gate_asker(io), plan=Plan.from_autonomy_until(autonomy),
                branch=pend["branch"])
        except ValueError as e:
            return f"Error: {e}"
        return _handle_outcome(folder, project, pend["run_id"], o,
                               pend["branch"], autonomy=autonomy)


def _resume_blocking(
    io, project: str, snapshot: str, at: str, branch: str, folder: str
) -> str:
    from .. import runs
    from ..config import ModelConfig, atlas_path
    from ..core.atlas import Atlas
    from ..core.plan import Plan
    from ..core.snapshots import load_snapshot
    from ..io import gate_asker
    from ..orchestrator import loop

    # Pass the project folder to resume against the same self-rooted store
    # the run wrote to. Omitted = fall back to HELIX_HOME / cwd (correct when
    # the server is already rooted at the project, e.g. a per-project
    # .mcp.json).
    with config.use_root(Path(folder).expanduser() if folder.strip() else None):
        snap = load_snapshot(project, snapshot)
        if snap is None:
            return f"Error: no snapshot {snapshot} for project '{project}'"
        start_at = at or snap.get("stage") or "scout"
        if start_at == "start":
            start_at = "scout"
        run_id = runs.start_run(project, Plan.from_autonomy_until(""))
        try:
            o = loop.resume_step(
                project, str(snapshot), start_at,
                Atlas(atlas_path()), ModelConfig(),
                ask=gate_asker(io), plan=Plan.from_autonomy_until(""),
                branch=branch)
        except ValueError as e:
            runs.abort_run(run_id, str(e))
            return f"Error: {e}"
        return _handle_outcome(folder or project, project, run_id, o, branch)


def _start_wizard(io, folder: str) -> str:
    from ..core.transitions import stages
    from ..io import ask_choice, ask_text

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

    src = (folder or "").strip()
    if not src:
        fd = _ask(ask_text("Source folder to ingest (path)", "folder"))
        if not fd:
            return "Setup cancelled."
        src = str(fd.get("folder", "")).strip()
    fp = Path(src or "sources").expanduser()
    if fp.exists() and not fp.is_dir():
        return (f"{fp} is a file, not a folder. Give a directory of "
                "sources, or drop files into atlas/inbox/ and run "
                "hx_atlas_ingest.")
    # No dead-end on missing sources: create the folder and tell the user
    # exactly how to add material, rather than erroring out or starting a
    # run that would only fail at Scout.
    fp.mkdir(parents=True, exist_ok=True)
    if not any(p.is_file() for p in fp.rglob("*")):
        return (
            f"{fp.resolve()} has no source material yet — the folder is "
            "ready for you. Add papers / PDFs / code / data there, or drop "
            "them into atlas/inbox/ and run hx_atlas_ingest, then say "
            '"start helix" again. No run was started; nothing was lost.'
        )

    # Hand off to the agent-driven initializer: it self-roots at fp, creates
    # the run, and returns the first stage's prompt for the client agent.
    return (f"Started '{name}' ({choice}).\n\n"
            + _step_blocking(io, str(fp), description, autonomy_until,
                             project_name=name))


@mcp.tool()
async def run_pipeline(
    folder: str, ctx: Context, question: str = "", autonomy_until: str = ""
) -> str:
    """Start a pipeline run on a folder and return the first stage's prompt
    for YOU (the client agent) to answer — Helix is driven through the tool
    loop, not server-side sampling. Equivalent to hx_step on a fresh run.
    ``autonomy_until`` (a stage name or "END") auto-proceeds gates instead of
    eliciting. Continue with hx_submit / hx_step."""
    return await _drive(
        ctx, _step_blocking, folder, question, autonomy_until,
        needs=("elicitation",))


@mcp.tool()
async def hx_step(
    ctx: Context, folder: str, question: str = "", autonomy_until: str = ""
) -> str:
    """Advance the pipeline for ``folder`` to the next point that needs the
    model, and return that stage's SYSTEM + USER prompt for YOU (the client
    agent) to answer. First call initializes the run (reads question.md if
    ``question`` is empty). Deterministic stages run server-side with no
    round-trip; ``autonomy_until`` auto-proceeds gates. When the run finishes
    it says so. No sampling — you are the model: produce the JSON and call
    hx_submit."""
    return await _drive(
        ctx, _step_blocking, folder, question, autonomy_until,
        needs=("elicitation",))


@mcp.tool()
async def hx_submit(
    ctx: Context, folder: str, stage: str, result_json: str,
    pending_token: str,
) -> str:
    """Submit your JSON answer for the pending stage. Helix maps it, writes
    the Atlas, snapshots, runs the gate, transitions, and returns the next
    hx_step prompt (or the final summary). Guarded by ``pending_token``."""
    return await _drive(
        ctx, _submit_blocking, folder, stage, result_json, pending_token,
        needs=("elicitation",))


@mcp.tool()
async def resume_pipeline(
    project: str, snapshot: str, ctx: Context, at: str = "",
    branch: str = "main", folder: str = "",
) -> str:
    """Resume a project from a snapshot, re-entering at any stage. Pass
    ``folder`` (the project's source folder) to resume against the same
    self-rooted store the run wrote to, regardless of the server's cwd.
    Gated."""
    return await _drive(
        ctx, _resume_blocking, project, snapshot, at, branch, folder)


@mcp.tool()
async def hx_start(ctx: Context, folder: str = "") -> str:
    """Guided project setup: elicits name / description / control mode (and
    the source folder if not given), then starts the run and returns the
    first stage's prompt for you to answer (agent-driven; no sampling)."""
    return await _drive(ctx, _start_wizard, folder, needs=("elicitation",))


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
    # Elicitation here is conditional (only canonical/published) and there is
    # no sampling, so skip the blanket pre-flight; the confirm path is
    # covered by client_io's defensive translation.
    return await _drive(ctx, _promote_blocking, ids, tier, needs=())


@mcp.tool()
def snapshot_revert(project: str, snapshot: str) -> str:
    """Restore a snapshot's artifacts into the project dir. Gated."""
    return agent_iface.snapshot_revert_text(project, snapshot)


@mcp.tool()
def hx_report_send_back(folder: str, project: str, stage: str) -> str:
    """Read the (researcher-modified) stage HTML report from
    ``<atlas>/projects/<project>/reports/<stage>.html`` and convert the
    embedded annotations into structured feedback for the stage re-run
    (Workstream D · spec §D round-trip).

    Returns the rendered feedback string the agent will see on re-entry,
    plus a small summary. The actual re-run is triggered by the agent
    calling ``hx_step`` / ``hx_submit`` after this — this tool only
    extracts and persists the feedback."""
    from ..core import reports
    from .. import runs

    with config.use_root(Path(folder).expanduser() if folder.strip() else None):
        path = config.atlas_path() / "projects" / project / "reports" / f"{stage}.html"
        if not path.exists():
            return f"No report at {path}"
        rt = reports.parse_round_trip(path.read_text())
        feedback = reports.build_send_back_feedback(rt)
        if not feedback.strip():
            return (f"Report at {path} carries no unresolved or marked "
                    "annotations; nothing to send back.")
        # Stash the feedback in the pending step (if any) so the next
        # hx_step/hx_submit cycle picks it up; else keep it for the agent.
        pend = runs.get_pending(project) or {}
        sendbacks = pend.setdefault("sendback", [])
        sendbacks.append({"stage": stage, "feedback": feedback})
        runs.set_pending(project, pend) if pend.get("stage") else None
        summary = (
            f"Extracted {len(rt.send_back) + len(rt.kept) + len(rt.rejected) + len(rt.comments)} "
            f"annotation(s) ({len(rt.send_back)} send-back · {len(rt.kept)} kept "
            f"· {len(rt.rejected)} rejected · {len(rt.comments)} researcher).\n"
            f"Feedback for re-run of '{stage}':\n\n{feedback}"
        )
        return summary


# --- Workstream B + F.2/F.3 — spec / question_check / clarify -------------


def _format_findings(qc) -> str:
    if qc.ok:
        return ""
    by_kind: dict[str, list] = {}
    for f in qc.findings:
        by_kind.setdefault(f.kind, []).append(f)
    out: list[str] = [f"{len(qc.findings)} finding(s):"]
    for kind, items in sorted(by_kind.items()):
        out.append(f"\n[{kind}] ({len(items)})")
        for f in items[:10]:
            out.append(f"  - {f.where} → {f.suggestion}")
        if len(items) > 10:
            out.append(f"  … and {len(items) - 10} more")
    return "\n".join(out)


def _question_check(folder: str = "", project: str = "") -> str:
    from ..core import spec as _spec
    from ..sandbox import SandboxError

    fp = Path(folder).expanduser() if folder.strip() else None
    with config.use_root(fp):
        proj = project.strip() or (fp.stem if fp else "")
        if not proj:
            return ("hx_question_check needs a project (or a folder so the "
                    "project name can be inferred from its stem).")
        try:
            qc = _spec.question_check(config.atlas_path(), proj, source_folder=fp)
        except SandboxError as e:
            return f"Rejected (sandbox): {e}"
        if qc.ok:
            return f"Spec for '{proj}' is ready (no blockers)."
        return _format_findings(qc)


@mcp.tool()
def hx_question_check(folder: str = "", project: str = "") -> str:
    """Validate the project spec (spec §B + F.2/F.3).

    Resolves ``projects/<project>/spec.md`` inside the active Atlas; if
    no spec yet, falls back to ``<folder>/question.md`` (the
    researcher's brief). Returns a structured findings list:
    missing FINER axis · missing PICOT axis · missing GQM field ·
    unresolved [NEEDS CLARIFICATION] / TODO / @open-question markers ·
    gate.status != 'ready'. Empty output means the spec is ready —
    Scout may submit."""
    return _question_check(folder, project)


def _clarify(io, folder: str, project: str) -> str:
    """Walk every unresolved clarification marker, ask the researcher
    via elicitation, and patch the spec in place with a SEARCH/REPLACE.

    Returns a summary of patched / skipped / remaining markers. The
    spec advances only when no markers remain."""
    from ..core import spec as _spec
    from ..io import ask_text
    from ..sandbox import SandboxError

    fp = Path(folder).expanduser() if folder.strip() else None
    with config.use_root(fp):
        proj = project.strip() or (fp.stem if fp else "")
        if not proj:
            return "hx_clarify needs a project (or a folder)."
        try:
            sp = _spec.load_spec(config.atlas_path(), proj)
        except SandboxError as e:
            return f"Rejected (sandbox): {e}"
        if sp is None:
            return f"No spec at projects/{proj}/spec.md to clarify."
        markers = _spec.scan_clarifications(sp.body)
        if not markers:
            return f"No unresolved markers in projects/{proj}/spec.md."
        patched, skipped = 0, 0
        for marker in markers:
            r = io.elicit(ask_text(
                f"Clarify: {marker}", "answer"))
            if r.action != "accept":
                skipped += 1
                continue
            answer = str((r.data or {}).get("answer", "")).strip()
            if not answer:
                skipped += 1
                continue
            new_body, ok = _spec.apply_clarification(sp.body, marker, answer)
            if ok:
                sp.body = new_body
                patched += 1
            else:
                skipped += 1
        if patched:
            _spec.save_spec(config.atlas_path(), proj, sp)
        remaining = len(_spec.scan_clarifications(sp.body))
        return (f"Clarify pass: {patched} patched · {skipped} skipped · "
                f"{remaining} remaining.")


# --- Workstream C — interactive `hx_ask` ----------------------------------


def _ask(io, prompt: str, schema_json: str = "", project: str = "",
         field_name: str = "answer") -> str:
    """Drive one elicitation; record the Q&A onto the project's pending
    step so the next stage sees it. Cheap and synchronous from the
    server's perspective — the elicitation is the client's roundtrip."""
    from .. import runs
    from ..io import ElicitRequest, ask_text

    if schema_json.strip():
        try:
            schema = json.loads(schema_json)
        except json.JSONDecodeError as e:
            return f"Bad schema_json: {e}"
        if not isinstance(schema, dict):
            return "schema_json must be a JSON object."
        req = ElicitRequest(prompt, schema)
    else:
        req = ask_text(prompt, field_name)
    r = io.elicit(req)
    if r.action != "accept":
        return f"hx_ask: {r.action} (no answer recorded)."
    data = dict(r.data or {})
    answer = data.get(field_name) if field_name in data else data
    # Persist into the project's pending step so the next stage prompt
    # surfaces the clarification.
    proj = project.strip()
    if proj:
        try:
            pend = runs.get_pending(proj) or {}
        except Exception:  # noqa: BLE001
            pend = {}
        clarifications = list(pend.get("clarifications") or [])
        clarifications.append({
            "q": prompt, "a": answer,
            "at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat(),
        })
        pend["clarifications"] = clarifications
        if pend.get("stage"):
            runs.set_pending(proj, pend)
    return f"hx_ask answered: {answer!r}"


@mcp.tool()
async def hx_ask(
    ctx: Context, prompt: str, schema_json: str = "",
    project: str = "", field_name: str = "answer",
) -> str:
    """Ask the researcher a structured question via MCP elicitation
    (Workstream C). Plain question by default; pass a JSON schema (any
    flat object accepted by MCP elicitation) to drive a multi-choice /
    multi-select / confirm prompt. Recording: if ``project`` names an
    active project with a pending step, the Q&A is appended to its
    ``clarifications`` list so the next stage prompt sees it."""
    return await _drive(
        ctx, _ask, prompt, schema_json, project, field_name,
        needs=("elicitation",))


@mcp.tool()
async def hx_clarify(ctx: Context, folder: str = "", project: str = "") -> str:
    """Walk the spec's unresolved clarification markers one at a time
    (spec §F.3). Asks the researcher (elicitation), patches the spec in
    place via anchored SEARCH/REPLACE, returns the remaining count. The
    spec advances only when zero markers remain."""
    return await _drive(ctx, _clarify, folder, project, needs=("elicitation",))


@mcp.tool()
def hx_constitution_init(folder: str = "") -> str:
    """Ensure the workspace has a Constitution (spec §F.1) and return it.

    The Constitution captures the project's non-negotiables — language /
    framework / testing / architectural style / definition of done — and
    is injected into every agent's system prompt. Idempotent: writes a
    default template only if no file exists; existing edits are preserved.
    Pass ``folder`` (a project root) to anchor the workspace discovery."""
    from ..core import constitution

    with config.use_root(Path(folder).expanduser() if folder.strip() else None):
        path = constitution.ensure_constitution(config.workspace_root())
        body = constitution.load_constitution()
        return f"Constitution at {path}\n\n{body}"


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
