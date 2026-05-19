"""The Plan primitive — how a run is controlled.

A Plan is run-scoped control config, not pipeline data: it is threaded
through the loop alongside ``ask``/``interactive`` and is NOT a
``PipelineState`` field (so it never serializes into a snapshot).

It governs two things at each transition:

- **autonomy** — is the gate after a stage auto, or does it ask the human?
- **directive** — optional guidance injected into a stage when it runs.

The legacy ``autonomy_until`` string is just a constructor
(:meth:`Plan.from_autonomy_until`) so existing callers/tests are unchanged;
the engine underneath is now the Plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Step:
    agent: str
    directive: str | None = None
    autonomy: str = "hitl"  # "auto" | "hitl"
    n: int = 1


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    # Declared for the richer run lifecycle (honored once runs are
    # tasks-backed, 2c); in 2b an exhausted plan simply falls back to asking
    # the human at the gate.
    on_exhaustion: str = "pause"  # "pause" | "stop"
    # Compat mode: when set, autonomy is derived from an autonomy_until
    # string ("" / "none" → pure HITL, "END" → full auto, a stage name →
    # auto for gates before it). None → use ``steps``.
    auto_until: str | None = None

    @classmethod
    def from_autonomy_until(cls, autonomy_until: str | None) -> Plan:
        return cls(auto_until=(autonomy_until or ""))

    def _step_for(self, agent: str) -> Step | None:
        for s in self.steps:
            if s.agent == agent:
                return s
        return None

    def gate_auto(self, after_stage: str, order: list[str]) -> bool:
        """Does the gate after ``after_stage`` auto-proceed (no human ask)?"""
        if self.auto_until is not None:
            au = (self.auto_until or "").strip()
            if au in ("", "none"):
                return False
            if au == "END":
                return True
            try:
                return order.index(after_stage) < order.index(au)
            except ValueError:
                return False
        st = self._step_for(after_stage)
        if st is None:
            return False  # plan exhausted / stage not in plan → ask the human
        return st.autonomy == "auto"

    def directive_for(self, stage: str) -> str | None:
        if self.auto_until is not None:
            return None
        st = self._step_for(stage)
        return st.directive if st else None
