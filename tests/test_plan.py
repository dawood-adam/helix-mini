"""The Plan primitive: explicit steps drive gate autonomy + inject
directives. (autonomy_until compat is covered in test_autonomy.)"""

from __future__ import annotations

from helix import app
from helix.config import ModelConfig
from helix.core.gates import GateDecision
from helix.core.plan import Plan, Step

_ALL = ("scout", "scout_critic", "planner", "builder",
        "validator", "critic_results")


def test_explicit_steps_autonomy_and_directive():
    order = list(_ALL)
    p = Plan(steps=[Step("scout", autonomy="auto"),
                    Step("planner", directive="focus on X", autonomy="hitl")])
    assert p.gate_auto("scout", order) is True       # step: auto
    assert p.gate_auto("planner", order) is False     # step: hitl
    assert p.gate_auto("builder", order) is False     # not in plan → ask
    assert p.directive_for("planner") == "focus on X"
    assert p.directive_for("scout") is None
    assert Plan.from_autonomy_until("END").directive_for("scout") is None


def test_full_auto_plan_runs_without_asking(project, fake_llm):
    asked = []

    def ask(report):
        asked.append(report.stage)
        return GateDecision("proceed")

    plan = Plan(steps=[Step(s, autonomy="auto") for s in _ALL])
    r = app.run(project, model_config=ModelConfig.cli("claude"),
                plan=plan, ask=ask, interactive=True)
    assert r.error is None
    assert asked == []  # every gate auto-proceeded per the plan


def test_step_directive_injected_as_feedback(project, fake_llm):
    plan = Plan(steps=[
        Step("scout", directive="prioritize rPPG papers", autonomy="auto"),
        *[Step(s, autonomy="auto") for s in _ALL[1:]],
    ])
    r = app.run(project, model_config=ModelConfig.cli("claude"),
                plan=plan, interactive=False)
    assert r.error is None
    assert any(f["from_stage"] == "plan" and f["target_stage"] == "scout"
               and "rPPG" in f["note"] for f in r.human_feedback)
