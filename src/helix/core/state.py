"""Pipeline state — data flowing through the six stages.

A generic ``human_feedback`` channel: a send-back at any gate records a note
targeting a stage, and that stage's context builder injects it
on re-run. Run control (autonomy/directives) is the run-scoped ``Plan``
(``core.plan``), threaded through the loop — deliberately NOT state here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineState:
    project_name: str = ""
    research_question: str = ""
    input_folder: str = ""

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

    # Workstream F.5 — TDD task loop. Each entry: ``{task_id, phase, at}``.
    # Builder advances strictly test → impl → refactor per task; the
    # ``_map_builder`` guardrails reject batched submissions and
    # phase-jumps based on this trace.
    completed_tasks: list[dict] = field(default_factory=list)

    # Send-back feedback: {"from_stage","target_stage","note","ts"}
    human_feedback: list[dict] = field(default_factory=list)

    tokens_used: int = 0
    token_cap: int = 0
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


_STATE_FIELDS = set(PipelineState.__dataclass_fields__)


def to_state(d: dict) -> PipelineState:
    """PipelineState from a dict, ignoring unknown keys."""
    return PipelineState(**{k: v for k, v in d.items() if k in _STATE_FIELDS})
