"""Fail-closed agent gate + SDK-free text helpers (Risk J)."""

from __future__ import annotations

from helix import app
from helix.agent_iface import (
    atlas_status_text, run_permission_decision, snapshot_list_text,
)
from helix.config import ModelConfig


def test_permission_fail_closed():
    # Read tools auto-approve.
    ok, _ = run_permission_decision("mcp__helix__atlas_search", interactive=True)
    assert ok is True
    # Gated tool with an approver that says yes.
    ok, _ = run_permission_decision(
        "mcp__helix__run_pipeline", interactive=True, approver=lambda: True)
    assert ok is True
    # Gated tool, non-interactive, no approver -> denied.
    ok, msg = run_permission_decision("mcp__helix__resume_pipeline", interactive=False)
    assert ok is False
    # Anything else (SDK built-ins) -> denied.
    ok, msg = run_permission_decision("Bash", interactive=True, approver=lambda: True)
    assert ok is False and "not permitted" in msg


def test_text_helpers_sdk_free(project, fake_llm):
    assert "No Atlas" in atlas_status_text()
    app.run(project, model_config=ModelConfig.cli("claude"),
            autonomy_until="END", interactive=False)
    assert "Pages:" in atlas_status_text()
    assert "snap-" in snapshot_list_text("src-papers")
