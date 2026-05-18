"""Intent state machines — the conversational layer over Helix.

An intent is a server-owned wizard: it knows the real state (projects, gates,
snapshots) and decides what to ask next. ``step`` is pure and
transport-agnostic — the CLI renders it today, the MCP server will return it
verbatim tomorrow. The same ``ask`` primitive subsumes confirmations
(``type:"confirm"``), so there is no separate confirm-token plumbing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .envelope import AnswerError, Ask, Envelope, Question, validate_answer
from .sessions import SESSIONS, Session


@dataclass
class Slot:
    key: str
    build: Callable[[Session], Question]
    when: Callable[[dict], bool] = lambda a: True


# --- hx_start -------------------------------------------------------------

def _stage_options() -> list[dict]:
    from .core.agents import stage_order

    return [{"value": s, "label": s} for s in stage_order()]


_START_SLOTS = [
    Slot("project_name", lambda s: Question(
        "project_name", "What should we call this project?", "string",
        constraints={"pattern": r"[a-z0-9][a-z0-9-]*"},
        examples=["smartphone-bp", "lupus-cases"])),
    Slot("description", lambda s: Question(
        "description", "One-sentence description of the research question?",
        "string")),
    Slot("control", lambda s: Question(
        "control", "How should it run?", "choice", options=[
            {"value": "step", "label": "Step-by-step — check in at every transition"},
            {"value": "auto_to", "label": "Autonomous up to a stage you choose"},
            {"value": "auto", "label": "Fully autonomous"},
        ])),
    Slot("stage", lambda s: Question(
        "stage", "Autonomous until which stage (it pauses there)?", "choice",
        options=_stage_options()),
        when=lambda a: a.get("control") == "auto_to"),
    Slot("start", lambda s: Question(
        "start",
        f"Start \"{s.answers.get('project_name')}\" now "
        f"({_mode_label(s.answers)})?",
        "confirm")),
]


def _mode_label(a: dict) -> str:
    c = a.get("control")
    if c == "auto":
        return "fully autonomous"
    if c == "auto_to":
        return f"autonomous until {a.get('stage', '?')}"
    return "step-by-step HITL"


def _resolve_start(a: dict) -> Envelope:
    autonomy = {"step": "", "auto": "END"}.get(
        a["control"], a.get("stage", ""))
    result = {
        "project": a["project_name"],
        "folder": f"./{a['project_name']}",
        "research_question": a["description"],
        "autonomy_until": autonomy,
        "control": a["control"],
        "start": bool(a.get("start")),
    }
    nxt = "pipeline_status" if a.get("start") else None
    warn = None if a.get("start") else "Not started — confirm to launch."
    return Envelope(result=result, next=nxt, warn=warn)


_INTENTS: dict[str, tuple[list[Slot], Callable[[dict], Envelope]]] = {
    "hx_start": (_START_SLOTS, _resolve_start),
}


def step(
    intent: str,
    session: str | None = None,
    answers: dict | None = None,
) -> Envelope:
    """Advance an intent. Returns an ``Envelope`` with ``ask`` (more input
    needed) or ``result`` (done)."""
    if intent not in _INTENTS:
        return Envelope(warn=f"Unknown intent '{intent}'")
    slots, resolve = _INTENTS[intent]

    s = SESSIONS.get(session) if session else None
    if s is None:
        s = SESSIONS.open(intent)
    by_key = {sl.key: sl for sl in slots}

    warn = None
    for key, raw in (answers or {}).items():
        sl = by_key.get(key)
        if sl is None or not sl.when(s.answers):
            continue
        try:
            s.answers[key] = validate_answer(sl.build(s), raw)
        except AnswerError as e:
            warn = f"{key}: {e}"
    SESSIONS.update(s.id, {})  # refresh TTL

    for sl in slots:
        if not sl.when(s.answers) or sl.key in s.answers:
            continue
        return Envelope(ask=Ask(s.id, [sl.build(s)]), next=intent, warn=warn)

    SESSIONS.close(s.id)
    return resolve(s.answers)
