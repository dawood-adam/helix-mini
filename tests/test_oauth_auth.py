"""Claude subscription auth (CLAUDE_CODE_OAUTH_TOKEN) across the engines.

`claude setup-token` mints a long-lived OAuth token; when set, the bundled
`claude` CLI used by the cli/claude engine and the Agent SDK runs on the
user's subscription rate limits instead of API billing.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from helix_mini.agent_sdk import claude_code_auth
from helix_mini.config import (
    ModelConfig,
    claude_code_oauth_token,
    has_claude_code_oauth,
)
from helix_mini.llm_cli import call_cli_llm

CLAUDE_JSON = json.dumps(
    {"is_error": False, "result": "ok", "total_cost_usd": 0.0,
     "usage": {"input_tokens": 1, "output_tokens": 1}}
)


def _completed(stdout: str):
    return SimpleNamespace(stdout=stdout, stderr="", returncode=0)


class TestTokenHelpers:
    def test_unset(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        assert claude_code_oauth_token() is None
        assert has_claude_code_oauth() is False

    def test_set(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "  tok-123  ")
        assert claude_code_oauth_token() == "tok-123"
        assert has_claude_code_oauth() is True

    def test_blank_is_none(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "   ")
        assert claude_code_oauth_token() is None
        assert has_claude_code_oauth() is False


class TestCliEngineAuth:
    @patch("helix_mini.llm_cli.shutil.which", return_value="/usr/bin/claude")
    @patch("helix_mini.llm_cli.subprocess.run")
    def test_token_drops_api_key_for_claude(self, mock_run, _which, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-be-used")
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok-xyz")
        mock_run.return_value = _completed(CLAUDE_JSON)

        call_cli_llm(model="cli/claude", system="s", user="u")

        env = mock_run.call_args.kwargs["env"]
        assert env.get("CLAUDE_CODE_OAUTH_TOKEN") == "tok-xyz"
        assert "ANTHROPIC_API_KEY" not in env

    @patch("helix_mini.llm_cli.shutil.which", return_value="/usr/bin/claude")
    @patch("helix_mini.llm_cli.subprocess.run")
    def test_api_key_preserved_without_token(self, mock_run, _which, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real")
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        mock_run.return_value = _completed(CLAUDE_JSON)

        call_cli_llm(model="cli/claude", system="s", user="u")

        env = mock_run.call_args.kwargs["env"]
        assert env.get("ANTHROPIC_API_KEY") == "sk-real"

    @patch("helix_mini.llm_cli.shutil.which", return_value="/usr/bin/x")
    @patch("helix_mini.llm_cli.subprocess.run")
    def test_generic_engine_does_not_drop_api_key(
        self, mock_run, _which, tmp_path: Path, monkeypatch
    ):
        # A custom engine without uses_claude_code_auth must not touch the key.
        (tmp_path / "config.toml").write_text(
            '[cli.plain]\nbin = "x"\noutput_format = "text"\n'
        )
        monkeypatch.setattr("helix_mini.config.settings.HELIX_HOME", tmp_path)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real")
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok-xyz")
        mock_run.return_value = _completed("hello")

        call_cli_llm(model="cli/plain", system="s", user="u")

        env = mock_run.call_args.kwargs["env"]
        assert env.get("ANTHROPIC_API_KEY") == "sk-real"


class TestAgentSdkAuth:
    def test_no_token_is_noop(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        assert claude_code_auth() == ({}, [])

    def test_token_passes_and_drops_api_key(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok-abc")
        env, drop = claude_code_auth()
        assert env == {"CLAUDE_CODE_OAUTH_TOKEN": "tok-abc"}
        assert drop == ["ANTHROPIC_API_KEY"]


class TestDefaultResolver:
    """ModelConfig.default(): OAuth wins, then API key, else None."""

    def _clear(self, monkeypatch):
        for v in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(v, raising=False)

    def test_oauth_token_selects_cli_claude(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
        assert ModelConfig.default().model == "cli/claude"
        assert ModelConfig.default(lightspeed=True).model == "cli/claude:haiku"

    def test_oauth_wins_over_api_key(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-also-set")
        assert ModelConfig.default().model == "cli/claude"

    def test_api_key_used_when_no_token(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-only")
        model = ModelConfig.default().model
        assert not model.startswith("cli/")
        assert "claude" in model

    def test_none_when_nothing_configured(self, monkeypatch):
        self._clear(monkeypatch)
        assert ModelConfig.default() is None


class TestDockerPassthrough:
    def test_token_forwarded_into_container(self, monkeypatch):
        from helix_mini.docker import _collect_env_vars

        for info_var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(info_var, raising=False)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok-docker")

        args = _collect_env_vars()
        # Name-only form: the secret value must never enter argv.
        assert args == ["-e", "CLAUDE_CODE_OAUTH_TOKEN"]
        assert not any("tok-docker" in a for a in args)

    def test_token_and_api_key_both_forwarded(self, monkeypatch):
        from helix_mini.docker import _collect_env_vars

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-1")
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok-2")
        args = _collect_env_vars()
        assert "ANTHROPIC_API_KEY" in args
        assert "CLAUDE_CODE_OAUTH_TOKEN" in args
        # No value is ever embedded in the docker args.
        assert not any("=" in a for a in args)
        assert not any("sk-1" in a or "tok-2" in a for a in args)
