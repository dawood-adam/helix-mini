"""Workstream H — the discovery engine (hypothesis loop).

Covers: the ``Hypothesis`` dataclass + ``rank`` is deterministic;
``parse_hypotheses`` / ``to_section`` round-trip on the hypothesis-thread
body format; the ``rediscover`` plan mode loops the orchestrator from
Results Critic back to Scout, capped at ``REDISCOVER_CAP``;
``discovery-log`` lint flags a Supported hypothesis with no support
list.
"""

from __future__ import annotations

import pytest

from helix.core import hypothesis as _hyp
from helix.core.hypothesis import (
    REDISCOVER_CAP, Hypothesis, parse_hypotheses, rank, to_section,
)


# --- Hypothesis dataclass + scoring ---------------------------------------


def test_score_is_mean_of_rubric_axes():
    h = Hypothesis(id="H1", statement="x", testable=1.0,
                   falsifiable=0.5, distinct=0.0)
    assert h.score == pytest.approx(0.5)


def test_type_and_status_defaults_are_validated():
    h = Hypothesis(id="H1", statement="x", type="frobnitz", status="???")
    assert h.type == "explanatory" and h.status == "Proposed"


# --- Ranker ---------------------------------------------------------------


def test_rank_orders_by_score_descending_with_id_tiebreak():
    a = Hypothesis(id="HA", statement="a", testable=0.8,
                   falsifiable=0.8, distinct=0.8)
    b = Hypothesis(id="HB", statement="b", testable=0.9,
                   falsifiable=0.9, distinct=0.9)
    c = Hypothesis(id="HC", statement="c", testable=0.8,
                   falsifiable=0.8, distinct=0.8)  # ties with HA
    out = [h.id for h in rank([a, b, c])]
    assert out == ["HB", "HA", "HC"]  # HB top; HA before HC by id


def test_rank_pushes_refuted_and_superseded_to_bottom():
    alive = Hypothesis(id="HA", statement="a", testable=0.1,
                       falsifiable=0.1, distinct=0.1, status="Proposed")
    dead = Hypothesis(id="HB", statement="b", testable=1.0,
                     falsifiable=1.0, distinct=1.0, status="Refuted")
    out = [h.id for h in rank([alive, dead])]
    assert out == ["HA", "HB"]


def test_rank_is_deterministic_across_repeated_calls():
    hs = [Hypothesis(id=f"H{i}", statement="s", testable=i / 10,
                     falsifiable=(i + 1) / 10, distinct=i / 10)
          for i in range(5)]
    a = [h.id for h in rank(list(hs))]
    b = [h.id for h in rank(list(hs))]
    assert a == b


# --- Thread-body round-trip -----------------------------------------------


def test_to_section_parse_round_trip():
    h = Hypothesis(
        id="H1", statement="rPPG can estimate BP",
        type="predictive", testable=0.8, falsifiable=0.7, distinct=0.6,
        support=["atlas:concepts:rppg", "atlas:sources:paper"],
        refutations=[], status="Supported")
    body = to_section(h)
    parsed = parse_hypotheses(body)
    assert len(parsed) == 1
    got = parsed[0]
    assert got.id == "H1" and got.statement.startswith("rPPG")
    assert got.type == "predictive" and got.status == "Supported"
    assert got.testable == 0.8 and got.falsifiable == 0.7
    assert got.distinct == 0.6
    assert got.support == ["atlas:concepts:rppg", "atlas:sources:paper"]


def test_parse_hypotheses_tolerates_extra_prose():
    body = (
        "## snap-1\n\nfree-form intro paragraph\n\n"
        "### H1\n- statement: first\n- type: descriptive\n- status: Proposed\n\n"
        "(unrelated text)\n\n"
        "### H2\n- statement: second\n- testable: 0.7\n- distinct: 0.3\n"
    )
    parsed = parse_hypotheses(body)
    assert [h.id for h in parsed] == ["H1", "H2"]
    assert parsed[1].testable == 0.7 and parsed[1].distinct == 0.3


# --- The rediscover loop control --------------------------------------------


def test_is_rediscover_picks_up_plan_mode():
    from helix.core.plan import Plan

    assert _hyp.is_rediscover(Plan.from_autonomy_until("rediscover")) is True
    assert _hyp.is_rediscover(Plan.from_autonomy_until("END")) is False
    assert _hyp.is_rediscover(Plan()) is False


def test_iterations_so_far_counts_critic_results_completions():
    from helix.core.state import PipelineState

    s = PipelineState(project_name="p", completed_stages=[
        "scout", "scout_critic", "planner", "builder", "validator",
        "critic_results",
        "scout", "scout_critic", "planner", "builder", "validator",
        "critic_results",
    ])
    assert _hyp.iterations_so_far(s) == 2


def test_should_loop_again_respects_cap():
    from helix.core.plan import Plan
    from helix.core.state import PipelineState

    plan = Plan.from_autonomy_until("rediscover")
    s = PipelineState(project_name="p",
                       completed_stages=["critic_results"] * REDISCOVER_CAP)
    assert _hyp.should_loop_again(s, plan) is False
    # One fewer iteration → still loops.
    s2 = PipelineState(project_name="p",
                        completed_stages=["critic_results"] * (REDISCOVER_CAP - 1))
    assert _hyp.should_loop_again(s2, plan) is True


# --- Lint ------------------------------------------------------------------


def test_lint_discovery_log_flags_supported_without_support(tmp_path):
    from helix.core import threads
    from helix.core.atlas import Atlas
    from helix.core.lint import lint

    Atlas(tmp_path / "atlas")  # scaffold
    h_supported_no_evidence = Hypothesis(
        id="H1", statement="rPPG estimates BP",
        testable=0.8, falsifiable=0.7, distinct=0.6,
        status="Supported", support=[])
    h_supported_with_evidence = Hypothesis(
        id="H2", statement="another",
        status="Supported", support=["atlas:sources:paper"])
    body = "\n".join(to_section(h) for h in
                     (h_supported_no_evidence, h_supported_with_evidence))
    t = threads.ensure_thread(tmp_path / "atlas", "p1", "hypothesis")
    t.body = "# Hypothesis thread\n\n" + body
    threads.save_thread(tmp_path / "atlas", "p1", t)
    issues = lint(tmp_path / "atlas")
    flagged = {i["hypothesis"] for i in issues if i["kind"] == "discovery-log"}
    assert flagged == {"H1"}


# --- Orchestrator rediscover loop (integration) ----------------------------


def test_orchestrator_loops_under_rediscover_mode(project, fake_llm):
    """End-to-end: ``autonomy_until='rediscover'`` runs critic_results
    multiple times (capped). Each iteration writes a fresh
    critic_results snapshot."""
    from helix import app
    from helix.config import ModelConfig
    from helix.core.snapshots import list_snapshots

    r = app.run(project, model_config=ModelConfig.cli("claude"),
                autonomy_until="rediscover", interactive=False)
    assert r.error is None
    # critic_results runs at least 2 iterations (and at most REDISCOVER_CAP).
    n_cr = r.completed_stages.count("critic_results")
    assert 2 <= n_cr <= REDISCOVER_CAP, n_cr
    # Each iteration walks all six stages, so completed_stages has
    # n_cr full passes worth.
    n_scout = r.completed_stages.count("scout")
    assert n_scout == n_cr
    # Snapshots accumulate per stage per iteration.
    snaps = list_snapshots("src-papers")
    assert any(s["stage"] == "critic_results" for s in snaps)
