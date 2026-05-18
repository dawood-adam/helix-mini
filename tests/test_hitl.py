"""HITL: send the run back to ANY earlier stage with contextualized feedback."""

from __future__ import annotations

from helix import app
from helix.config import ModelConfig
from helix.core.gates import GateDecision


def test_send_back_to_any_stage_with_feedback(project, fake_llm, monkeypatch):
    seen_planner_feedback = []
    real_ctx_planner = None

    import helix.core.agents as A

    orig = A._ctx_planner

    def spy_planner(s, c):
        seen_planner_feedback.append(list(s.feedback_for("planner")))
        return orig(s, c)

    monkeypatch.setattr(A, "_ctx_planner", spy_planner)
    monkeypatch.setitem(A._CONTEXT, "planner", spy_planner)

    # Ask script: at the gate after 'builder', send back to 'planner' once
    # with feedback; thereafter always proceed.
    state = {"sent_back": False}

    def ask(report):
        if report.stage == "builder" and not state["sent_back"]:
            state["sent_back"] = True
            return GateDecision("goto", "planner", "tighten the validation bands")
        return GateDecision("proceed")

    r = app.run(project, model_config=ModelConfig.cli("claude"),
                ask=ask, interactive=True)

    assert r.error is None
    # planner ran at least twice (initial + after send-back)
    assert seen_planner_feedback.count([]) >= 1
    assert any("tighten the validation bands" in fb
               for fbs in seen_planner_feedback for fb in fbs)
    # feedback persisted on state, targeting planner
    assert any(f["target_stage"] == "planner" and "tighten" in f["note"]
               for f in r.human_feedback)
    # builder appears twice in the execution trace (looped through it again)
    assert r.completed_stages.count("builder") >= 2
