"""Workstream F.5 — the Builder's TDD task loop.

Covers: the ``_map_builder`` guardrails reject batched submissions,
phase-jumps, test-disabling artifacts, and a missing test in the test
phase; a well-formed test → impl → refactor sequence advances and is
recorded in ``state.completed_tasks``; legacy submits (no task_id /
phase) keep working.
"""

from __future__ import annotations

import pytest

from helix.core.agents import AgentCtx, AgentInputError, _map_builder
from helix.core.atlas import Atlas
from helix.core.state import PipelineState


def _expect_guard_error(call, fragment: str):
    """Run _map_builder and assert it raises AgentInputError containing
    ``fragment``. Mirrors the orchestrator's wrapping (run_agent →
    StageResult.error → send-back path)."""
    with pytest.raises(AgentInputError) as exc:
        call()
    assert fragment in str(exc.value)


def _ctx(tmp_path) -> AgentCtx:
    """Minimal AgentCtx — _map_builder only needs ``artifacts_dir``."""
    class _M:
        def model_for_stage(self, _):
            return "fake"

        def call_cap(self):
            return 0

    return AgentCtx(
        atlas=Atlas(tmp_path / "atlas"),
        model_config=_M(),
        raw_root=tmp_path / "raw",
        project_dir=tmp_path / "proj",
    )


def _state(**kw) -> PipelineState:
    return PipelineState(project_name=kw.pop("project_name", "p1"), **kw)


# --- Happy path: legacy + TDD sequence ------------------------------------


def test_legacy_builder_submit_passes_without_task_id(tmp_path):
    """Pre-F.5 submits (no task_id / phase) still work — the guardrail
    only activates when those fields are present."""
    upd = _map_builder({
        "artifacts": [{"name": "src/sim.py", "type": "code",
                       "content": "print('ok')", "description": "sim"}],
        "results": [],
    }, _state(), _ctx(tmp_path))
    assert "code_artifacts" in upd
    assert upd["code_artifacts"][0]["name"] == "src/sim.py"
    assert upd["completed_tasks"] == []  # nothing recorded without task_id


def test_full_tdd_sequence_advances_through_phases(tmp_path):
    s = _state()
    ctx = _ctx(tmp_path)
    # 1: test phase — must include a test artifact
    s_upd = _map_builder({
        "task_id": "T-001", "phase": "test",
        "artifacts": [{"name": "tests/test_x.py", "type": "code",
                       "content": "def test_x():\n    assert False\n",
                       "description": "failing test"}],
    }, s, ctx)
    s.completed_tasks = s_upd["completed_tasks"]
    assert s.completed_tasks[-1] == {
        **s.completed_tasks[-1],  # preserves 'at' timestamp
        "task_id": "T-001", "phase": "test",
    }
    # 2: impl phase
    s_upd = _map_builder({
        "task_id": "T-001", "phase": "impl",
        "artifacts": [{"name": "src/x.py", "type": "code",
                       "content": "def x():\n    return 1\n"}],
    }, s, ctx)
    s.completed_tasks = s_upd["completed_tasks"]
    assert [t["phase"] for t in s.completed_tasks] == ["test", "impl"]
    # 3: refactor phase
    s_upd = _map_builder({
        "task_id": "T-001", "phase": "refactor",
        "artifacts": [{"name": "src/x.py", "type": "code",
                       "content": "def x():\n    \"\"\"clearer\"\"\"\n    return 1\n"}],
    }, s, ctx)
    s.completed_tasks = s_upd["completed_tasks"]
    assert [t["phase"] for t in s.completed_tasks] == ["test", "impl", "refactor"]


# --- Guardrails -----------------------------------------------------------


def test_rejects_batched_submission(tmp_path):
    _expect_guard_error(lambda: _map_builder({
        "task_ids": ["T-001", "T-002"],
        "artifacts": [{"name": "tests/x.py", "type": "code",
                       "content": "x = 1"}],
    }, _state(), _ctx(tmp_path)), "one task at a time")


def test_rejects_unknown_phase(tmp_path):
    _expect_guard_error(lambda: _map_builder({
        "task_id": "T-001", "phase": "design",
        "artifacts": [],
    }, _state(), _ctx(tmp_path)), "phase must be one of")


def test_rejects_test_phase_without_test_artifact(tmp_path):
    _expect_guard_error(lambda: _map_builder({
        "task_id": "T-001", "phase": "test",
        "artifacts": [{"name": "src/x.py", "type": "code",
                       "content": "def x(): pass"}],
    }, _state(), _ctx(tmp_path)), "at least one test artifact")


def test_rejects_phase_jump_test_to_refactor(tmp_path):
    # Submit a test phase first to seed history.
    s = _state()
    upd = _map_builder({
        "task_id": "T-001", "phase": "test",
        "artifacts": [{"name": "tests/x.py", "type": "code",
                       "content": "def test_x(): assert False"}],
    }, s, _ctx(tmp_path))
    s.completed_tasks = upd["completed_tasks"]
    # Now try to jump straight to refactor (skip impl) — must reject.
    _expect_guard_error(lambda: _map_builder({
        "task_id": "T-001", "phase": "refactor",
        "artifacts": [{"name": "src/x.py", "type": "code",
                       "content": "def x(): return 1"}],
    }, s, _ctx(tmp_path)), "expected phase 'impl'")


def test_rejects_repeating_a_phase(tmp_path):
    s = _state()
    upd = _map_builder({
        "task_id": "T-001", "phase": "test",
        "artifacts": [{"name": "tests/x.py", "type": "code",
                       "content": "def test_x(): assert False"}],
    }, s, _ctx(tmp_path))
    s.completed_tasks = upd["completed_tasks"]
    _expect_guard_error(lambda: _map_builder({  # re-submit 'test'
        "task_id": "T-001", "phase": "test",
        "artifacts": [{"name": "tests/x.py", "type": "code",
                       "content": "def test_x(): assert True"}],
    }, s, _ctx(tmp_path)), "expected phase 'impl'")


def test_rejects_test_disabling_patterns(tmp_path):
    for bad in (
        "@pytest.mark.skip\ndef test_x(): pass",
        "@unittest.skip('todo')\nclass T: pass",
        "import pytest\ndef test_x(): pytest.skip('later')",
        "@pytest.mark.xfail(strict=False)\ndef test_x(): assert 0",
    ):
        _expect_guard_error(lambda b=bad: _map_builder({
            "task_id": "T-001", "phase": "test",
            "artifacts": [{"name": "tests/test_x.py", "type": "code",
                           "content": b}],
        }, _state(), _ctx(tmp_path)), "disables a test")


def test_rejects_further_submits_after_refactor(tmp_path):
    s = _state()
    for phase, body in (("test", "def test_x(): assert False"),
                        ("impl", "def x(): return 1"),
                        ("refactor", "def x():\n    return 1\n")):
        upd = _map_builder({
            "task_id": "T-001", "phase": phase,
            "artifacts": [{"name": (
                "tests/test_x.py" if phase == "test" else "src/x.py"),
                "type": "code", "content": body}],
        }, s, _ctx(tmp_path))
        s.completed_tasks = upd["completed_tasks"]
    # Task is done — another submit must say so.
    _expect_guard_error(lambda: _map_builder({
        "task_id": "T-001", "phase": "test",
        "artifacts": [{"name": "tests/test_x.py", "type": "code",
                       "content": "def test_x(): assert True"}],
    }, s, _ctx(tmp_path)), "already done")


# --- Integration with run_agent → StageResult.error ----------------------


def test_run_agent_converts_tdd_guard_to_state_error(tmp_path, monkeypatch):
    """A guard violation surfaces through run_agent as ``{error: ...}``
    — the same shape the orchestrator already handles as a clean stop."""
    from helix.core.agents import run_agent
    from helix import config

    monkeypatch.setenv("HELIX_HOME", str(tmp_path))
    # Stub the LLM chokepoint to return a guard-violating response.
    monkeypatch.setattr("helix.core.agents.call_llm_json",
        lambda *, model, system, user, **kw: (
            {"task_id": "T-001", "phase": "test",
             "artifacts": [{"name": "src/x.py", "type": "code",
                            "content": "x = 1"}],  # NO test file → violates
             "decision_card": {"summary": "x"}}, 1))
    s = _state()
    s.input_folder = str(tmp_path)
    (tmp_path / "src.py").write_text("x")  # avoid empty-sources error path
    ctx = _ctx(tmp_path)
    updates, tokens, card = run_agent("builder", s, ctx)
    assert updates.get("error") and "at least one test artifact" in updates["error"]
    assert tokens > 0  # the LLM call still counted
