"""Run control: the Plan engine. ``autonomy_until`` is now a Plan
constructor (compat), so existing callers/tests are unchanged."""

from __future__ import annotations

from helix import app
from helix.config import ModelConfig
from helix.core.gates import GateDecision
from helix.core.plan import Plan
from helix.core.transitions import stages


def test_plan_from_autonomy_until_window():
    order = list(stages())
    p = Plan.from_autonomy_until("builder")
    assert p.gate_auto("scout", order) is True
    assert p.gate_auto("planner", order) is True
    assert p.gate_auto("builder", order) is False  # ask AT builder onward
    assert Plan.from_autonomy_until("").gate_auto("scout", order) is False
    assert Plan.from_autonomy_until("END").gate_auto("critic_results", order) is True


def test_autonomy_until_builder_asks_only_from_builder(project, fake_llm):
    asked = []

    def ask(report):
        asked.append(report.stage)
        return GateDecision("proceed")

    r = app.run(project, model_config=ModelConfig.cli("claude"),
                autonomy_until="builder", ask=ask, interactive=True)
    assert r.error is None
    # Gates before 'builder' auto-proceeded; asked only from builder onward.
    assert "scout" not in asked and "critic_methods" not in asked
    assert "planner" not in asked
    assert "builder" in asked
