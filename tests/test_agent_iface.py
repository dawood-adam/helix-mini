"""SDK-free text helper bodies (now mounted as MCP tools)."""

from __future__ import annotations

from helix import app
from helix.agent_iface import atlas_status_text, snapshot_list_text
from helix.config import ModelConfig


def test_text_helpers_sdk_free(project, fake_llm):
    assert "No Atlas" in atlas_status_text()
    app.run(project, model_config=ModelConfig.cli("claude"),
            autonomy_until="END", interactive=False)
    assert "Pages:" in atlas_status_text()
    assert "snap-" in snapshot_list_text("src-papers")
