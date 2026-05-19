"""LLM call chokepoint. Every model call funnels through here.

Sampling-only: the model is driven by the MCP client (it picks the model,
holds the credentials, and pays). ``call_llm`` is wired to MCP
``sampling/createMessage`` in Phase 1. Until then it raises a clear error;
tests patch ``helix.core.agents.call_llm_json`` so they never reach it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    content: str
    usage: dict[str, int]
    cost: float


def call_llm(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> LLMResponse:
    """Sampling-only: delegate to whatever client IO is bound for this run
    (the MCP client's model under sampling). Raises a clear error if nothing
    is bound. Tests patch ``helix.core.agents.call_llm_json`` above this."""
    from .io import current

    return current().sample(system=system, user=user, max_tokens=max_tokens)


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


def call_llm_json(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> tuple[dict[str, Any], int]:
    """LLM call expecting JSON. Returns ``(parsed_dict, tokens)``.

    Sampling never reports usage to the server, so ``tokens`` is an estimate
    (≈ chars/4) of the prompt + response the server itself handled — enough
    to bound a run."""
    resp = call_llm(
        model=model,
        system=system + "\n\nYou MUST respond with valid JSON only. No "
        "markdown fences, no explanation outside the JSON object.",
        user=user,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    text = resp.content.strip()
    if text.startswith("```"):
        text = "\n".join(
            l for l in text.split("\n") if not l.strip().startswith("```")
        )
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        block = _extract_json_block(text)
        try:
            parsed = json.loads(block) if block is not None else None
        except json.JSONDecodeError:
            parsed = None
        if parsed is None:
            log.warning("LLM returned invalid JSON, wrapping as raw content")
            parsed = {"raw": text}
    tokens = resp.usage.get("total_tokens") or resp.usage.get("total") or (
        (len(system) + len(user) + len(resp.content)) // 4
    )
    return parsed, int(tokens)
