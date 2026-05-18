"""The single next-stage resolver.

Both orchestrators (plain loop and LangGraph) call ``next_stage`` so they can
never diverge on routing — the conformance test relies on this (Risk A).
"""

from __future__ import annotations

from functools import lru_cache

from .agents import stage_order
from .gates import GateDecision

END = "END"


@lru_cache(maxsize=1)
def stages() -> tuple[str, ...]:
    return tuple(stage_order())


def is_stage(name: str) -> bool:
    return name in stages()


def next_stage(current: str, gate: GateDecision) -> str:
    """Resolve the next stage from the current stage + a gate decision.

    ``proceed`` -> the next stage in order (or END past the last);
    ``goto`` -> any stage (forward or backward); ``stop`` -> END.
    """
    if gate.action == "stop":
        return END
    if gate.action == "goto":
        if not is_stage(gate.target or ""):
            raise ValueError(
                f"goto unknown stage {gate.target!r}; valid: {', '.join(stages())}"
            )
        return gate.target  # type: ignore[return-value]
    order = stages()
    i = order.index(current)
    return order[i + 1] if i + 1 < len(order) else END
