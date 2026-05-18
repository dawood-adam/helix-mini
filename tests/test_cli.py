"""CLI surface smoke tests."""

from __future__ import annotations

from click.testing import CliRunner

from helix.cli import cli


def test_help():
    r = CliRunner().invoke(cli, ["--help"])
    assert r.exit_code == 0
    for cmd in ("run", "snapshots", "agent", "init", "status", "atlas"):
        assert cmd in r.output


def test_snapshots_help_lists_subcommands():
    r = CliRunner().invoke(cli, ["snapshots", "--help"])
    assert r.exit_code == 0
    for sub in ("list", "show", "diff", "diagram", "revert", "resume"):
        assert sub in r.output


def test_init_scaffold(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIX_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(cli, ["init", "demo"])
    assert r.exit_code == 0
    assert (tmp_path / "demo" / "question.md").exists()
    assert (tmp_path / "demo" / "helix.toml").exists()
    claude = (tmp_path / "demo" / "CLAUDE.md").read_text()
    assert "Helix project" in claude and "helix run ." in claude
