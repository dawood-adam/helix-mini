"""DecisionCard: the single structured agent output + its defensive parsing."""

from __future__ import annotations

from helix.core.decisions import DecisionCard
from helix.core.snapshots import load_snapshot, mint_snapshot
from helix.core.state import PipelineState


def test_full_card_parsed():
    c = DecisionCard.from_response({"decision_card": {
        "summary": "Picked approach A.",
        "key_findings": ["f1", "f2"],
        "assumptions": ["a1"],
        "open_questions": [],
        "directive_for_next": "validate A",
        "confidence": "HIGH",
    }}, "critic_methods")
    assert c.summary == "Picked approach A."
    assert c.key_findings == ["f1", "f2"]
    assert c.directive_for_next == "validate A"
    assert c.confidence == "high"  # normalized


def test_missing_card_defaults_generic():
    c = DecisionCard.from_response({}, "scout")
    assert c.summary == "scout complete"
    assert c.confidence == "medium"
    assert c.key_findings == [] and c.assumptions == []


def test_deterministic_or_no_response():
    c = DecisionCard.from_response(None, "validator")
    assert c.summary == "validator complete" and c.confidence == "medium"


def test_defensive_against_junk():
    # decision_card not a dict; bad confidence; scalar where a list is expected
    c = DecisionCard.from_response(
        {"decision_card": "oops"}, "planner")
    assert c.summary == "planner complete"
    c2 = DecisionCard.from_response({"decision_card": {
        "summary": "  ", "confidence": "banana", "key_findings": "single"}},
        "builder")
    assert c2.summary == "builder complete"      # blank -> generic
    assert c2.confidence == "medium"             # invalid -> medium
    assert c2.key_findings == ["single"]         # scalar -> [scalar]


def test_card_lands_in_snapshot(project):
    s = PipelineState(project_name="p")
    card = DecisionCard.from_response(
        {"decision_card": {"summary": "did the thing"}}, "scout")
    mint_snapshot(s, "p", stage="scout", card=card)
    snap = load_snapshot("p", 1)
    assert snap["decision_card"]["summary"] == "did the thing"
    # zero-LLM contract still holds: mint serializes a pre-made card.
    assert snap["decision_card"]["confidence"] == "medium"
