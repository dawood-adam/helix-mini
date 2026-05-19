"""CLI surface smoke tests. The CLI is init-only; the pipeline is driven
through the MCP server."""

from __future__ import annotations

import json
import sys

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

    # .mcp.json must be PATH-robust: absolute interpreter + `-m`, not the
    # bare `helix-mcp` name (which the client resolves against its own PATH).
    mcp = json.loads((tmp_path / "demo" / ".mcp.json").read_text())
    helix_srv = mcp["mcpServers"]["helix"]
    assert helix_srv["command"] == sys.executable
    assert helix_srv["args"] == ["-m", "helix.mcp.server"]
