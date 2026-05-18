"""Snapshots v2: zero-LLM, content-addressed, branch/revert/resume, gitgraph."""

from __future__ import annotations

import json

from helix import app, config
from helix.config import ModelConfig
from helix.core import snapshots
from helix.core.snapshots import (
    diff_snapshots, list_snapshots, load_snapshot, mint_snapshot,
    restore_artifacts, snapshot_gitgraph,
)
from helix.core.state import PipelineState


def test_mint_costs_zero_llm(project, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(
        "helix.core.agents.call_llm_json",
        lambda **k: (_ for _ in ()).throw(AssertionError("LLM during snapshot")),
    )
    s = PipelineState(project_name="p", code_artifacts=[
        {"name": "a.py", "type": "code", "content": "x" * 5000, "description": "d"}])
    meta = mint_snapshot(s, "p", stage="builder", report={"decision": "d"})
    assert meta["id"] == "1"


def test_content_addressed_dedup_and_rehydrate(project):
    big = "y" * 10000
    s = PipelineState(project_name="p", code_artifacts=[
        {"name": "a.py", "type": "code", "content": big, "description": "d"}])
    mint_snapshot(s, "p", stage="builder")
    mint_snapshot(s, "p", stage="builder")  # identical bytes
    objs = list((config.helix_dir() / "snapshots" / "p" / "objects").iterdir())
    assert len(objs) == 1  # deduped by sha
    raw = json.loads((config.helix_dir() / "snapshots" / "p" / "1.json").read_text())
    assert raw["state"]["code_artifacts"] == []  # bytes not inlined
    assert len(json.dumps(raw)) < 4000  # snapshot stays small
    loaded = load_snapshot("p", 1)
    assert loaded["state"]["code_artifacts"][0]["content"] == big  # rehydrated


def test_branch_revert_resume(project, fake_llm):
    app.run(project, model_config=ModelConfig.cli("claude"),
            autonomy_until="END", interactive=False)
    snaps = list_snapshots("src-papers")
    assert len(snaps) >= 6
    builder_snap = next(s for s in snaps if s["stage"] == "builder")

    # revert: artifacts restored to the project dir
    dest = config.atlas_path() / "projects" / "src-papers" / "artifacts"
    written = restore_artifacts("src-papers", builder_snap["id"], dest)
    assert "src/sim.py" in written
    assert (dest / "src" / "sim.py").read_text() == "print('ok')\n"

    # resume on a new branch from the builder snapshot
    r2 = app.resume("src-papers", builder_snap["id"], model_config=ModelConfig.cli("claude"),
                     start_at="builder", branch="retry", autonomy_until="END",
                     interactive=False)
    assert r2.error is None
    branches = {s.get("branch") for s in list_snapshots("src-papers")}
    assert "retry" in branches and "main" in branches

    graph = snapshot_gitgraph("src-papers")
    assert "gitGraph" in graph and "branch retry" in graph


def test_diff(project, fake_llm):
    app.run(project, model_config=ModelConfig.cli("claude"),
            autonomy_until="END", interactive=False)
    snaps = list_snapshots("src-papers")
    a = load_snapshot("src-papers", snaps[0]["id"])
    b = load_snapshot("src-papers", snaps[-1]["id"])
    d = diff_snapshots(a, b)
    assert "current_stage" in d
