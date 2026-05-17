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

# Long-lived OAuth token minted by `claude setup-token`. When set, the bundled
# `claude` CLI (used by the cli/claude engine and the Agent SDK) authenticates
# against the user's Claude subscription rate limits instead of API billing.
# It is NOT an API key — litellm / the HTTP API cannot use it.
CLAUDE_CODE_OAUTH_ENV = "CLAUDE_CODE_OAUTH_TOKEN"


def claude_code_oauth_token() -> str | None:
    """Return the Claude Code OAuth token from the environment, if set."""
    token = os.environ.get(CLAUDE_CODE_OAUTH_ENV)
    return token.strip() if token and token.strip() else None


def has_claude_code_oauth() -> bool:
    """Whether subscription auth (claude setup-token) is configured."""
    return claude_code_oauth_token() is not None


# Stripping these lets a spawned `claude` run even when helix-mini is itself
# launched from Claude Code (the CLI refuses nested sessions otherwise).
CLAUDE_NESTED_GUARD_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


def claude_subprocess_env(
    strip: tuple[str, ...] = (), *, prefer_oauth: bool = False
) -> dict[str, str]:
    """Environment for spawning the `claude` binary as a subprocess.

    Removes the nested-session guard vars plus any extra ``strip``. When
    ``prefer_oauth`` and an OAuth token is set, drops ANTHROPIC_API_KEY so a
    stray API key can't silently switch the run to pay-per-token billing.
    Scoped to the child only — the parent process is untouched.
    """
    remove = set(CLAUDE_NESTED_GUARD_VARS) | set(strip)
    env = {k: v for k, v in os.environ.items() if k not in remove}
    token = claude_code_oauth_token()
    if prefer_oauth and token is not None:
        env.pop("ANTHROPIC_API_KEY", None)
        env[CLAUDE_CODE_OAUTH_ENV] = token
    return env


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
