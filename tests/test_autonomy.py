"""autonomy_until: auto-proceed gates before a stage, then ask."""

from __future__ import annotations

from helix import app
from helix.config import ModelConfig
from helix.core.gates import GateDecision, gate_is_auto


def test_gate_is_auto_window():
    assert gate_is_auto("scout", "builder") is True
    assert gate_is_auto("planner", "builder") is True
    assert gate_is_auto("builder", "builder") is False  # ask AT builder onward
    assert gate_is_auto("scout", "") is False  # full HITL
    assert gate_is_auto("critic_results", "END") is True  # fully autonomous


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
