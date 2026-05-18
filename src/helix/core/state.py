"""Pipeline state — data flowing through the six stages.

Adds a generic ``human_feedback`` channel (Risk I): a send-back at any gate
records a note targeting a stage, and that stage's context builder injects it
on re-run. ``autonomy_until`` (Risk: autonomy model) replaces per-gate flags.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


@dataclass
class PipelineState:
    project_name: str = ""
    research_question: str = ""
    input_folder: str = ""

    # "" / "none" -> ask at every gate. A stage name -> auto-proceed gates
    # before it, then ask. "END" -> fully autonomous.
    autonomy_until: str = ""

    source_content: list[dict] = field(default_factory=list)
    candidate_approaches: list[dict] = field(default_factory=list)
    chosen_approach_id: str | None = None
    chosen_approach: dict = field(default_factory=dict)
    project_plan: dict[str, Any] = field(default_factory=dict)
    code_artifacts: list[dict] = field(default_factory=list)
    experiment_results: list[dict] = field(default_factory=list)

    sanity_check_flags: list[str] | None = None
    critiques: list[dict] = field(default_factory=list)
    next_action: str = ""
    verdict: str = ""
    build_iterations: int = 0

    # Send-back feedback: {"from_stage","target_stage","note","ts"}
    human_feedback: list[dict] = field(default_factory=list)

    cost_so_far: float = 0.0
    cost_cap: float = 10.0
    call_cap: int = 0

    current_stage: str = "start"
    completed_stages: list[str] = field(default_factory=list)
    error: str | None = None

    def feedback_for(self, stage: str) -> list[str]:
        """Notes the human directed at ``stage`` via a send-back."""
        return [
            f["note"]
            for f in self.human_feedback
            if f.get("target_stage") == stage and f.get("note")
        ]


class GraphState(TypedDict, total=False):
    """LangGraph schema — mirrors PipelineState for node I/O."""

    project_name: str
    research_question: str
    input_folder: str
    autonomy_until: str
    source_content: list[dict]
    candidate_approaches: list[dict]
    chosen_approach_id: str | None
    chosen_approach: dict
    project_plan: dict[str, Any]
    code_artifacts: list[dict]
    experiment_results: list[dict]
    sanity_check_flags: list[str] | None
    critiques: list
    next_action: str
    verdict: str
    build_iterations: int
    human_feedback: list[dict]
    cost_so_far: float
    cost_cap: float
    call_cap: int
    current_stage: str
    completed_stages: list[str]
    error: str | None


_STATE_FIELDS = set(PipelineState.__dataclass_fields__)


def to_state(d: dict) -> PipelineState:
    """PipelineState from a dict, ignoring unknown keys."""
    return PipelineState(**{k: v for k, v in d.items() if k in _STATE_FIELDS})
