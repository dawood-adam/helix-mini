"""Thin LLM call wrapper using litellm."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import litellm

log = logging.getLogger(__name__)

# Suppress litellm noise
litellm.suppress_debug_info = True

# --- Guardrail defaults ---
DEFAULT_TIMEOUT = 120  # seconds
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
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> LLMResponse:
    """Make a single LLM call with timeout and retry protection."""
    if model.startswith("cli/"):
        from .llm_cli import call_cli_llm

        return call_cli_llm(
            model=model,
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    response = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        num_retries=max_retries,
    )

    content = response.choices[0].message.content or ""
    usage = {
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
    }
    cost = litellm.completion_cost(completion_response=response) or 0.0

    return LLMResponse(content=content, usage=usage, cost=cost)


def call_llm_json(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> tuple[dict[str, Any], float]:
    """Make an LLM call expecting JSON output. Returns (parsed_dict, cost)."""
    system_with_json = (
        system + "\n\nYou MUST respond with valid JSON only. No markdown fences, "
        "no explanation outside the JSON object."
    )

    resp = call_llm(
        model=model,
        system=system_with_json,
        user=user,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    # Strip markdown fences if present
    text = resp.content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        log.warning("LLM returned invalid JSON, wrapping as raw content")
        parsed = {"raw": text}

    return parsed, resp.cost
