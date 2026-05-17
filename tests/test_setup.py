"""Tests for setup, .env loading, and Docker sandbox module."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from helix_mini.config import (
    CLOUD_STAGES,
    LOCAL_RECOMMENDED_STAGES,
    PROVIDERS,
    QWEN_SIZES,
    ModelConfig,
    has_api_key,
)


class TestProviderConfig:
    def test_providers_defined(self):
        assert "anthropic" in PROVIDERS
        assert "openai" in PROVIDERS

    def test_provider_has_required_fields(self):
        for name, info in PROVIDERS.items():
            assert "env_var" in info
            assert "default_model" in info
            assert "lightspeed_model" in info


class TestHasApiKey:
    def test_no_key(self, monkeypatch: object):
        for info in PROVIDERS.values():
            monkeypatch.delenv(info["env_var"], raising=False)  # type: ignore[attr-defined]
        assert has_api_key() is False

    def test_with_anthropic_key(self, monkeypatch: object):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")  # type: ignore[attr-defined]
        assert has_api_key() is True


class TestModelConfig:
    def test_default_model_for_stage(self):
        mc = ModelConfig(model="anthropic/claude-sonnet-4-20250514")
        assert mc.model_for_stage("scout") == "anthropic/claude-sonnet-4-20250514"
        assert mc.model_for_stage("planner") == "anthropic/claude-sonnet-4-20250514"

    def test_stage_overrides(self):
        mc = ModelConfig(
            model="ollama/qwen3:8b",
            stage_overrides={"planner": "anthropic/claude-sonnet-4-20250514"},
        )
        assert mc.model_for_stage("scout") == "ollama/qwen3:8b"
        assert mc.model_for_stage("planner") == "anthropic/claude-sonnet-4-20250514"

    def test_local_config(self):
        mc = ModelConfig.local("small")
        assert mc.model == QWEN_SIZES["small"]
        assert mc.stage_overrides == {}

    def test_local_default_size(self):
        mc = ModelConfig.local()
        assert mc.model == QWEN_SIZES["medium"]

    def test_local_recommended_config(self):
        mc = ModelConfig.local_recommended("small")
        assert mc.model == QWEN_SIZES["small"]
        # Critical stages should use cloud model
        for stage in CLOUD_STAGES:
            assert mc.model_for_stage(stage) != QWEN_SIZES["small"]
        # Simple stages should use local model
        for stage in LOCAL_RECOMMENDED_STAGES:
            assert mc.model_for_stage(stage) == QWEN_SIZES["small"]

    def test_local_recommended_lightspeed(self):
        mc = ModelConfig.local_recommended("medium", lightspeed=True)
        # Lightspeed should use cheaper cloud model for critical stages
        for stage in CLOUD_STAGES:
            assert "haiku" in mc.model_for_stage(stage)


class TestDockerSandbox:
    def test_collect_env_vars(self, monkeypatch: object):
        from helix_mini.docker import _collect_env_vars

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")  # type: ignore[attr-defined]
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # type: ignore[attr-defined]
        args = _collect_env_vars()
        assert "-e" in args
        # Only the var NAME should appear, never the value (security fix)
        assert "ANTHROPIC_API_KEY" in args
        assert "sk-test" not in " ".join(args)

    def test_collect_env_vars_empty(self, monkeypatch: object):
        for info in PROVIDERS.values():
            monkeypatch.delenv(info["env_var"], raising=False)  # type: ignore[attr-defined]
        from helix_mini.docker import _collect_env_vars

        args = _collect_env_vars()
        assert args == []
