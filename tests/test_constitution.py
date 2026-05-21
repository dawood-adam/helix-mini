"""Workstream F.1 — Constitution: workspace-level non-negotiables file,
optional per-project override, injection into every agent's prompt."""

from __future__ import annotations


def _setup_workspace(tmp_path, monkeypatch):
    """Minimal workspace: marker + Atlas tree + project subdir."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "helix.toml").write_text('[workspace]\n[atlas]\npath = "atlas"\n')
    (ws / "atlas" / "projects").mkdir(parents=True)
    proj = ws / "proj"
    proj.mkdir()
    (proj / "helix.toml").write_text("[limits]\ntoken_cap = 0\n")
    monkeypatch.setenv("HELIX_HOME", str(proj))
    return ws, proj


def test_ensure_writes_default_template_idempotently(tmp_path, monkeypatch):
    from helix.core import constitution

    ws, _ = _setup_workspace(tmp_path, monkeypatch)
    p = constitution.ensure_constitution(ws)
    assert p == ws / "constitution.md"
    assert "Constitution" in p.read_text()

    # Idempotent: user edits, ensure() must not clobber.
    p.write_text("# Mine\nshort.\n")
    p2 = constitution.ensure_constitution(ws)
    assert p2.read_text() == "# Mine\nshort.\n"


def test_workspace_constitution_loads_via_helper(tmp_path, monkeypatch):
    from helix.core import constitution

    ws, _ = _setup_workspace(tmp_path, monkeypatch)
    constitution.save_constitution("# Workspace rules\n- strict TDD\n")
    assert "strict TDD" in constitution.load_constitution()


def test_project_override_wins(tmp_path, monkeypatch):
    """Per spec §F-1: optional per-project override beats the workspace-
    level Constitution when present."""
    from helix.core import constitution

    ws, _ = _setup_workspace(tmp_path, monkeypatch)
    constitution.save_constitution("WORKSPACE")
    constitution.save_constitution("PROJECT-ONLY", project="proj")
    assert constitution.load_constitution() == "WORKSPACE"
    assert constitution.load_constitution(project="proj") == "PROJECT-ONLY"


def test_injected_into_every_agent_prompt(tmp_path, monkeypatch):
    """``load_agent`` appends the active Constitution to the agent's
    system prompt so every stage sees the non-negotiables at turn-start."""
    from helix.core import agents, constitution

    ws, _ = _setup_workspace(tmp_path, monkeypatch)
    constitution.save_constitution("# C\nstrict TDD line.\n")
    # Built-in stages all get the injection — pick scout as the witness.
    a = agents.load_agent("scout")
    assert "strict TDD line." in a.system
    # No Constitution → no injection (the body ends normally).
    constitution.constitution_path().unlink()
    a2 = agents.load_agent("scout")
    assert "strict TDD line." not in a2.system


def test_helix_init_scaffolds_constitution(tmp_path, monkeypatch):
    """`helix init` writes the default Constitution into the workspace
    (idempotent — re-init preserves the user's edits)."""
    from click.testing import CliRunner

    from helix.cli import cli

    monkeypatch.chdir(tmp_path)
    CliRunner().invoke(cli, ["init"])
    p = tmp_path / "constitution.md"
    assert p.exists()
    assert "Constitution" in p.read_text()
    # Re-init keeps user edits.
    p.write_text("# Mine\n")
    CliRunner().invoke(cli, ["init"])
    assert p.read_text() == "# Mine\n"
