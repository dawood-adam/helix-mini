"""Workstream I — skills & plugins (prompt-level).

Covers: ``helix init`` writes a workspace AGENTS.md; each agent's
prompt mentions the recommended skill it should reach for; the wording
is gracefully optional ("if installed" / "graceful")."""

from __future__ import annotations

from click.testing import CliRunner

from helix.cli import cli
from helix.core.agents import load_agent


def test_helix_init_writes_agents_md(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["init"])
    assert result.exit_code == 0, result.output
    agents = tmp_path / "AGENTS.md"
    assert agents.exists()
    text = agents.read_text()
    assert "WebSearch" in text and "WebFetch" in text
    assert "superpowers" in text
    assert "simplify" in text and "review" in text
    assert "security-review" in text
    # Mentions the graceful contract.
    assert "use if available" in text.lower() or "graceful" in text.lower()


def test_helix_init_is_idempotent_on_agents_md(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    CliRunner().invoke(cli, ["init"])
    custom = "# my custom AGENTS.md\n"
    (tmp_path / "AGENTS.md").write_text(custom)
    CliRunner().invoke(cli, ["init"])
    # Re-running init must NOT overwrite the user's edits.
    assert (tmp_path / "AGENTS.md").read_text() == custom


def test_scout_prompt_mentions_websearch_and_extraction_skill():
    a = load_agent("scout")
    sys = a.system.lower()
    assert "websearch" in sys and "webfetch" in sys
    assert "superpowers" in sys
    assert "if available" in sys or "graceful" in sys


def test_builder_prompt_mentions_simplify_and_review():
    a = load_agent("builder")
    sys = a.system.lower()
    assert "simplify" in sys and "review" in sys
    assert "graceful" in sys or "if installed" in sys


def test_results_critic_prompt_mentions_security_review():
    a = load_agent("critic_results")
    sys = a.system.lower()
    assert "security-review" in sys
    # And it advances the hypothesis verdict (Workstream H tie-in).
    assert "hypothesis" in sys and "supported" in sys
