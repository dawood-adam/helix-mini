"""Tests for the CLI-backed LLM engine — fully mocked, no real CLI spawned."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from helix_mini.config import ModelConfig
from helix_mini.llm_cli import (
    DEFAULT_CLI_CALL_CAP,
    CLIEngineError,
    call_cap_for,
    call_cli_llm,
    engine_reports_cost,
    get_engine,
    parse_cli_model,
)


def _completed(stdout: str, returncode: int = 0, stderr: str = ""):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


CLAUDE_JSON = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": '{"verdict": "ship"}',
        "session_id": "abc",
        "total_cost_usd": 0.0123,
        "usage": {"input_tokens": 100, "output_tokens": 42},
        "num_turns": 1,
    }
)


class TestParseAndResolve:
    def test_parse_plain(self):
        assert parse_cli_model("cli/claude") == ("claude", None)

    def test_parse_with_native_model(self):
        assert parse_cli_model("cli/claude:opus") == ("claude", "opus")

    def test_builtin_claude_engine(self):
        eng = get_engine("claude")
        assert eng.bin == "claude"
        assert eng.reports_cost is True
        assert eng.uses_claude_code_auth is True

    def test_unknown_engine_raises(self):
        with pytest.raises(CLIEngineError, match="Unknown CLI engine"):
            get_engine("nope")

    def test_config_defined_engine(self, tmp_path: Path, monkeypatch):
        (tmp_path / "config.toml").write_text(
            '[cli.dummy]\nbin = "echo"\noutput_format = "text"\n'
        )
        monkeypatch.setattr("helix_mini.config.settings.HELIX_HOME", tmp_path)
        eng = get_engine("dummy")
        assert eng.bin == "echo"
        assert eng.output_format == "text"
        assert eng.reports_cost is False

    def test_builtin_wins_over_config(self, tmp_path: Path, monkeypatch):
        (tmp_path / "config.toml").write_text('[cli.claude]\nbin = "hacked"\n')
        monkeypatch.setattr("helix_mini.config.settings.HELIX_HOME", tmp_path)
        assert get_engine("claude").bin == "claude"


class TestCallCliLlm:
    @patch("helix_mini.llm_cli.shutil.which", return_value="/usr/bin/claude")
    @patch("helix_mini.llm_cli.subprocess.run")
    def test_claude_json_parsed(self, mock_run, _which):
        mock_run.return_value = _completed(CLAUDE_JSON)
        resp = call_cli_llm(
            model="cli/claude:haiku", system="SYS", user="USR"
        )
        assert resp.content == '{"verdict": "ship"}'
        assert resp.cost == pytest.approx(0.0123)
        assert resp.usage == {"prompt_tokens": 100, "completion_tokens": 42}

        args, kwargs = mock_run.call_args
        argv = args[0]
        assert argv[0] == "claude"
        assert "--output-format" in argv and "json" in argv
        assert "--max-turns" in argv
        assert argv[argv.index("--model") + 1] == "haiku"
        assert argv[argv.index("--append-system-prompt") + 1] == "SYS"
        assert kwargs["input"] == "USR"  # prompt via stdin

    @patch("helix_mini.llm_cli.shutil.which", return_value="/usr/bin/claude")
    @patch("helix_mini.llm_cli.subprocess.run")
    def test_claudecode_stripped_from_child_env(self, mock_run, _which, monkeypatch):
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
        monkeypatch.setenv("KEEP_ME", "yes")
        mock_run.return_value = _completed(CLAUDE_JSON)

        call_cli_llm(model="cli/claude", system="s", user="u")

        env = mock_run.call_args.kwargs["env"]
        assert "CLAUDECODE" not in env
        assert "CLAUDE_CODE_ENTRYPOINT" not in env
        assert env.get("KEEP_ME") == "yes"

    @patch("helix_mini.llm_cli.shutil.which", return_value="/usr/bin/claude")
    @patch("helix_mini.llm_cli.subprocess.run")
    def test_is_error_flag_raises(self, mock_run, _which):
        mock_run.return_value = _completed(
            json.dumps({"is_error": True, "result": "rate limited"})
        )
        with pytest.raises(CLIEngineError, match="reported an error"):
            call_cli_llm(model="cli/claude", system="s", user="u")

    @patch("helix_mini.llm_cli.shutil.which", return_value="/usr/bin/x")
    @patch("helix_mini.llm_cli.subprocess.run")
    def test_text_engine_via_config(self, mock_run, _which, tmp_path, monkeypatch):
        (tmp_path / "config.toml").write_text(
            '[cli.plain]\nbin = "x"\nprompt_via = "arg"\noutput_format = "text"\n'
        )
        monkeypatch.setattr("helix_mini.config.settings.HELIX_HOME", tmp_path)
        mock_run.return_value = _completed("  hello world  \n")

        resp = call_cli_llm(model="cli/plain", system="SYS", user="USR")
        assert resp.content == "hello world"
        assert resp.cost == 0.0
        # No system flag -> system is prepended into the prompt arg.
        argv = mock_run.call_args.args[0]
        assert argv[-1] == "SYS\n\n---\n\nUSR"

    @patch("helix_mini.llm_cli.shutil.which", return_value="/usr/bin/claude")
    @patch("helix_mini.llm_cli.subprocess.run")
    def test_nonzero_exit_raises(self, mock_run, _which):
        mock_run.return_value = _completed("", returncode=2, stderr="boom")
        with pytest.raises(CLIEngineError, match="exited 2"):
            call_cli_llm(model="cli/claude", system="s", user="u")

    @patch("helix_mini.llm_cli.shutil.which", return_value="/usr/bin/claude")
    @patch("helix_mini.llm_cli.subprocess.run")
    def test_timeout_raises(self, mock_run, _which):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=1)
        with pytest.raises(CLIEngineError, match="timed out"):
            call_cli_llm(model="cli/claude", system="s", user="u")

    @patch("helix_mini.llm_cli.shutil.which", return_value=None)
    def test_missing_binary_raises(self, _which):
        with pytest.raises(CLIEngineError, match="not on PATH"):
            call_cli_llm(model="cli/claude", system="s", user="u")

    @patch("helix_mini.llm_cli.shutil.which", return_value="/usr/bin/claude")
    @patch("helix_mini.llm_cli.subprocess.run")
    def test_invalid_json_raises(self, mock_run, _which):
        mock_run.return_value = _completed("not json at all")
        with pytest.raises(CLIEngineError, match="did not return valid JSON"):
            call_cli_llm(model="cli/claude", system="s", user="u")


class TestRouting:
    @patch("helix_mini.llm.litellm.completion")
    @patch("helix_mini.llm_cli.call_cli_llm")
    def test_cli_model_routes_to_cli_not_litellm(self, mock_cli, mock_litellm):
        from helix_mini.llm import LLMResponse, call_llm

        mock_cli.return_value = LLMResponse(content="ok", usage={}, cost=0.0)
        out = call_llm(model="cli/claude", system="s", user="u")

        assert out.content == "ok"
        mock_cli.assert_called_once()
        mock_litellm.assert_not_called()

    @patch("helix_mini.llm_cli.shutil.which", return_value="/usr/bin/claude")
    @patch("helix_mini.llm_cli.subprocess.run")
    def test_call_llm_json_through_cli(self, mock_run, _which):
        from helix_mini.llm import call_llm_json

        mock_run.return_value = _completed(CLAUDE_JSON)
        parsed, cost = call_llm_json(model="cli/claude", system="s", user="u")
        assert parsed == {"verdict": "ship"}
        assert cost == pytest.approx(0.0123)

    @patch("helix_mini.llm_cli.call_cli_llm")
    def test_cli_timeout_not_clamped_by_api_default(self, mock_cli):
        # Regression: the 120s litellm default must NOT be forced onto the CLI
        # engine (which has its own 600s). call_llm must forward timeout=None
        # so call_cli_llm falls back to eng.timeout.
        from helix_mini.llm import LLMResponse, call_llm

        mock_cli.return_value = LLMResponse(content="ok", usage={}, cost=0.0)
        call_llm(model="cli/claude", system="s", user="u")
        assert mock_cli.call_args.kwargs["timeout"] is None

        call_llm(model="cli/claude", system="s", user="u", timeout=42)
        assert mock_cli.call_args.kwargs["timeout"] == 42


class TestJsonSalvage:
    def test_extract_plain_object(self):
        from helix_mini.llm import _extract_json_block

        assert _extract_json_block('{"a": 1}') == '{"a": 1}'

    def test_extract_from_prose(self):
        from helix_mini.llm import _extract_json_block

        block = _extract_json_block(
            'Sure! Here is the result:\n{"verdict": "ship", "n": 2}\nHope it helps.'
        )
        assert json.loads(block) == {"verdict": "ship", "n": 2}

    def test_braces_inside_strings_not_miscounted(self):
        from helix_mini.llm import _extract_json_block

        src = 'x {"code": "if (a) { return [1]; }", "ok": true} y'
        assert json.loads(_extract_json_block(src)) == {
            "code": "if (a) { return [1]; }", "ok": True
        }

    def test_no_json_returns_none(self):
        from helix_mini.llm import _extract_json_block

        assert _extract_json_block("no json here at all") is None

    def test_call_llm_json_salvages_prose_wrapped(self, monkeypatch):
        from helix_mini import llm
        from helix_mini.llm import LLMResponse, call_llm_json

        monkeypatch.setattr(
            llm, "call_llm",
            lambda **kw: LLMResponse(
                content='Here is the JSON:\n{"artifacts": [], "verdict": "iterate"}\nDone.',
                usage={}, cost=0.0),
        )
        parsed, _ = call_llm_json(model="cli/claude", system="s", user="u")
        assert parsed == {"artifacts": [], "verdict": "iterate"}

    def test_call_llm_json_raw_fallback_when_unsalvageable(self, monkeypatch):
        from helix_mini import llm
        from helix_mini.llm import LLMResponse, call_llm_json

        monkeypatch.setattr(
            llm, "call_llm",
            lambda **kw: LLMResponse(content="totally not json", usage={}, cost=0.0),
        )
        parsed, _ = call_llm_json(model="x/y", system="s", user="u")
        assert parsed == {"raw": "totally not json"}


class TestModelConfigAndCaps:
    def test_model_config_cli(self):
        assert ModelConfig.cli("claude").model == "cli/claude"
        assert ModelConfig.cli("claude", "opus").model == "cli/claude:opus"

    def test_claude_reports_cost_so_no_call_cap(self):
        assert engine_reports_cost("cli/claude") is True
        assert call_cap_for("cli/claude") == 0
        assert ModelConfig.cli("claude").call_cap() == 0

    def test_api_model_no_call_cap(self):
        assert call_cap_for("anthropic/claude-sonnet-4-20250514") == 0

    def test_non_cost_engine_triggers_call_cap(self, tmp_path, monkeypatch):
        (tmp_path / "config.toml").write_text(
            '[cli.plain]\nbin = "x"\noutput_format = "text"\n'
        )
        monkeypatch.setattr("helix_mini.config.settings.HELIX_HOME", tmp_path)
        assert engine_reports_cost("cli/plain") is False
        assert call_cap_for("cli/plain") == DEFAULT_CLI_CALL_CAP
        assert ModelConfig.cli("plain").call_cap() == DEFAULT_CLI_CALL_CAP


class TestGraphCaps:
    def test_call_cap_halts_pipeline(self):
        from helix_mini.pipeline.graph import CostCapExceeded, _check_caps
        from helix_mini.pipeline.state import ForgeState

        s = ForgeState(
            call_cap=2,
            completed_stages=["scout", "critic_methods"],
        )
        with pytest.raises(CostCapExceeded, match="call cap"):
            _check_caps(s)

    def test_call_cap_allows_under_limit(self):
        from helix_mini.pipeline.graph import _check_caps
        from helix_mini.pipeline.state import ForgeState

        _check_caps(ForgeState(call_cap=5, completed_stages=["scout", "validator"]))

    def test_inactive_call_cap_ignored(self):
        from helix_mini.pipeline.graph import _check_caps
        from helix_mini.pipeline.state import ForgeState

        _check_caps(
            ForgeState(call_cap=0, completed_stages=["scout"] * 50)
        )

    def test_cost_cap_still_enforced(self):
        from helix_mini.pipeline.graph import CostCapExceeded, _check_caps
        from helix_mini.pipeline.state import ForgeState

        with pytest.raises(CostCapExceeded, match="Cost cap"):
            _check_caps(ForgeState(cost_so_far=5.0, cost_cap=5.0))


@pytest.mark.skipif(
    os.environ.get("HELIX_CLI_IT") != "1",
    reason="live Claude CLI integration test; set HELIX_CLI_IT=1 to run "
    "(must NOT be run nested inside a Claude Code session)",
)
class TestLiveClaude:
    def test_real_claude_roundtrip(self):
        resp = call_cli_llm(
            model="cli/claude:haiku",
            system="You are terse.",
            user="Reply with exactly the word: OK",
        )
        assert "OK" in resp.content
        assert resp.cost >= 0.0
