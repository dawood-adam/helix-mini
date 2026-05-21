"""Workstream H — the autonomous hypothesis loop (propose → validate → revise).

The hypothesis loop runs *across* the existing six stages, not as a new
stage. The carrier is the ``hypothesis`` **thread** (Workstream E) at
``projects/<id>/threads/hypothesis.md``: each candidate hypothesis is a
section in that thread with a small extra schema —
``{id, statement, type, support, refutations, status, score}`` — and the
``rediscover`` plan mode (Workstream H.2) restarts from Scout after the
Results Critic, capped at ``REDISCOVER_CAP`` iterations, with the thread
carried forward so each iteration builds on the previous round's
verdicts.

The ranker (``rank``) is intentionally deterministic + dependency-light
— an Elo-style pairwise score on the (testable · falsifiable ·
distinct) rubric the Scout Critic emits. Co-Scientist-style idea
tournament, but priced for a laptop.

Pure stdlib. No MCP, no model, no thread import (the orchestrator wires
threads through `core.threads` separately).
"""

from __future__ import annotations

from dataclasses import dataclass, field

REDISCOVER_CAP = 3
HYP_TYPES = ("descriptive", "explanatory", "predictive", "interventional")
HYP_STATUSES = ("Proposed", "Accepted", "Supported", "Refuted",
                "Inconclusive", "Superseded")


@dataclass
class Hypothesis:
    """One candidate hypothesis on the project's hypothesis thread.

    Inherits the thread schema (Workstream E): the actual ``opened_at``
    / ``last_touched_at`` / ``contributors`` live on the thread page.
    This object carries only the per-hypothesis fields.
    """

    id: str
    statement: str
    type: str = "explanatory"
    # Scout Critic rubric scores (0.0–1.0); the ranker uses these to
    # produce an ordered list.
    testable: float = 0.0
    falsifiable: float = 0.0
    distinct: float = 0.0
    # Run-time evidence — populated by the loop iterations.
    support: list[str] = field(default_factory=list)        # Atlas page ids
    refutations: list[str] = field(default_factory=list)
    status: str = "Proposed"

    def __post_init__(self) -> None:
        if self.type not in HYP_TYPES:
            self.type = "explanatory"
        if self.status not in HYP_STATUSES:
            self.status = "Proposed"

    @property
    def score(self) -> float:
        """Composite rubric score (mean of the three rubric axes).

        Ties broken at rank time by id (alphabetical) so the result is
        deterministic — same input, same order, every time."""
        return (self.testable + self.falsifiable + self.distinct) / 3.0


def rank(hypotheses: list[Hypothesis]) -> list[Hypothesis]:
    """Return the hypotheses sorted best → worst.

    Deterministic (Elo-isn't-needed) — score descending, then id ascending
    for tie-break. Hypotheses that have been ``Refuted`` or ``Superseded``
    are pushed to the bottom regardless of score: the tournament should
    surface still-alive ideas first."""
    alive_rank = {"Refuted": 99, "Superseded": 98}

    def key(h: Hypothesis):
        return (alive_rank.get(h.status, 0), -h.score, h.id)
    return sorted(hypotheses, key=key)


# --- Serialization helpers (the hypothesis thread body format) ------------

# The thread body holds one ``### <id>`` section per hypothesis. The
# parser is liberal: it tolerates extra prose between sections and
# falls back to defaults if a field is malformed.

import re

_HYP_HEADER = re.compile(r"^###\s+(\S+)\s*$", re.MULTILINE)
_FIELD = re.compile(r"^-\s*(\w+):\s*(.+?)\s*$", re.MULTILINE)


def parse_hypotheses(thread_body: str) -> list[Hypothesis]:
    """Parse hypotheses from a thread body (as produced by ``to_section``).

    Tolerant: unknown fields are ignored; missing rubric scores default
    to 0; comma-separated lists become Python lists."""
    out: list[Hypothesis] = []
    headers = list(_HYP_HEADER.finditer(thread_body))
    for i, h in enumerate(headers):
        hid = h.group(1).strip()
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(thread_body)
        section = thread_body[start:end]
        fields = {m.group(1): m.group(2).strip() for m in _FIELD.finditer(section)}
        try:
            testable = float(fields.get("testable", "0") or 0)
            falsifiable = float(fields.get("falsifiable", "0") or 0)
            distinct = float(fields.get("distinct", "0") or 0)
        except ValueError:
            testable = falsifiable = distinct = 0.0
        out.append(Hypothesis(
            id=hid,
            statement=fields.get("statement", ""),
            type=fields.get("type", "explanatory"),
            testable=testable, falsifiable=falsifiable, distinct=distinct,
            support=_split(fields.get("support")),
            refutations=_split(fields.get("refutations")),
            status=fields.get("status", "Proposed"),
        ))
    return out


def _split(v: str | None) -> list[str]:
    if not v:
        return []
    return [s.strip() for s in v.split(",") if s.strip()]


def to_section(h: Hypothesis) -> str:
    """Render one hypothesis as its body section. Compose multiple via
    ``"\n".join(to_section(h) for h in rank(hs))`` to drop the ranked
    bundle into the thread body."""
    lines = [
        f"### {h.id}",
        f"- statement: {h.statement}",
        f"- type: {h.type}",
        f"- testable: {h.testable}",
        f"- falsifiable: {h.falsifiable}",
        f"- distinct: {h.distinct}",
        f"- status: {h.status}",
    ]
    if h.support:
        lines.append(f"- support: {', '.join(h.support)}")
    if h.refutations:
        lines.append(f"- refutations: {', '.join(h.refutations)}")
    return "\n".join(lines) + "\n"


# --- The rediscover loop control ------------------------------------------


def is_rediscover(plan) -> bool:
    """Predicate the orchestrator uses to identify Workstream-H mode.

    A duck-typed read of the Plan's ``auto_until`` so we don't introduce
    a hard dependency on ``core.plan`` from the orchestrator's transition
    logic (Plan lives in core.plan; this module stays leaf)."""
    return getattr(plan, "auto_until", None) == "rediscover"


def iterations_so_far(state) -> int:
    """How many full pipeline iterations (critic_results completions) have
    happened so far in this run? Capped externally by ``REDISCOVER_CAP``."""
    return sum(1 for s in getattr(state, "completed_stages", [])
                if s == "critic_results")


def should_loop_again(state, plan) -> bool:
    """True iff the rediscover loop should restart from Scout."""
    return is_rediscover(plan) and iterations_so_far(state) < REDISCOVER_CAP
