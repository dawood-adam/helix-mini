"""Bounded run registry — observability + plan mutation for MCP runs.

Server-side only (NOT imported by ``helix.core``). Runs still execute
*within* the ``run_pipeline`` tool call, so the polished elicitation HITL is
unchanged. This adds, per run:

- a persisted ``record.json`` + append-only ``events.jsonl`` under
  ``.helix/runs/<run_id>/`` (history survives a server restart; live
  continuation is via snapshots/resume, not here);
- a live in-memory handle holding the run's ``Plan`` so ``hx_run_plan_set``
  can steer it (effective at the next gate — the loop re-reads the Plan).

Concurrency: a run executes in an ``anyio.to_thread`` worker while the event
loop stays free, so a concurrent ``hx_run_plan_set`` mutates the shared Plan
the loop reads at discrete gate points. Single-user local; GIL-safe enough.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .core.plan import Plan, Step
from .sandbox import validate_project_name


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    d = config.helix_dir() / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _dir(run_id: str) -> Path:
    d = _root() / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class RunRecord:
    run_id: str
    project: str
    status: str = "running"  # running | paused | done | error
    current_stage: str = ""
    last_snapshot: str | None = None
    tokens_used: int = 0
    note: str = ""
    started_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


@dataclass
class _Live:
    record: RunRecord
    plan: Plan
    seq: int = 0


_LIVE: dict[str, _Live] = {}


def _persist(rec: RunRecord) -> None:
    rec.updated_at = _now()
    (_dir(rec.run_id) / "record.json").write_text(json.dumps(asdict(rec), indent=2))
    (_root() / f"{rec.project}.latest").write_text(rec.run_id)


def start_run(project: str, plan: Plan) -> str:
    project = validate_project_name(project)
    run_id = "run_" + secrets.token_hex(3)
    rec = RunRecord(run_id=run_id, project=project)
    _LIVE[run_id] = _Live(record=rec, plan=plan)
    _persist(rec)
    return run_id


def record_event(run_id: str, stage: str, tokens: int, kind: str = "stage") -> None:
    live = _LIVE.get(run_id)
    if live is None:
        return
    live.seq += 1
    live.record.current_stage = stage
    live.record.tokens_used = int(tokens)
    event = {"seq": live.seq, "ts": _now(), "stage": stage,
             "tokens": int(tokens), "kind": kind}
    with open(_dir(run_id) / "events.jsonl", "a") as f:
        f.write(json.dumps(event) + "\n")
    _persist(live.record)


def finish_run(run_id: str, state) -> None:
    live = _LIVE.get(run_id)
    if live is None:
        return
    rec = live.record
    rec.status = (
        "error" if state.error
        else "paused" if (state.next_action or "").startswith("paused")
        else "done"
    )
    rec.tokens_used = int(state.tokens_used)
    rec.current_stage = state.current_stage
    rec.note = state.error or state.next_action or state.verdict or ""
    from .core.snapshots import list_snapshots

    snaps = list_snapshots(state.project_name)
    rec.last_snapshot = snaps[-1]["id"] if snaps else None
    _persist(rec)
    _LIVE.pop(run_id, None)
    try:  # best-effort: a cache write must never fail a completed run
        from .core.hot import write_hot

        write_hot(state.project_name)
    except Exception:  # noqa: BLE001 - defensive by design
        pass


def abort_run(run_id: str, note: str) -> None:
    live = _LIVE.get(run_id)
    if live is None:
        return
    live.record.status = "error"
    live.record.note = note
    _persist(live.record)
    _LIVE.pop(run_id, None)


# --- Pending step (agent-driven suspend/resume across tool calls) -----------
# The run is suspended at an LLM stage waiting for the client agent's answer.
# Persisted to disk (not just _LIVE) so a server restart between hx_step and
# hx_submit is still resumable. Keyed by project.


def _pending_path(project: str) -> Path:
    return _root() / f"{validate_project_name(project)}.pending.json"


def set_pending(project: str, data: dict) -> None:
    _pending_path(project).write_text(json.dumps(data, indent=2))


def get_pending(project: str) -> dict | None:
    p = _pending_path(project)
    return json.loads(p.read_text()) if p.exists() else None


def clear_pending(project: str) -> None:
    _pending_path(project).unlink(missing_ok=True)


def _resolve(project: str | None, run_id: str | None) -> str | None:
    if run_id:
        return run_id
    if project:
        p = _root() / f"{validate_project_name(project)}.latest"
        return p.read_text().strip() if p.exists() else None
    return None


def get_record(project: str | None = None, run_id: str | None = None) -> RunRecord | None:
    rid = _resolve(project, run_id)
    if rid is None:
        return None
    if rid in _LIVE:
        return _LIVE[rid].record
    p = _dir(rid) / "record.json"
    return RunRecord(**json.loads(p.read_text())) if p.exists() else None


def tail_events(project: str | None = None, run_id: str | None = None,
                since: int = 0) -> list[dict]:
    rid = _resolve(project, run_id)
    if rid is None:
        return []
    fp = _dir(rid) / "events.jsonl"
    if not fp.exists():
        return []
    out = []
    for line in fp.read_text().splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("seq", 0) > since:
            out.append(ev)
    return out


def set_plan(project: str | None = None, run_id: str | None = None, *,
             autonomy_until: str | None = None,
             steps: list[dict] | None = None) -> str:
    """Steer a live run's Plan (effective at the next gate)."""
    rid = _resolve(project, run_id)
    live = _LIVE.get(rid or "")
    if live is None:
        return f"No live run for {run_id or project!r} (only live runs are steerable)."
    if steps is not None:
        live.plan.steps = [Step(**s) for s in steps]
        live.plan.auto_until = None
    if autonomy_until is not None:
        live.plan.auto_until = autonomy_until
        live.plan.steps = []
    return f"Plan updated for {rid}; effective at the next gate."
