"""Cost ceiling pauses (resumable) instead of failing (Risk E)."""

from __future__ import annotations

from helix import app
from helix.config import ModelConfig
from helix.core.snapshots import list_snapshots


def test_autonomous_run_pauses_not_errors(project, fake_llm, monkeypatch):
    # Ceiling small enough to trip after the first stage's cost (~0.01).
    monkeypatch.setattr("helix.config.cost_cap", lambda: 0.005)
    r = app.run(project, model_config=ModelConfig.cli("claude"),
                autonomy_until="END", interactive=False)
    assert r.error is None              # paused, not failed
    assert r.next_action == "paused-cost"
    # A snapshot was minted so the run is resumable.
    assert list_snapshots("src-papers")


def test_interactive_continue_doubles_ceiling(project, fake_llm, monkeypatch):
    monkeypatch.setattr("helix.config.cost_cap", lambda: 0.005)
    from helix.core.gates import GateDecision

    def ask(report):
        # Continue at the cost-ceiling prompt; proceed at normal gates.
        return GateDecision("proceed")

    r = app.run(project, model_config=ModelConfig.cli("claude"),
                ask=ask, interactive=True)
    # It kept going past the ceiling (ceiling doubled on continue).
    assert r.next_action != "paused-cost"
    assert "critic_results" in r.completed_stages
