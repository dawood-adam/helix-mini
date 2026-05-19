"""Read/run helper bodies for the helix-mcp tools.

Pure (no SDK dependency): the MCP server in ``helix.mcp`` wraps each of
these as a tool. Consent is owned by the MCP host (Claude Code) and the
curated tool surface, so there is no in-process permission gate here.
"""

from __future__ import annotations

import logging

from . import config
from .core.atlas import Atlas

log = logging.getLogger(__name__)


def atlas_status_text() -> str:
    root = config.atlas_path()
    if not root.exists():
        return "No Atlas yet — run the pipeline first."
    pages = sum(
        1 for ln in Atlas(root).read_all_summaries().splitlines()
        if ln.startswith("- [")
    )
    pdir = root / "projects"
    projects = sorted(d.name for d in pdir.iterdir() if d.is_dir()) if pdir.exists() else []
    return f"Atlas: {root}\nPages: {pages}\nProjects: {', '.join(projects) or '(none)'}"


def decision_log_text(project: str) -> str:
    from .core.decisions import render_decisions_md

    p = config.atlas_path() / "projects" / project / ".decisions.json"
    return render_decisions_md(p) if p.exists() else f"No decision log for: {project}"


def snapshot_list_text(project: str) -> str:
    from .core.snapshots import list_snapshots

    snaps = list_snapshots(project)
    if not snaps:
        return f"No snapshots for '{project}'."
    return "\n".join(
        f"snap-{m['id']} {m.get('branch','main')} {m.get('stage','')} "
        f"parent={m.get('parent') or '-'}"
        for m in snaps
    )


def snapshot_show_text(project: str, snap_id: str) -> str:
    from .core.snapshots import load_snapshot, snapshot_summary

    snap = load_snapshot(project, snap_id)
    if not snap:
        return f"No snap-{snap_id} for '{project}'."
    return "\n".join(f"{k}={v}" for k, v in snapshot_summary(snap).items())


def snapshot_diff_text(project: str, a: str, b: str) -> str:
    from .core.snapshots import diff_snapshots, load_snapshot

    sa, sb = load_snapshot(project, a), load_snapshot(project, b)
    if not sa or not sb:
        return f"Need both snap-{a} and snap-{b} for '{project}'."
    ch = diff_snapshots(sa, sb)
    if not ch:
        return f"snap-{a} -> snap-{b}: no tracked differences"
    return f"snap-{a} -> snap-{b}:\n" + "\n".join(
        f"  {k}: {o!r} -> {n!r}" for k, (o, n) in ch.items()
    )


def snapshot_timeline_text(project: str) -> str:
    from .core.snapshots import snapshot_gitgraph

    return snapshot_gitgraph(project)


def snapshot_revert_text(project: str, snapshot: str) -> str:
    from .core.snapshots import restore_artifacts

    dest = config.atlas_path() / "projects" / project / "artifacts"
    written = restore_artifacts(project, snapshot, dest)
    return f"Restored {len(written)} file(s) from snap-{snapshot} of '{project}'."
