"""Hot cache — kill the "where were we?" lag.

At run end a one-page ``atlas/projects/<id>/_hot.md`` is regenerated from the
snapshot trail (zero-LLM — it reuses the Decision Card already stored). It is
a *cache* (overwritten every run), distinct from *history* (snapshots,
append-only). Next session, Claude reads the ``hot://<id>`` resource first.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .. import config
from ..sandbox import validate_project_name


def _hot_path(project: str) -> Path:
    return config.atlas_path() / "projects" / validate_project_name(project) / "_hot.md"


def write_hot(project: str) -> Path | None:
    """Regenerate the hot cache from snapshots. No-op (None) if there is no
    history yet. Best-effort: callers guard so a run never fails on this."""
    from .snapshots import list_snapshots, load_snapshot

    snaps = list_snapshots(project)
    if not snaps:
        return None
    last = snaps[-1]
    snap = load_snapshot(project, last["id"]) or {}
    card = snap.get("decision_card") or {}
    state = snap.get("state", {})
    head_status = (state.get("next_action") or state.get("verdict")
                   or "in-progress")
    branches = sorted({s.get("branch", "main") for s in snaps})
    recent = ", ".join(f"{s['id']}:{s.get('stage', '?')}" for s in snaps[-5:])
    body = "\n".join([
        f"## Hot context — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        "",
        f"**Current head:** snap {last['id']} "
        f"({last.get('stage', '?')}, {head_status})",
        f"**Summary:** {card.get('summary') or '—'}",
        f"**Open questions:** "
        f"{'; '.join(card.get('open_questions') or []) or '—'}",
        f"**Directive for next:** {card.get('directive_for_next') or '—'}",
        f"**Recently touched:** {recent}",
        f"**Live branches:** {', '.join(branches)}",
        "",
    ])
    dest = _hot_path(project)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body)
    return dest


def read_hot(project: str) -> str:
    p = _hot_path(project)
    return p.read_text() if p.exists() else f"(no hot cache for '{project}' yet)"
