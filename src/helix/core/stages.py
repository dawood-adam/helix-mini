"""Stage execution — thin wrapper over the markdown agents.

``run_stage`` is the unit the orchestrator calls. The agent's Decision Card
is the single structured output; its ``summary`` is the human-readable digest
snapshots reuse, so a snapshot still costs no extra work.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .agents import AgentCtx, run_agent
from .decisions import DecisionCard
from .state import PipelineState


@dataclass
class StageResult:
    updates: dict = field(default_factory=dict)
    tokens: int = 0
    card: DecisionCard = field(default_factory=DecisionCard)
    error: str | None = None

    # Legacy projection: the decision log and gate prompts still take plain
    # strings; they could consume the card directly in a later cleanup.
    @property
    def decision(self) -> str:
        return self.card.summary

    @property
    def rationale(self) -> str:
        return "; ".join(self.card.key_findings) or self.card.directive_for_next


def run_stage(stage: str, state: PipelineState, ctx: AgentCtx) -> StageResult:
    from ..io import ClientUnavailable

    try:
        updates, tokens, card = run_agent(stage, state, ctx)
    except ClientUnavailable as e:
        # The model/elicitation seam went away mid-stage. Treat it exactly
        # like an agent input error: a clean StageResult.error, so advance
        # snapshots it and the run stops resumably instead of the exception
        # crashing the tool and losing the whole run.
        return StageResult(updates={}, tokens=0, error=str(e))
    if updates.get("error"):
        return StageResult(updates={}, tokens=tokens, error=updates["error"])
    return StageResult(updates=updates, tokens=tokens, card=card)
