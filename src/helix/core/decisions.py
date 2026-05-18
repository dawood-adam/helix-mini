"""Decision log — the stage-by-stage audit trail.

This is also the human-readable digest reused by snapshots: a snapshot stores
the decision text the stage already produced, so snapshotting never costs an
LLM call (Risk: snapshot cost).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def append_decision(path: Path, stage: str, decision: str, rationale: str) -> dict:
    """Append one decision record. Returns the record (reused as the snapshot
    report so no extra work is done)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "decision": decision,
        "rationale": rationale,
    }
    log = json.loads(path.read_text()) if path.exists() else []
    log.append(record)
    path.write_text(json.dumps(log, indent=2))
    return record


def render_decisions_md(path: Path) -> str:
    if not path.exists():
        return "# Decision Log\n\n(no decisions yet)\n"
    log = json.loads(path.read_text())
    out = ["# Decision Log", ""]
    for r in log:
        out += [
            f"## [{r['timestamp']}] {r['stage']}",
            f"**Decision:** {r['decision']}",
            f"**Rationale:** {r['rationale']}",
            "",
        ]
    return "\n".join(out)


def save_decisions_md(project_dir: Path, decisions_path: Path) -> Path:
    dest = project_dir / "decisions.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_decisions_md(decisions_path))
    return dest
