"""Pipeline state — data flowing through the Forge pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


@dataclass
class ForgeState:
    project_name: str = ""
    research_question: str = ""
    input_folder: str = ""

    # HITL autonomy settings per gate
    autonomy: dict[str, str] = field(default_factory=dict)

    # Agent working data
    source_content: list[dict] = field(default_factory=list)
    candidate_approaches: list[dict] = field(default_factory=list)
    chosen_approach_id: str | None = None
    chosen_approach: dict = field(default_factory=dict)
    project_plan: dict[str, Any] = field(default_factory=dict)
    code_artifacts: list[dict] = field(default_factory=list)
    experiment_results: list[dict] = field(default_factory=list)

    # Routing
    sanity_check_flags: list[str] | None = None
    critiques: list[dict] = field(default_factory=list)
    next_action: str = ""

    # Budget
    cost_so_far: float = 0.0
    cost_cap: float = 5.0

    # Stage tracking
    current_stage: str = "start"
    completed_stages: list[str] = field(default_factory=list)
    error: str | None = None


class GraphState(TypedDict, total=False):
    """LangGraph state schema — mirrors ForgeState for graph node I/O."""

    project_name: str
    research_question: str
    input_folder: str
    autonomy: dict[str, str]
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
    cost_so_far: float
    cost_cap: float
    current_stage: str
    completed_stages: list[str]
    error: str | None


_STATE_FIELDS = set(ForgeState.__dataclass_fields__)


def to_state(d: dict) -> ForgeState:
    """Create ForgeState from dict, ignoring extra keys."""
    return ForgeState(**{k: v for k, v in d.items() if k in _STATE_FIELDS})
