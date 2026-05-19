"""The one standardized client-IO seam.

Everything Helix sends *up* to the MCP client goes through here, with a
single typed vocabulary:

- ``sample(...)``  — ask the client's model to think (MCP ``sampling``)
- ``elicit(...)``  — ask the client's user a structured question (MCP
  ``elicitation``)

Both share the identical hard problem (sync pipeline core ↔ async MCP
session), so they share one seam. Components never craft raw JSON schemas or
hand-roll prompts — they call ``ask_text/ask_choice/ask_multi/ask_confirm``
and get a spec-compliant flat schema. The active implementation is bound for
the duration of a run via :func:`use` and reached anywhere via
:func:`current`, so nothing has to thread it through call signatures.

This module is pure: it imports neither ``mcp`` nor ``anyio``. Core stays
dependency-light; only ``helix.mcp.*`` touches the SDK.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

# --- Elicitation value objects ---------------------------------------------


@dataclass
class ElicitRequest:
    """A question for the user + the flat JSON schema of the answer."""

    message: str
    schema: dict


@dataclass
class ElicitResult:
    action: Literal["accept", "decline", "cancel"]
    data: dict = field(default_factory=dict)


class Declined(Exception):
    """The user declined or cancelled a required elicitation.

    Standardized across Helix: any component that needs an answer raises
    this on non-accept; the orchestrator turns it into a resumable pause
    (mirrors the cost-ceiling pause)."""


# --- Typed schema builders (the "almost programmatic" vocabulary) ----------
#
# MCP elicitation schemas are intentionally flat: a single object whose
# properties are primitives / enums / arrays of enums. These builders are the
# ONLY place schemas are constructed, so every prompt in Helix is uniform.


def _obj(field_name: str, prop: dict) -> dict:
    return {
        "type": "object",
        "properties": {field_name: prop},
        "required": [field_name],
    }


def ask_text(message: str, field_name: str = "value", *, pattern: str | None = None) -> ElicitRequest:
    prop: dict[str, Any] = {"type": "string"}
    if pattern:
        prop["pattern"] = pattern
    return ElicitRequest(message, _obj(field_name, prop))


def ask_choice(message: str, options: list[str], field_name: str = "choice") -> ElicitRequest:
    return ElicitRequest(message, _obj(field_name, {"type": "string", "enum": list(options)}))


def ask_multi(message: str, options: list[str], field_name: str = "choices") -> ElicitRequest:
    return ElicitRequest(message, _obj(field_name, {
        "type": "array",
        "items": {"type": "string", "enum": list(options)},
        "uniqueItems": True,
    }))


def ask_confirm(message: str, field_name: str = "proceed") -> ElicitRequest:
    return ElicitRequest(message, _obj(field_name, {"type": "boolean"}))


# --- The seam ---------------------------------------------------------------


@runtime_checkable
class ClientIO(Protocol):
    """What the MCP client offers back to the server. One per active run."""

    def sample(self, *, system: str, user: str, max_tokens: int) -> Any:
        """Run an LLM completion on the client. Returns an ``LLMResponse``
        (typed as Any here to avoid importing llm at module load)."""

    def elicit(self, req: ElicitRequest) -> ElicitResult:
        """Ask the user a structured question on the client."""


_IO: contextvars.ContextVar[ClientIO | None] = contextvars.ContextVar(
    "helix_client_io", default=None
)


def current() -> ClientIO:
    io = _IO.get()
    if io is None:
        raise RuntimeError(
            "No Helix client IO is bound. Helix runs through an MCP client "
            "(e.g. Claude Code) that provides sampling + elicitation; start "
            "it via the helix MCP server, not a bare process."
        )
    return io


@contextmanager
def use(io: ClientIO):
    """Bind ``io`` for the duration of a run (set by the MCP server)."""
    token = _IO.set(io)
    try:
        yield
    finally:
        _IO.reset(token)


# --- Adapter: standardized elicitation -> the pre-existing core HITL seam ---


def gate_asker(io: ClientIO):
    """Return a ``core.gates.Asker`` backed by standardized elicitation.

    This is the linchpin: ``core`` already abstracts "ask the human" as
    ``(GateReport) -> GateDecision``. Implementing it here means the WHOLE
    pipeline's human-in-the-loop runs through one standardized elicitation
    path with zero changes to core.
    """
    from .core.gates import GateDecision
    from .core.transitions import stages

    def ask(report) -> GateDecision:
        prompt = f"After {report.stage}: {report.decision}\n{report.rationale}"
        if report.note:
            prompt += f"\nNote: {report.note}"
        r = io.elicit(ask_choice(prompt, ["proceed", "send back", "stop"], "action"))
        if r.action != "accept":
            raise Declined()
        choice = (r.data or {}).get("action")
        if choice == "stop":
            return GateDecision("stop")
        if choice == "proceed":
            return GateDecision("proceed")
        tgt = io.elicit(ask_choice(
            "Send the run back to which stage?", list(stages()), "stage"))
        if tgt.action != "accept":
            raise Declined()
        fb = io.elicit(ask_text("Feedback for that stage (what to fix)", "note"))
        note = (fb.data or {}).get("note") if fb.action == "accept" else None
        return GateDecision("goto", (tgt.data or {}).get("stage"), note or None)

    return ask
