"""Decision log — the stage-by-stage audit trail.

This is also the human-readable digest reused by snapshots: a snapshot stores
the decision text the stage already produced, so snapshotting never costs an
LLM call (Risk: snapshot cost).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class DecisionCard:
    """The single structured output every agent produces (HELIX-v3 §6).

    Source of truth for: the snapshot's human digest, the decision log, gate
    prompts, and (later) Loom / the linter. Agents are *asked* to fill it
    (builtin prompts); when an LLM omits it we fall back to a generic card so
    the pipeline never blocks on a missing/partial field.
    """

    summary: str = ""
    key_findings: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    directive_for_next: str = ""
    confidence: str = "medium"  # low | medium | high

    @staticmethod
    def _strs(v) -> list[str]:
        if isinstance(v, list):
            return [str(x) for x in v if x not in (None, "")]
        return [str(v)] if v not in (None, "") else []

    @classmethod
    def from_response(cls, resp: dict | None, stage: str) -> DecisionCard:
        d = (resp or {}).get("decision_card")
        if not isinstance(d, dict):
            d = {}
        conf = str(d.get("confidence", "medium")).lower()
        if conf not in ("low", "medium", "high"):
            conf = "medium"
        return cls(
            summary=str(d.get("summary") or "").strip() or f"{stage} complete",
            key_findings=cls._strs(d.get("key_findings")),
            assumptions=cls._strs(d.get("assumptions")),
            open_questions=cls._strs(d.get("open_questions")),
            directive_for_next=str(d.get("directive_for_next") or "").strip(),
            confidence=conf,
        )


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
