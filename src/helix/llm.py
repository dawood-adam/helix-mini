"""LLM call chokepoint. Every model call funnels through here.

``cli/<engine>`` models route to ``llm_cli`` (a subprocess — no Python dep).
Everything else uses ``litellm``, imported lazily so the core/CLI path works
without the ``helix[sdk]`` extra installed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 120
DEFAULT_MAX_RETRIES = 3


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
    timeout: int | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> LLMResponse:
    if model.startswith("cli/"):
        from .llm_cli import call_cli_llm

        return call_cli_llm(
            model=model, system=system, user=user,
            temperature=temperature, max_tokens=max_tokens, timeout=timeout,
        )

    try:
        import litellm
    except ImportError as e:
        raise RuntimeError(
            f"Model '{model}' needs the litellm API path. Install it with "
            "'pip install helix[sdk]', or use a Claude subscription "
            "(claude setup-token) / --cli claude / --local."
        ) from e

    litellm.suppress_debug_info = True
    response = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        num_retries=max_retries,
    )
    content = response.choices[0].message.content or ""
    usage = {
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
    }
    cost = litellm.completion_cost(completion_response=response) or 0.0
    return LLMResponse(content=content, usage=usage, cost=cost)


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
) -> tuple[dict[str, Any], float]:
    """LLM call expecting JSON. Returns ``(parsed_dict, cost)``."""
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
    return parsed, resp.cost
