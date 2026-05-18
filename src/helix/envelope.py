"""The uniform response envelope and the ``ask`` elicitation primitive.

This is transport-agnostic on purpose. The same ``Envelope`` / ``Ask`` /
``Question`` objects are rendered by the CLI today and will be returned
verbatim by the MCP server later — one engine, many front-ends. ``ask`` lets
*any* operation hold the user's hand when arguments are missing or a
destructive action needs acknowledgement; it is a design primitive, not a
per-command wizard.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

QType = Literal[
    "string", "int", "float", "bool",
    "choice", "multi", "path", "id_ref", "confirm",
]


@dataclass
class Question:
    key: str
    prompt: str
    type: QType = "string"
    constraints: dict = field(default_factory=dict)   # pattern, min, max, must_exist
    options: list[dict] | None = None                  # [{value,label}] for choice/multi/id_ref
    examples: list[str] = field(default_factory=list)


@dataclass
class Ask:
    session: str
    questions: list[Question]


@dataclass
class Envelope:
    """Uniform reply: ``{result, ask?, next?, warn?, events?}``."""

    result: Any | None = None
    ask: Ask | None = None
    next: str | None = None
    warn: str | None = None
    events: list | None = None

    def to_dict(self) -> dict:
        ask = None
        if self.ask is not None:
            ask = {
                "session": self.ask.session,
                "questions": [
                    {k: v for k, v in asdict(q).items() if v not in (None, [], {})}
                    for q in self.ask.questions
                ],
            }
        d: dict[str, Any] = {
            "result": self.result, "ask": ask,
            "next": self.next, "warn": self.warn,
        }
        if self.events is not None:
            d["events"] = self.events
        return d


class AnswerError(ValueError):
    """A supplied answer failed the question's constraints."""


def validate_answer(q: Question, value: Any) -> Any:
    """Coerce + validate one answer. Returns the clean value or raises
    ``AnswerError`` with a user-facing message."""
    c = q.constraints or {}
    if q.type == "string":
        s = str(value)
        pat = c.get("pattern")
        if pat and not re.fullmatch(pat, s):
            raise AnswerError(f"must match {pat}")
        return s
    if q.type in ("int", "float"):
        try:
            n = int(value) if q.type == "int" else float(value)
        except (TypeError, ValueError):
            raise AnswerError(f"expected a {q.type}")
        if "min" in c and n < c["min"]:
            raise AnswerError(f"must be >= {c['min']}")
        if "max" in c and n > c["max"]:
            raise AnswerError(f"must be <= {c['max']}")
        return n
    if q.type in ("bool", "confirm"):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("y", "yes", "true", "1")
    if q.type in ("choice", "id_ref"):
        valid = {o["value"] for o in (q.options or [])}
        if value not in valid:
            raise AnswerError(f"pick one of: {', '.join(sorted(valid))}")
        return value
    if q.type == "multi":
        valid = {o["value"] for o in (q.options or [])}
        picked = list(value) if isinstance(value, (list, tuple)) else [value]
        bad = [p for p in picked if p not in valid]
        if bad:
            raise AnswerError(f"unknown: {', '.join(map(str, bad))}")
        if not picked:
            raise AnswerError("pick at least one")
        return picked
    if q.type == "path":
        p = Path(str(value)).expanduser()
        if c.get("must_exist", False) and not p.exists():
            raise AnswerError(f"path does not exist: {p}")
        return str(p)
    return value
