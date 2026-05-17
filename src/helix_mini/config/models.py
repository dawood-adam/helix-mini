"""Model configuration and selection."""

from __future__ import annotations

from dataclasses import dataclass, field

from .settings import DEFAULT_CONFIG, load_config_toml

QWEN_SIZES = {
    "small": "ollama/qwen3:1.7b",
    "medium": "ollama/qwen3:8b",
    "large": "ollama/qwen3:32b",
}

DEFAULT_QWEN_SIZE = "medium"

# Stages where local models perform well enough (simpler tasks)
LOCAL_RECOMMENDED_STAGES = {"scout", "builder", "validator"}
# Stages that benefit from stronger models (critical reasoning)
CLOUD_STAGES = {"critic_methods", "planner", "critic_results"}
# Stages that actually invoke an LLM (validator is deterministic). Used to
# enforce the call-count guardrail when an engine doesn't report cost.
LLM_STAGES = {"scout", "critic_methods", "planner", "builder", "critic_results"}


@dataclass
class ModelConfig:
    model: str
    stage_overrides: dict[str, str] = field(default_factory=dict)

    def model_for_stage(self, stage: str) -> str:
        """Get the model to use for a specific pipeline stage."""
        return self.stage_overrides.get(stage, self.model)

    @classmethod
    def load(cls, lightspeed: bool = False) -> ModelConfig:
        """Load model config from config.toml or use defaults."""
        profile = "lightspeed" if lightspeed else "default"
        config = load_config_toml()
        section = config.get(profile, config.get("default", {}))
        return cls(model=section.get("model", DEFAULT_CONFIG[profile]["model"]))

    @classmethod
    def local(cls, size: str = DEFAULT_QWEN_SIZE) -> ModelConfig:
        """Create config using a local Qwen model for all stages."""
        model = QWEN_SIZES.get(size, QWEN_SIZES[DEFAULT_QWEN_SIZE])
        return cls(model=model)

    @classmethod
    def cli(cls, engine: str = "claude", native_model: str | None = None) -> ModelConfig:
        """Pilot every stage through an LLM CLI engine (e.g. Claude Code).

        No API key required — the CLI handles its own auth.
        """
        model = f"cli/{engine}" + (f":{native_model}" if native_model else "")
        return cls(model=model)

    @classmethod
    def default(cls, lightspeed: bool = False) -> ModelConfig | None:
        """Resolve the default engine when no flag was given.

        Precedence (OAuth wins): a Claude Code OAuth token routes every stage
        through the subscription-backed ``cli/claude`` engine — even if an API
        key is also set, so a stray key can't silently switch to API billing.
        Otherwise fall back to the API-key litellm path. ``None`` means neither
        is configured (caller decides how to handle that).
        """
        from . import providers

        if providers.has_claude_code_oauth():
            return cls.cli("claude", native_model="haiku" if lightspeed else None)
        if providers.has_api_key():
            return cls.load(lightspeed=lightspeed)
        return None

    def call_cap(self) -> int:
        """Max LLM calls per run when cost isn't reported; 0 = use cost cap."""
        from ..llm_cli import call_cap_for

        return call_cap_for(self.model, list(self.stage_overrides.values()))

    @classmethod
    def local_recommended(
        cls,
        size: str = DEFAULT_QWEN_SIZE,
        lightspeed: bool = False,
    ) -> ModelConfig:
        """Hybrid: local Qwen for simple stages, cloud model for critical stages."""
        local_model = QWEN_SIZES.get(size, QWEN_SIZES[DEFAULT_QWEN_SIZE])
        cloud_profile = "lightspeed" if lightspeed else "default"
        cloud_model = DEFAULT_CONFIG[cloud_profile]["model"]
        overrides = {stage: cloud_model for stage in CLOUD_STAGES}
        return cls(model=local_model, stage_overrides=overrides)
