"""Gate model — the human-in-the-loop control between every stage.

After each stage the orchestrator presents a report; the human may proceed,
send the run back to ANY stage with contextualized feedback, or stop. An
``autonomy_until`` window auto-proceeds early gates. The deterministic
validator auto-routes hard flags back to the builder (the old sanity route),
feeding the flags in as feedback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .agents import stage_order
from .state import PipelineState


@dataclass
class GateDecision:
    action: str  # "proceed" | "goto" | "stop"
    target: str | None = None  # stage name when action == "goto"
    feedback: str | None = None


@dataclass
class GateReport:
    stage: str
    decision: str
    rationale: str
    summary: dict = field(default_factory=dict)
    note: str = ""  # e.g. validator flags, critic verdict


# An asker is: (GateReport) -> GateDecision. None/non-interactive => proceed.
Asker = "callable[[GateReport], GateDecision]"


def gate_is_auto(after_stage: str, autonomy_until: str) -> bool:
    """Whether the gate after ``after_stage`` auto-proceeds."""
    au = (autonomy_until or "").strip()
    if au in ("", "none"):
        return False
    if au == "END":
        return True
    order = stage_order()
    try:
        return order.index(after_stage) < order.index(au)
    except ValueError:
        return False


def record_feedback(state: PipelineState, frm: str, target: str, note: str) -> None:
    state.human_feedback.append({
        "from_stage": frm,
        "target_stage": target,
        "note": note,
        "ts": datetime.now(timezone.utc).isoformat(),
    })


def _summary(state: PipelineState) -> dict:
    return {
        "approaches": len(state.candidate_approaches or []),
        "chosen": state.chosen_approach_id or "-",
        "plan": (state.project_plan or {}).get("title", "-"),
        "artifacts": len(state.code_artifacts or []),
        "results": len(state.experiment_results or []),
        "verdict": state.verdict or "-",
        "cost": round(state.cost_so_far, 4),
        "iterations": state.build_iterations,
    }


def decide_gate(
    state: PipelineState,
    after_stage: str,
    decision: str,
    rationale: str,
    *,
    ask=None,
    interactive: bool = False,
) -> GateDecision:
    """Resolve the gate after ``after_stage``."""
    auto = gate_is_auto(after_stage, state.autonomy_until)
    can_ask = bool(ask) and interactive and not auto

    if after_stage == "validator":
        flags = state.sanity_check_flags or []
        hard = any(str(f).startswith("HARD:") for f in flags)
        if hard and not can_ask:
            note = "Validator hard flags: " + "; ".join(map(str, flags))
            record_feedback(state, "validator", "builder", note)
            return GateDecision("goto", "builder", note)

    if after_stage == "critic_results" and not can_ask:
        verdict = (state.verdict or "ship").lower()
        if verdict == "iterate":
            note = "critic verdict: iterate"
            record_feedback(state, "critic_results", "builder", note)
            return GateDecision("goto", "builder", note)
        return GateDecision("stop", None, verdict)

    if not can_ask:
        return GateDecision("proceed")

    note = ""
    if after_stage == "validator" and state.sanity_check_flags:
        note = "flags: " + "; ".join(map(str, state.sanity_check_flags))
    elif after_stage == "critic_results":
        note = f"critic verdict: {state.verdict or 'ship'}"
    report = GateReport(after_stage, decision, rationale, _summary(state), note)
    gd = ask(report)
    if gd.action == "goto" and gd.feedback:
        record_feedback(state, after_stage, gd.target or "", gd.feedback)
    return gd
