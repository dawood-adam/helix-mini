"""Stage execution — thin wrapper over the markdown agents.

``run_stage`` is the unit both orchestrators call. It runs the agent and
produces the audit ``decision``/``rationale`` text — which snapshots reuse as
their human-readable digest, so a snapshot costs no extra work.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .agents import AgentCtx, run_agent
from .state import PipelineState


@dataclass
class StageResult:
    updates: dict = field(default_factory=dict)
    cost: float = 0.0
    decision: str = ""
    rationale: str = ""
    error: str | None = None


def _v(updates: dict, state: PipelineState, name: str):
    return updates.get(name, getattr(state, name))


def _decision_text(stage: str, u: dict, s: PipelineState) -> tuple[str, str]:
    if stage == "scout":
        n = len(_v(u, s, "candidate_approaches") or [])
        return f"Identified {n} approaches", "Ingested sources, analyzed directions"
    if stage == "critic_methods":
        return (
            f"Recommended approach: {_v(u, s, 'chosen_approach_id')}",
            f"Evaluated {len(s.candidate_approaches)} candidates",
        )
    if stage == "planner":
        title = (_v(u, s, "project_plan") or {}).get("title", "untitled")
        return f"Plan: {title}", "Designed validation plan with success criteria"
    if stage == "builder":
        arts = _v(u, s, "code_artifacts") or []
        files = u.get("artifact_files", [])
        return (
            f"Produced {len(arts)} artifacts ({len(files)} file(s) written)",
            f"Built code (iteration {s.build_iterations})"
            + (f"; files: {', '.join(files[:10])}" if files else ""),
        )
    if stage == "validator":
        flags = _v(u, s, "sanity_check_flags")
        return ("pass" if not flags else f"flags: {flags}",
                "Checked results against validation bands")
    if stage == "critic_results":
        return (f"Verdict: {_v(u, s, 'verdict')}",
                "Final assessment of results and approach")
    return stage, ""


def run_stage(stage: str, state: PipelineState, ctx: AgentCtx) -> StageResult:
    updates, cost = run_agent(stage, state, ctx)
    if updates.get("error"):
        return StageResult(updates={}, cost=cost, error=updates["error"])
    decision, rationale = _decision_text(stage, updates, state)
    return StageResult(updates=updates, cost=cost, decision=decision, rationale=rationale)
