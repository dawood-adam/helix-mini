"""Lightweight snapshot store for ForgeState."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .state import ForgeState


def mint_snapshot(state: ForgeState, project_dir: Path) -> Path:
    """Save a snapshot of the current state. Returns the snapshot path."""
    snap_dir = project_dir / ".snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(snap_dir.glob("snap-*.json"))
    next_num = len(existing) + 1

    snap_path = snap_dir / f"snap-{next_num}.json"
    snap_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": state.current_stage,
        "state": asdict(state),
    }
    snap_path.write_text(json.dumps(snap_data, indent=2, default=str))
    return snap_path


def load_snapshot(snap_path: Path) -> dict:
    """Load a snapshot from disk."""
    return json.loads(snap_path.read_text())


def _snap_num(path: Path) -> int:
    """Extract N from a ``snap-N.json`` path (0 if unparseable)."""
    try:
        return int(path.stem.split("-", 1)[1])
    except (IndexError, ValueError):
        return 0


def list_snapshots(project_dir: Path) -> list[Path]:
    """List all snapshots for a project, ordered by snapshot number."""
    snap_dir = project_dir / ".snapshots"
    if not snap_dir.exists():
        return []
    return sorted(snap_dir.glob("snap-*.json"), key=_snap_num)


def find_snapshot(project_dir: Path, num: int) -> Path | None:
    """Return the path to ``snap-<num>.json`` if it exists."""
    p = project_dir / ".snapshots" / f"snap-{num}.json"
    return p if p.exists() else None


def snapshot_summary(snap: dict) -> dict:
    """Compact, display-friendly view of one loaded snapshot."""
    st = snap.get("state", {})
    return {
        "stage": snap.get("stage") or st.get("current_stage", "?"),
        "timestamp": snap.get("timestamp", "?"),
        "cost": float(st.get("cost_so_far", 0.0) or 0.0),
        "build_iterations": st.get("build_iterations", 0),
        "verdict": st.get("verdict", "") or "-",
        "approaches": len(st.get("candidate_approaches", []) or []),
        "artifacts": len(st.get("code_artifacts", []) or []),
        "error": st.get("error"),
    }


# ForgeState fields worth showing in a human-readable diff (scalars/sizes).
_DIFF_FIELDS = (
    "current_stage", "verdict", "build_iterations", "cost_so_far",
    "chosen_approach_id", "next_action", "error",
)
_DIFF_LIST_FIELDS = (
    "candidate_approaches", "code_artifacts", "experiment_results",
    "critiques", "completed_stages", "sanity_check_flags",
)


def diff_snapshots(a: dict, b: dict) -> dict[str, tuple]:
    """Field-level diff of two snapshots' ForgeState. Returns {field: (old, new)}.

    Scalars are compared by value; list fields are compared by length so the
    output stays readable (git-status-style, not a full deep diff).
    """
    sa, sb = a.get("state", {}), b.get("state", {})
    out: dict[str, tuple] = {}
    for f in _DIFF_FIELDS:
        if sa.get(f) != sb.get(f):
            out[f] = (sa.get(f), sb.get(f))
    for f in _DIFF_LIST_FIELDS:
        la, lb = len(sa.get(f) or []), len(sb.get(f) or [])
        if la != lb:
            out[f] = (f"{la} items", f"{lb} items")
    return out


def snapshot_gitgraph(snaps: list[dict]) -> str:
    """Render snapshots as a standard Mermaid ``gitGraph`` (git-style history).

    Each snapshot is one commit, labelled ``snap-N <stage> $<cost>``; refine
    loops simply appear as repeated builder/critic commits in sequence.
    """
    lines = ["```mermaid", "gitGraph"]
    for i, snap in enumerate(snaps, 1):
        s = snapshot_summary(snap)
        label = f"snap-{i} {s['stage']} ${s['cost']:.4f}"
        if s["verdict"] not in ("", "-"):
            label += f" [{s['verdict']}]"
        lines.append(f'  commit id: "{label}"')
    if len(lines) == 2:
        lines.append('  commit id: "(no snapshots yet)"')
    lines.append("```")
    return "\n".join(lines)
