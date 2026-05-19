"""3g: hot cache — regenerated from snapshots at run end, zero-LLM."""

from __future__ import annotations

from helix import runs
from helix.core.decisions import DecisionCard
from helix.core.hot import read_hot, write_hot
from helix.core.plan import Plan
from helix.core.snapshots import mint_snapshot
from helix.core.state import PipelineState


def test_write_and_read_hot_from_snapshots(project):
    st = PipelineState(project_name="p")
    mint_snapshot(st, "p", stage="scout",
                  card=DecisionCard(summary="ingested sources"))
    mint_snapshot(st, "p", stage="planner", parent="1",
                  card=DecisionCard(
                      summary="dual-view plan ready",
                      open_questions=["dual vs single view?"],
                      directive_for_next="validate on Chen data"))

    dest = write_hot("p")
    assert dest is not None and dest.name == "_hot.md"
    text = read_hot("p")
    assert "snap 2 (planner, in-progress)" in text
    assert "dual-view plan ready" in text
    assert "dual vs single view?" in text
    assert "validate on Chen data" in text
    assert "1:scout, 2:planner" in text
    assert "**Live branches:** main" in text


def test_no_snapshots_is_noop(project):
    assert write_hot("ghost") is None
    assert read_hot("ghost") == "(no hot cache for 'ghost' yet)"


def test_finish_run_regenerates_hot(project):
    mint_snapshot(PipelineState(project_name="fp"), "fp", stage="scout",
                  card=DecisionCard(summary="started"))
    rid = runs.start_run("fp", Plan())
    runs.finish_run(rid, PipelineState(project_name="fp", verdict="ship",
                                       current_stage="scout"))
    # finish_run regenerated the hot cache from the snapshot trail
    assert "snap 1 (scout," in read_hot("fp") and "started" in read_hot("fp")
