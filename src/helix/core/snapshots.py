"""Snapshots v2 — git-style version control for pipeline state.

A snapshot is a timestamped, stage-stamped, deterministic serialization of
state. It costs **zero LLM calls**: it reuses the decision/rationale the stage
already produced as its human digest. Artifact bytes are content-addressed
(stored once under ``objects/<sha>``) so a snapshot stays a few KB even after
hundreds of refine cycles (Risk C). Each snapshot records ``parent`` and
``branch``, so the history is a real DAG that branches, reverts, and resumes
(Risk D).

Layout: ``<.helix>/snapshots/<project>/`` → ``objects/``, ``<id>.json``,
``index.json``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .. import config
from ..sandbox import SandboxError, validate_artifact_name
from .state import PipelineState, to_state

log = logging.getLogger(__name__)


def _root(project: str) -> Path:
    d = config.helix_dir() / "snapshots" / project
    (d / "objects").mkdir(parents=True, exist_ok=True)
    return d


def _index_path(project: str) -> Path:
    return _root(project) / "index.json"


def _read_index(project: str) -> list[dict]:
    p = _index_path(project)
    return json.loads(p.read_text()) if p.exists() else []


def _put_object(project: str, content: str) -> str:
    sha = hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()
    obj = _root(project) / "objects" / sha
    if not obj.exists():
        obj.write_text(content)
    return sha


def _get_object(project: str, sha: str) -> str:
    obj = _root(project) / "objects" / sha
    return obj.read_text() if obj.exists() else ""


def mint_snapshot(
    state: PipelineState,
    project: str,
    *,
    stage: str,
    report: dict | None = None,
    parent: str | None = None,
    branch: str = "main",
) -> dict:
    """Append an immutable snapshot. Returns its metadata. No LLM call."""
    index = _read_index(project)
    next_id = str(max((int(m["id"]) for m in index), default=0) + 1)

    manifest = []
    for a in state.code_artifacts or []:
        content = a.get("content") or ""
        manifest.append({
            "name": a.get("name"),
            "type": a.get("type"),
            "description": a.get("description"),
            "sha": _put_object(project, content),
        })

    slim = asdict(state)
    slim["code_artifacts"] = []  # bytes live in objects/, referenced by manifest

    snap = {
        "id": next_id,
        "parent": parent,
        "branch": branch,
        "stage": stage,
        "ts": datetime.now(timezone.utc).isoformat(),
        "report": report or {},
        "artifact_manifest": manifest,
        "state": slim,
    }
    (_root(project) / f"{next_id}.json").write_text(json.dumps(snap, indent=2, default=str))
    meta = {k: snap[k] for k in ("id", "parent", "branch", "stage", "ts")}
    index.append(meta)
    _index_path(project).write_text(json.dumps(index, indent=2))
    return meta


def load_snapshot(project: str, snap_id: str | int) -> dict | None:
    """Load one snapshot with artifacts rehydrated from the object store."""
    p = _root(project) / f"{snap_id}.json"
    if not p.exists():
        return None
    snap = json.loads(p.read_text())
    rehydrated = []
    for m in snap.get("artifact_manifest", []):
        rehydrated.append({
            "name": m.get("name"),
            "type": m.get("type"),
            "description": m.get("description"),
            "content": _get_object(project, m["sha"]) if m.get("sha") else "",
        })
    snap["state"]["code_artifacts"] = rehydrated
    return snap


def list_snapshots(project: str) -> list[dict]:
    return _read_index(project)


def resume_state(project: str, snap_id: str | int) -> PipelineState | None:
    snap = load_snapshot(project, snap_id)
    return to_state(snap["state"]) if snap else None


def restore_artifacts(project: str, snap_id: str | int, dest: Path) -> list[str]:
    """Write a snapshot's artifacts back to ``dest`` (git checkout of files)."""
    snap = load_snapshot(project, snap_id)
    if not snap:
        return []
    written = []
    for a in snap["state"].get("code_artifacts", []):
        name = a.get("name")
        if not name:
            continue
        # Defense in depth: never trust a stored name. A hand-crafted or
        # legacy snapshot could carry a traversal/absolute path; confine the
        # write to ``dest`` exactly as the builder write path does.
        try:
            fp = validate_artifact_name(name, dest)
        except SandboxError as e:
            log.warning("Sandbox blocked snapshot artifact restore: %s", e)
            continue
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(a.get("content") or "")
        written.append(str(fp.relative_to(dest.resolve())))
    return written


def snapshot_summary(snap: dict) -> dict:
    st = snap.get("state", {})
    return {
        "id": snap.get("id"),
        "parent": snap.get("parent"),
        "branch": snap.get("branch", "main"),
        "stage": snap.get("stage") or st.get("current_stage", "?"),
        "ts": snap.get("ts", "?"),
        "cost": float(st.get("cost_so_far", 0.0) or 0.0),
        "iterations": st.get("build_iterations", 0),
        "verdict": st.get("verdict", "") or "-",
        "artifacts": len(snap.get("artifact_manifest", []) or []),
        "error": st.get("error"),
    }


_DIFF_FIELDS = (
    "current_stage", "verdict", "build_iterations", "cost_so_far",
    "chosen_approach_id", "next_action", "error",
)
_DIFF_LIST_FIELDS = (
    "candidate_approaches", "experiment_results", "critiques",
    "completed_stages", "sanity_check_flags", "human_feedback",
)


def diff_snapshots(a: dict, b: dict) -> dict[str, tuple]:
    """git-status-style diff: scalars by value, lists by length."""
    sa, sb = a.get("state", {}), b.get("state", {})
    out: dict[str, tuple] = {}
    if a.get("branch") != b.get("branch"):
        out["branch"] = (a.get("branch"), b.get("branch"))
    for f in _DIFF_FIELDS:
        if sa.get(f) != sb.get(f):
            out[f] = (sa.get(f), sb.get(f))
    for f in _DIFF_LIST_FIELDS:
        la, lb = len(sa.get(f) or []), len(sb.get(f) or [])
        if la != lb:
            out[f] = (f"{la} items", f"{lb} items")
    na, nb = len(a.get("artifact_manifest") or []), len(b.get("artifact_manifest") or [])
    if na != nb:
        out["artifacts"] = (f"{na} items", f"{nb} items")
    return out


def snapshot_gitgraph(project: str) -> str:
    """Render the real parent/branch DAG as a Mermaid ``gitGraph``."""
    index = _read_index(project)
    lines = ["```mermaid", "gitGraph"]
    seen_branches = {"main"}
    current = "main"
    if not index:
        lines += ['  commit id: "(no snapshots yet)"', "```"]
        return "\n".join(lines)
    for m in index:
        br = m.get("branch", "main")
        if br not in seen_branches:
            lines.append(f"  branch {br}")
            seen_branches.add(br)
            current = br
        elif br != current:
            lines.append(f"  checkout {br}")
            current = br
        label = f"{m['id']} {m.get('stage', '?')}"
        lines.append(f'  commit id: "snap-{label}"')
    lines.append("```")
    return "\n".join(lines)
