"""Model configuration and selection."""

from __future__ import annotations

from dataclasses import dataclass, field

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from .settings import DEFAULT_CONFIG, HELIX_HOME

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
        config_path = HELIX_HOME / "config.toml"
        profile = "lightspeed" if lightspeed else "default"

        if config_path.exists():
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
            section = config.get(profile, config.get("default", {}))
            return cls(model=section.get("model", DEFAULT_CONFIG[profile]["model"]))

        return cls(model=DEFAULT_CONFIG[profile]["model"])

    @classmethod
    def local(cls, size: str = DEFAULT_QWEN_SIZE) -> ModelConfig:
        """Create config using a local Qwen model for all stages."""
        model = QWEN_SIZES.get(size, QWEN_SIZES[DEFAULT_QWEN_SIZE])
        return cls(model=model)

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
