"""Model-call chokepoint. Every stage model call funnels through here.

Agent-driven: Helix has no model of its own and holds no credentials. The
run binds a JSON *responder* (the step driver) and ``call_llm_json`` routes
through it — the responder either suspends the stage (``io.NeedsModel``, the
prompt goes to the client agent) or returns the agent's injected answer.
There is no server-side sampling. Tests bind a responder (or patch
``helix.core.agents.call_llm_json``).
"""

from __future__ import annotations

import contextvars
import json
import logging
from contextlib import contextmanager
from typing import Any, Callable

log = logging.getLogger(__name__)

# The model-acquisition seam. A run binds a "JSON responder" —
# ``(model, system, user) -> (parsed_dict, tokens_estimate)`` — and every
# stage's model call routes through it instead of sampling. Threaded via a
# contextvar like the IO seam (never a PipelineState field). Unbound = the
# legacy sampling path, so anything not driven through the step loop is
# unchanged. The agent-driven responder either raises ``io.NeedsModel`` to
# suspend the stage, or returns the client agent's injected answer.
JsonResponder = Callable[[str, str, str], "tuple[dict[str, Any], int]"]
_RESPONDER: contextvars.ContextVar[JsonResponder | None] = contextvars.ContextVar(
    "helix_json_responder", default=None
)


@contextmanager
def use_responder(fn: JsonResponder | None):
    """Bind the JSON responder for the duration of one ``advance`` step (set
    by the step driver). ``None`` is a no-op (keeps the legacy path)."""
    if fn is None:
        yield
        return
    token = _RESPONDER.set(fn)
    try:
        yield
    finally:
        _RESPONDER.reset(token)




def _extract_json_block(text: str) -> str | None:
    """First balanced top-level {...} or [...] substring (salvage from prose)."""
    start = next((i for i, c in enumerate(text) if c in "{["), None)
    if start is None:
        return None
    open_ch = text[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = escape = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


_JSON_DIRECTIVE = (
    "\n\nYou MUST respond with valid JSON only. No markdown fences, no "
    "explanation outside the JSON object."
)


def parse_json_text(text: str) -> Any:
    """Best-effort parse of a model/agent JSON reply: tolerate code fences,
    salvage the first balanced ``{...}``/``[...]``, else ``{"raw": text}``.
    Reused to parse the client agent's submitted answer in the step loop."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = "\n".join(
            l for l in text.split("\n") if not l.strip().startswith("```")
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        block = _extract_json_block(text)
        try:
            parsed = json.loads(block) if block is not None else None
        except json.JSONDecodeError:
            parsed = None
        if parsed is None:
            log.warning("LLM returned invalid JSON, wrapping as raw content")
            return {"raw": text}
        return parsed


def call_llm_json(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> tuple[dict[str, Any], int]:
    """Stage model call expecting JSON. Returns ``(parsed, tokens)``.

    Routes through the bound JSON responder if one is set (agent-driven: it
    may raise ``io.NeedsModel`` to suspend, or return the agent's answer);
    otherwise the legacy sampling path. ``tokens`` is an estimate (≈ chars/4)
    of prompt + response — enough to bound a run."""
    json_system = system + _JSON_DIRECTIVE

    responder = _RESPONDER.get()
    if responder is None:
        raise RuntimeError(
            "No model seam bound. Helix is agent-driven (no server-side "
            "sampling): drive the pipeline through hx_step / hx_submit so "
            "the client agent answers each stage. (Tests bind a responder "
            "or patch helix.core.agents.call_llm_json.)"
        )
    return responder(model, json_system, user)
