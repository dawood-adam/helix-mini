"""Configuration: repo-local paths, helix.toml, auth, model selection.

All path resolution lives here so the rest of the codebase never hardcodes a
location (Risk K). Defaults are repo-local: the Atlas and the ``.helix``
control directory live in the project folder unless overridden.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

try:
    import tomllib
except ImportError:  # pragma: no cover - py311 has tomllib
    import tomli as tomllib  # type: ignore[no-redef]

# --- Guardrail defaults (the only real bound on unbounded cycling) ----------
COST_CAP_DEFAULT = 10.0
CALL_CAP_DEFAULT = 60

# --- Paths ------------------------------------------------------------------


def project_root() -> Path:
    """The helix project directory. ``HELIX_HOME`` overrides the cwd."""
    return Path(os.environ.get("HELIX_HOME", Path.cwd())).resolve()


def helix_dir() -> Path:
    """``.helix/`` — snapshots, objects, refs, env. Created on demand."""
    d = project_root() / ".helix"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_env() -> None:
    for env in (helix_dir() / ".env", project_root() / ".env"):
        if env.exists():
            load_dotenv(env, override=False)
    load_dotenv(override=False)


def load_helix_toml() -> dict:
    """Parse ``<project>/helix.toml``; {} if absent or unreadable."""
    path = project_root() / "helix.toml"
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, ValueError):
        return {}


def atlas_path() -> Path:
    """Atlas root. ``helix.toml [atlas].path`` or repo-local ``./atlas``."""
    cfg = load_helix_toml().get("atlas", {})
    raw = os.environ.get("HELIX_ATLAS") or cfg.get("path") or "atlas"
    p = Path(raw)
    return p if p.is_absolute() else project_root() / p


def cost_cap() -> float:
    return float(load_helix_toml().get("limits", {}).get("cost_cap", COST_CAP_DEFAULT))


def call_cap_default() -> int:
    return int(load_helix_toml().get("limits", {}).get("call_cap", CALL_CAP_DEFAULT))


def ensure_helix_toml() -> Path:
    path = project_root() / "helix.toml"
    if not path.exists():
        path.write_text(
            '[atlas]\npath = "atlas"\n\n'
            f"[limits]\ncost_cap = {COST_CAP_DEFAULT}\n"
            f"call_cap = {CALL_CAP_DEFAULT}\n\n"
            '[default]\nmodel = "anthropic/claude-sonnet-4-20250514"\n\n'
            '[lightspeed]\nmodel = "anthropic/claude-haiku-4-5-20251001"\n'
        )
    return path


_load_env()

# --- Providers / auth (OAuth wins) ------------------------------------------

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

CLAUDE_CODE_OAUTH_ENV = "CLAUDE_CODE_OAUTH_TOKEN"
CLAUDE_NESTED_GUARD_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")

DEFAULT_CONFIG = {
    "default": {"model": "anthropic/claude-sonnet-4-20250514"},
    "lightspeed": {"model": "anthropic/claude-haiku-4-5-20251001"},
}


def claude_code_oauth_token() -> str | None:
    token = os.environ.get(CLAUDE_CODE_OAUTH_ENV)
    return token.strip() if token and token.strip() else None


def has_claude_code_oauth() -> bool:
    return claude_code_oauth_token() is not None


def has_api_key() -> bool:
    return any(os.environ.get(info["env_var"]) for info in PROVIDERS.values())


def claude_subprocess_env(
    strip: tuple[str, ...] = (), *, prefer_oauth: bool = False
) -> dict[str, str]:
    """Child env for spawning ``claude``. Strips nested-session guard vars;
    drops ANTHROPIC_API_KEY when an OAuth token is set so a stray key can't
    silently switch to pay-per-token billing. Scoped to the child only."""
    remove = set(CLAUDE_NESTED_GUARD_VARS) | set(strip)
    env = {k: v for k, v in os.environ.items() if k not in remove}
    token = claude_code_oauth_token()
    if prefer_oauth and token is not None:
        env.pop("ANTHROPIC_API_KEY", None)
        env[CLAUDE_CODE_OAUTH_ENV] = token
    return env


def validate_api_key(provider: str, api_key: str) -> bool:
    try:
        import litellm
    except ImportError as e:
        raise RuntimeError(
            "API-key validation needs litellm. Install: pip install 'helix[sdk]'"
        ) from e
    model = {
        "anthropic": "anthropic/claude-haiku-4-5-20251001",
        "openai": "openai/gpt-4o-mini",
    }.get(provider, f"{provider}/test")
    try:
        litellm.completion(
            model=model,
            messages=[{"role": "user", "content": "Say ok"}],
            max_tokens=5, timeout=15, api_key=api_key,
        )
        return True
    except Exception:
        return False


# --- Model selection --------------------------------------------------------

QWEN_SIZES = {
    "small": "ollama/qwen3:1.7b",
    "medium": "ollama/qwen3:8b",
    "large": "ollama/qwen3:32b",
}
DEFAULT_QWEN_SIZE = "medium"

# Stages that benefit from stronger models (used by --local-recommended).
CLOUD_STAGES = {"critic_methods", "planner", "critic_results"}
# LLM-backed stages (validator is deterministic). Used for the call-count
# guardrail; the agent loader confirms this from frontmatter at runtime.
LLM_STAGES = {"scout", "critic_methods", "planner", "builder", "critic_results"}


@dataclass
class ModelConfig:
    model: str
    stage_overrides: dict[str, str] = field(default_factory=dict)

    def model_for_stage(self, stage: str) -> str:
        return self.stage_overrides.get(stage, self.model)

    @classmethod
    def load(cls, lightspeed: bool = False) -> ModelConfig:
        profile = "lightspeed" if lightspeed else "default"
        cfg = load_helix_toml()
        section = cfg.get(profile, cfg.get("default", {}))
        return cls(model=section.get("model", DEFAULT_CONFIG[profile]["model"]))

    @classmethod
    def local(cls, size: str = DEFAULT_QWEN_SIZE) -> ModelConfig:
        return cls(model=QWEN_SIZES.get(size, QWEN_SIZES[DEFAULT_QWEN_SIZE]))

    @classmethod
    def cli(cls, engine: str = "claude", native_model: str | None = None) -> ModelConfig:
        return cls(model=f"cli/{engine}" + (f":{native_model}" if native_model else ""))

    @classmethod
    def local_recommended(
        cls, size: str = DEFAULT_QWEN_SIZE, lightspeed: bool = False
    ) -> ModelConfig:
        local_model = QWEN_SIZES.get(size, QWEN_SIZES[DEFAULT_QWEN_SIZE])
        cloud = DEFAULT_CONFIG["lightspeed" if lightspeed else "default"]["model"]
        return cls(model=local_model, stage_overrides={s: cloud for s in CLOUD_STAGES})

    @classmethod
    def default(cls, lightspeed: bool = False) -> ModelConfig | None:
        """Resolve the engine when no flag is given. OAuth wins: a Claude
        subscription token routes every stage through ``cli/claude`` even if
        an API key is also set. ``None`` = nothing configured."""
        if has_claude_code_oauth():
            return cls.cli("claude", native_model="haiku" if lightspeed else None)
        if has_api_key():
            return cls.load(lightspeed=lightspeed)
        return None

    def call_cap(self) -> int:
        from .llm_cli import call_cap_for

        return call_cap_for(self.model, list(self.stage_overrides.values()))
