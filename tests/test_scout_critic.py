"""Workstream F.6 — Scout Critic rename + Deep-Modules bias.

Covers: the renamed stage is the second one in the pipeline; the new
agent definition carries the testable/falsifiable/distinct rubric +
deep_modules_note; the Planner's system prompt now carries the
Deep-Modules guidance; the back-compat alias keeps existing
``critic_methods`` callers working.
"""

from __future__ import annotations

from helix.core.agents import _CONTEXT, _MAP, load_agent, stage_order
from helix.core.transitions import stages


def test_stage_order_renames_critic_methods_to_scout_critic():
    order = list(stage_order())
    assert order[1] == "scout_critic"
    assert "critic_methods" not in order
    # And the public transitions API agrees.
    assert "scout_critic" in stages()


def test_scout_critic_agent_carries_new_rubric():
    a = load_agent("scout_critic")
    assert a.name == "scout_critic" and a.kind == "llm"
    # Rubric axes mentioned in the prompt
    for axis in ("testable", "falsifiable", "distinct"):
        assert axis in a.system.lower(), axis
    # Deep-Modules note is requested in the output contract
    assert "deep_modules_note" in a.system


def test_planner_prompt_includes_deep_modules_bias():
    a = load_agent("planner")
    assert "deep" in a.system.lower() and "ousterhout" in a.system.lower()
    # The Rust-RFC alternatives section is the home for the "design it twice"
    # record.
    assert "alternatives" in a.system.lower()


def test_back_compat_critic_methods_keys_still_resolve():
    """Anything referencing the pre-rename ``critic_methods`` key in
    ``_CONTEXT`` / ``_MAP`` (e.g. snapshots resumed from before the
    rename) still finds a function — the new ``scout_critic`` body."""
    assert "critic_methods" in _CONTEXT and "critic_methods" in _MAP
    # And it's the same function the new key points at.
    assert _CONTEXT["critic_methods"] is _CONTEXT["scout_critic"]
    assert _MAP["critic_methods"] is _MAP["scout_critic"]
