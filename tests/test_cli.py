"""CLI surface smoke tests. The CLI is two scaffolders + an MCP launcher;
the pipeline itself is driven through the MCP server."""

from __future__ import annotations

import json
import sys

from click.testing import CliRunner

from helix.cli import cli


def test_help():
    r = CliRunner().invoke(cli, ["--help"])
    assert r.exit_code == 0
    # Both scaffolders are advertised.
    assert "init" in r.output
    assert "new" in r.output


def test_init_scaffolds_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(cli, ["init"])
    assert r.exit_code == 0, r.output
    # workspace marker
    assert (tmp_path / "helix.toml").exists()
    assert "[workspace]" in (tmp_path / "helix.toml").read_text()
    # shared Atlas tree
    for d in ("inbox", "raw", "sources", "concepts", "entities",
              "concepts/glossary", "entities/datasets", "projects"):
        assert (tmp_path / "atlas" / d).is_dir(), d
    # .mcp.json: PATH-robust (absolute interpreter + `-m`)
    mcp = json.loads((tmp_path / ".mcp.json").read_text())
    helix_srv = mcp["mcpServers"]["helix"]
    assert helix_srv["command"] == sys.executable
    assert helix_srv["args"] == ["-m", "helix.mcp.server"]
    # README explains the model
    assert "Helix workspace" in (tmp_path / "README.md").read_text()


def test_init_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # The user might edit helix.toml; re-running init must not clobber it.
    CliRunner().invoke(cli, ["init"])
    (tmp_path / "helix.toml").write_text(
        '[workspace]\n# my custom note\n\n[atlas]\npath = "atlas"\n')
    r = CliRunner().invoke(cli, ["init"])
    assert r.exit_code == 0, r.output
    assert "my custom note" in (tmp_path / "helix.toml").read_text()


def test_new_requires_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(cli, ["new", "demo"])
    assert r.exit_code != 0
    assert "workspace" in (r.output + (r.exception and str(r.exception) or "")).lower()


def test_new_scaffolds_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    CliRunner().invoke(cli, ["init"])
    r = CliRunner().invoke(cli, ["new", "demo"])
    assert r.exit_code == 0, r.output
    proj = tmp_path / "demo"
    assert (proj / "question.md").exists()
    assert (proj / "helix.toml").exists()
    # Per-project helix.toml has limits, not [atlas] (workspace owns Atlas).
    proj_toml = (proj / "helix.toml").read_text()
    assert "[limits]" in proj_toml
    assert "[atlas]" not in proj_toml
    claude = (proj / "CLAUDE.md").read_text()
    assert "Helix project" in claude
    assert "start helix" in claude
    assert "collection of source material" in claude
    assert claude.index("source material") < claude.index("Driving the pipeline")
    # Per-project .mcp.json so Claude Code finds the server here.
    mcp = json.loads((proj / ".mcp.json").read_text())
    assert mcp["mcpServers"]["helix"]["args"] == ["-m", "helix.mcp.server"]


def test_new_refuses_to_overwrite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    CliRunner().invoke(cli, ["init"])
    CliRunner().invoke(cli, ["new", "demo"])
    r = CliRunner().invoke(cli, ["new", "demo"])
    assert r.exit_code != 0
    assert "already exists" in (r.output + (r.exception and str(r.exception) or ""))
