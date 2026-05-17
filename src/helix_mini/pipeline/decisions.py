"""Decision log — JSON storage + markdown rendering."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def append_decision(
    decisions_path: Path,
    stage: str,
    decision: str,
    rationale: str,
    data: dict | None = None,
) -> None:
    """Append a decision entry to the JSON log."""
    decisions_path.parent.mkdir(parents=True, exist_ok=True)

    entries = []
    if decisions_path.exists():
        try:
            entries = json.loads(decisions_path.read_text())
        except (json.JSONDecodeError, ValueError):
            entries = []

    entries.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "decision": decision,
        "rationale": rationale,
        "data": data or {},
    })

    decisions_path.write_text(json.dumps(entries, indent=2))


def render_decisions_md(decisions_path: Path) -> str:
    """Render the JSON decision log as readable markdown."""
    if not decisions_path.exists():
        return "# Decisions\n\nNo decisions recorded yet.\n"

    try:
        entries = json.loads(decisions_path.read_text())
    except (json.JSONDecodeError, ValueError):
        return "# Decisions\n\nCorrupted decision log.\n"

    lines = ["# Decision Log\n"]
    for entry in entries:
        ts = entry.get("timestamp", "unknown")
        stage = entry.get("stage", "unknown")
        decision = entry.get("decision", "")
        rationale = entry.get("rationale", "")

        lines.append(f"## [{ts}] {stage}")
        lines.append(f"**Decision:** {decision}")
        lines.append(f"**Rationale:** {rationale}")
        lines.append("")

    return "\n".join(lines)


def save_decisions_md(project_dir: Path, decisions_path: Path) -> None:
    """Write the rendered markdown alongside the JSON."""
    md = render_decisions_md(decisions_path)
    (project_dir / "decisions.md").write_text(md)
