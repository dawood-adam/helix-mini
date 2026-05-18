"""Full-pipeline parity: a fresh run reaches a ship verdict and writes Atlas."""

from __future__ import annotations

from helix import app
from helix.config import ModelConfig
from helix.core.snapshots import list_snapshots


def test_full_run_loop(project, fake_llm):
    r = app.run(project, model_config=ModelConfig.cli("claude"),
                autonomy_until="END", interactive=False)
    assert r.error is None
    assert r.verdict == "ship"
    assert r.completed_stages[:5] == [
        "scout", "critic_methods", "planner", "builder", "validator",
    ]
    assert "critic_results" in r.completed_stages
    assert r.cost_so_far > 0
    # One snapshot per stage executed.
    snaps = list_snapshots("src-papers")
    assert len(snaps) == len(r.completed_stages)
    assert {s["stage"] for s in snaps} >= {"scout", "builder", "critic_results"}


def test_atlas_compounds(project, fake_llm):
    app.run(project, model_config=ModelConfig.cli("claude"),
            autonomy_until="END", interactive=False)
    from helix.config import atlas_path
    from helix.core.atlas import Atlas

    a = Atlas(atlas_path())
    assert a.read("Paper"), "scout should have written a source page"
    assert (atlas_path() / "projects" / "src-papers" / "decisions.md").exists()
