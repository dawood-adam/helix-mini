"""CLI surface smoke tests. The CLI is init-only; the pipeline is driven
through the MCP server (Phase 1)."""

from __future__ import annotations

from click.testing import CliRunner

from helix.cli import cli


def test_help():
    r = CliRunner().invoke(cli, ["--help"])
    assert r.exit_code == 0
    assert "init" in r.output


def test_init_scaffold(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIX_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(cli, ["init", "demo"])
    assert r.exit_code == 0
    assert (tmp_path / "demo" / "question.md").exists()
    assert (tmp_path / "demo" / "helix.toml").exists()
    claude = (tmp_path / "demo" / "CLAUDE.md").read_text()
    assert "Helix project" in claude
    # "start helix" must first direct the user to point out source material.
    assert "start helix" in claude
    assert "collection of source material" in claude
    assert claude.index("source material") < claude.index("Driving the pipeline")
