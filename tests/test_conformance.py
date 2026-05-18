"""Dual-orchestrator conformance (Risk A): the loop and the LangGraph runner
must produce identical routing/snapshots for the same scripted scenario."""

from __future__ import annotations

import pytest

from helix import app
from helix.config import ModelConfig
from helix.core.snapshots import list_snapshots

langgraph = pytest.importorskip(
    "langgraph", reason="LangGraph orchestrator is the helix[sdk] extra"
)


def _run(project, engine):
    r = app.run(project, model_config=ModelConfig.cli("claude"),
                autonomy_until="END", interactive=False, engine=engine)
    snaps = [(s["stage"]) for s in list_snapshots("src-papers")]
    return (r.verdict, r.error, list(r.completed_stages), snaps)


def test_loop_and_sdk_agree(project, fake_llm):
    loop_result = _run(project, "loop")
    # Fresh isolated run for the sdk engine.
    import shutil

    from helix import config

    shutil.rmtree(config.atlas_path(), ignore_errors=True)
    shutil.rmtree(config.helix_dir() / "snapshots", ignore_errors=True)

    sdk_result = _run(project, "sdk")
    assert loop_result == sdk_result
