"""The bounded run registry: persisted record + events + live plan steering."""

from __future__ import annotations

from helix import runs
from helix.core.plan import Plan
from helix.core.state import PipelineState


def test_run_record_lifecycle(project):
    rid = runs.start_run("demo", Plan())
    assert rid.startswith("run_")
    assert runs.get_record(project="demo").status == "running"

    runs.record_event(rid, "scout", 12)
    runs.record_event(rid, "planner", 30)
    evs = runs.tail_events(project="demo")
    assert [e["stage"] for e in evs] == ["scout", "planner"]
    assert runs.tail_events(project="demo", since=1) == evs[1:]

    runs.finish_run(rid, PipelineState(
        project_name="demo", verdict="ship",
        current_stage="critic_results", tokens_used=42))
    done = runs.get_record(project="demo")
    assert done.status == "done" and done.tokens_used == 42
    assert done.run_id == rid  # resolved from disk after the live entry is gone


def test_set_plan_steers_live_run_then_stops(project):
    plan = Plan.from_autonomy_until("END")
    rid = runs.start_run("d2", plan)
    msg = runs.set_plan(project="d2", steps=[{"agent": "scout", "autonomy": "hitl"}])
    assert "effective at the next gate" in msg
    # same Plan object the loop holds is mutated
    assert plan.steps[0].agent == "scout" and plan.auto_until is None
    runs.finish_run(rid, PipelineState(project_name="d2"))
    assert "No live run" in runs.set_plan(project="d2", autonomy_until="END")


def test_abort_marks_error(project):
    rid = runs.start_run("d3", Plan())
    runs.abort_run(rid, "no snapshot 99")
    rec = runs.get_record(project="d3")
    assert rec.status == "error" and "no snapshot" in rec.note
