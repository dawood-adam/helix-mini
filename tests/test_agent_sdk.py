"""Tests for the Claude Agent SDK integration.

claude-agent-sdk is an optional dependency and is NOT installed in CI, so the
module must import without it. These tests exercise the SDK-free surface: the
pure ``*_text`` helpers, the permission gate, and the missing-SDK error path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# These tests assert the actionable error when the optional SDK is absent;
# skip them when claude-agent-sdk happens to be installed in the environment.
_SDK_INSTALLED = importlib.util.find_spec("claude_agent_sdk") is not None

from helix_mini.agent_sdk import (
    RUN_TOOL,
    atlas_search_text,
    atlas_status_text,
    decision_log_text,
    run_agent,
    run_permission_decision,
    run_pipeline_text,
)
from helix_mini.atlas import Atlas, PageWrite
from helix_mini.pipeline.decisions import append_decision


def _seed_atlas(home: Path) -> None:
    atlas = Atlas(home / "atlas")
    atlas.write(
        [PageWrite("concepts/cardiac.md", "Cardiac Modeling",
                    "Heart simulation via CFD.", "Cardiac sim methods")],
        "seed | test",
    )


class TestAtlasHelpers:
    def test_search_no_atlas(self, tmp_path: Path):
        assert "No Atlas found" in atlas_search_text("anything", home=tmp_path)

    def test_search_hit_and_miss(self, tmp_path: Path):
        _seed_atlas(tmp_path)
        hit = atlas_search_text("Cardiac", home=tmp_path)
        assert "Cardiac Modeling" in hit
        assert "concepts/cardiac.md" in hit
        assert "No Atlas results" in atlas_search_text("zzz-nomatch", home=tmp_path)

    def test_status_no_atlas(self, tmp_path: Path):
        assert "No Atlas found" in atlas_status_text(home=tmp_path)

    def test_status_reports_pages_and_projects(self, tmp_path: Path):
        _seed_atlas(tmp_path)
        (tmp_path / "atlas" / "projects" / "proj-a").mkdir(parents=True)
        out = atlas_status_text(home=tmp_path)
        assert "Pages: 1" in out
        assert "proj-a" in out

    def test_decision_log_missing(self, tmp_path: Path):
        assert "No decision log" in decision_log_text("ghost", home=tmp_path)

    def test_decision_log_renders(self, tmp_path: Path):
        path = tmp_path / "atlas" / "projects" / "p" / ".decisions.json"
        append_decision(path, "scout", "found 2 approaches", "ingested sources")
        out = decision_log_text("p", home=tmp_path)
        assert "Decision Log" in out
        assert "found 2 approaches" in out


class TestRunPipelineTool:
    def test_folder_not_found(self, tmp_path: Path):
        out = run_pipeline_text(str(tmp_path / "nope"))
        assert out.startswith("Error: folder not found")

    def test_formats_results(self, tmp_path: Path):
        folder = tmp_path / "sources"
        folder.mkdir()

        fake_result = SimpleNamespace(
            project_name="sources", error=None,
            completed_stages=["scout", "planner", "builder"], cost_so_far=0.0123,
        )

        class FakeApp:
            def __init__(self, *a, **k): ...
            def run(self, *a, **k): return [fake_result]

        with patch("helix_mini.app.HelixMini", FakeApp), \
             patch("helix_mini.config.providers.has_api_key", return_value=True), \
             patch("helix_mini.config.providers.has_claude_code_oauth",
                   return_value=False):
            out = run_pipeline_text(str(folder), question="q", home=tmp_path)

        assert "sources: done (stages=3, cost=$0.0123)" in out

    @staticmethod
    def _capturing_app(captured: dict):
        class FakeApp:
            def __init__(self, *a, **k): ...
            def run(self, *a, **k):
                captured["model"] = k.get("model_config")
                return [SimpleNamespace(
                    project_name="p", error=None,
                    completed_stages=[], cost_so_far=0.0)]
        return FakeApp

    def test_falls_back_to_cli_engine_without_api_key(self, tmp_path: Path):
        folder = tmp_path / "src2"
        folder.mkdir()
        captured = {}

        with patch("helix_mini.app.HelixMini", self._capturing_app(captured)), \
             patch("helix_mini.config.providers.has_api_key", return_value=False), \
             patch("helix_mini.config.providers.has_claude_code_oauth",
                   return_value=False):
            run_pipeline_text(str(folder), home=tmp_path)

        assert captured["model"].model == "cli/claude"

    def test_oauth_token_wins_even_with_api_key(self, tmp_path: Path):
        folder = tmp_path / "src3"
        folder.mkdir()
        captured = {}

        with patch("helix_mini.app.HelixMini", self._capturing_app(captured)), \
             patch("helix_mini.config.providers.has_api_key", return_value=True), \
             patch("helix_mini.config.providers.has_claude_code_oauth",
                   return_value=True):
            # run_pipeline_text defaults lightspeed=True -> cheapest cli model
            run_pipeline_text(str(folder), home=tmp_path)

        assert captured["model"].model == "cli/claude:haiku"


class TestPermissionGate:
    def test_read_tool_auto_allowed(self):
        ok, reason = run_permission_decision(
            "mcp__helix__atlas_search", interactive=False)
        assert ok is True and reason == ""

    def test_run_tool_denied_non_interactive(self):
        ok, reason = run_permission_decision(
            "mcp__helix__run_pipeline", interactive=False)
        assert ok is False
        assert "non-interactive" in reason

    def test_run_tool_approved(self):
        ok, reason = run_permission_decision(
            "mcp__helix__run_pipeline", interactive=True,
            approver=lambda: True)
        assert ok is True and reason == ""

    def test_run_tool_declined(self):
        ok, reason = run_permission_decision(
            "mcp__helix__run_pipeline", interactive=True,
            approver=lambda: False)
        assert ok is False
        assert reason == "User declined the pipeline run."

    def test_bare_run_tool_name_is_gated(self):
        ok, _ = run_permission_decision(
            RUN_TOOL, interactive=True, approver=lambda: False)
        assert ok is False

    def test_interactive_without_approver_denies(self):
        ok, reason = run_permission_decision(
            "mcp__helix__run_pipeline", interactive=True)
        assert ok is False
        assert "No approver" in reason

    def test_unknown_tool_fail_closed(self):
        # Built-in/unrecognized tools (Bash, Write, ...) must be DENIED even
        # when an approver would say yes — they never reach the approver
        # branch. Regression test for the fail-open RCE.
        for tool in ("Bash", "Write", "Edit", "mcp__other__exec", "WebFetch"):
            ok, reason = run_permission_decision(
                tool, interactive=True, approver=lambda: True)
            assert ok is False, f"{tool} must be denied"
            assert "not permitted" in reason


@pytest.mark.skipif(
    _SDK_INSTALLED,
    reason="claude-agent-sdk is installed; the SDK-absent error path "
    "cannot be exercised in this environment",
)
class TestSdkMissing:
    def test_require_sdk_raises_actionable_error(self):
        from helix_mini.agent_sdk import _require_sdk

        with pytest.raises(RuntimeError, match=r"helix-mini\[agent\]"):
            _require_sdk()

    def test_run_agent_fails_fast_without_sdk(self):
        with pytest.raises(RuntimeError, match="Claude Agent SDK is not installed"):
            run_agent("hello")


class TestCliCommand:
    def test_agent_command_strips_nested_guard(self, monkeypatch):
        """The guard vars are popped before the SDK is touched, regardless of
        whether claude-agent-sdk is installed (run_agent is stubbed)."""
        import os

        from click.testing import CliRunner

        from helix_mini.cli import cli

        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
        monkeypatch.setattr(
            "helix_mini.agent_sdk.run_agent", lambda *a, **k: None
        )

        result = CliRunner().invoke(cli, ["agent", "hi"])

        assert result.exit_code == 0
        assert "CLAUDECODE" not in os.environ
        assert "CLAUDE_CODE_ENTRYPOINT" not in os.environ

    def test_agent_prompt_joins_unquoted_words(self, monkeypatch):
        from click.testing import CliRunner

        from helix_mini.cli import cli

        captured = {}

        def fake_run_agent(prompt=None, home=None, max_turns=30):
            captured["prompt"] = prompt

        monkeypatch.setattr("helix_mini.agent_sdk.run_agent", fake_run_agent)

        result = CliRunner().invoke(
            cli, ["agent", "search", "the", "atlas", "for", "cardiac"]
        )
        assert result.exit_code == 0
        assert captured["prompt"] == "search the atlas for cardiac"

    def test_agent_no_prompt_is_interactive(self, monkeypatch):
        from click.testing import CliRunner

        from helix_mini.cli import cli

        captured = {}

        def fake_run_agent(prompt=None, home=None, max_turns=30):
            captured["prompt"] = prompt

        monkeypatch.setattr("helix_mini.agent_sdk.run_agent", fake_run_agent)

        result = CliRunner().invoke(cli, ["agent"])
        assert result.exit_code == 0
        assert captured["prompt"] is None
