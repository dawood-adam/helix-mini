"""Provider registry and API key management."""

from __future__ import annotations

import os

PROVIDERS = {
    "anthropic": {
        "env_var": "ANTHROPIC_API_KEY",
        "default_model": "anthropic/claude-sonnet-4-20250514",
        "lightspeed_model": "anthropic/claude-haiku-4-5-20251001",
    },
    "openai": {
        "env_var": "OPENAI_API_KEY",
        "default_model": "openai/gpt-4o",
        "lightspeed_model": "openai/gpt-4o-mini",
    },
}


def has_api_key() -> bool:
    """Check if any supported API key is available."""
    return any(os.environ.get(info["env_var"]) for info in PROVIDERS.values())


def validate_api_key(provider: str, api_key: str) -> bool:
    """Quick validation that an API key works with a minimal LLM call."""
    import litellm

    model_map = {
        "anthropic": "anthropic/claude-haiku-4-5-20251001",
        "openai": "openai/gpt-4o-mini",
    }
    model = model_map.get(provider, f"{provider}/test")

    try:
        litellm.completion(
            model=model,
            messages=[{"role": "user", "content": "Say ok"}],
            max_tokens=5,
            timeout=15,
            api_key=api_key,
        )
        return True
    except Exception:
        return False


def validate_ollama(model: str = "") -> bool:
    """Check that Ollama is running and the model is available."""
    import litellm

    from .models import DEFAULT_QWEN_SIZE, QWEN_SIZES

    model = model or QWEN_SIZES[DEFAULT_QWEN_SIZE]
    try:
        litellm.completion(
            model=model,
            messages=[{"role": "user", "content": "Say ok"}],
            max_tokens=5,
            timeout=15,
        )
        return True
    except Exception:
        return False
