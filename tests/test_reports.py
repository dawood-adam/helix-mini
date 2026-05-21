"""Workstream D — stage HTML reports + the annotation overlay.

Covers: renderer emits valid self-contained HTML carrying the embedded
W3C Web Annotation JSON block; the round-trip parser buckets entries by
state; the send-back feedback builder produces an agent-readable string
that includes kept/rejected/replies/researcher comments."""

from __future__ import annotations

import json

from helix.core.decisions import DecisionCard
from helix.core.reports import (
    ReportContext,
    build_send_back_feedback,
    parse_round_trip,
    render_report,
)


def _card(**kw):
    return DecisionCard(
        summary=kw.get("summary", "scout complete"),
        key_findings=kw.get("key_findings", ["finding A", "finding B"]),
        assumptions=kw.get("assumptions", []),
        open_questions=kw.get("open_questions", []),
        directive_for_next=kw.get("directive_for_next", "look at X next"),
        confidence=kw.get("confidence", "medium"),
    )


def test_renders_self_contained_html_with_embedded_json():
    html = render_report(_card(), "scout", "orthobp", snapshot_id="3")
    assert html.startswith("<!doctype html>")
    # The annotations block is embedded; no sidecar required.
    assert 'id="hx-annotations"' in html
    # The overlay JS + CSS are inlined (no external src).
    assert "<style>" in html and "<script>" in html
    assert "src=" not in html.lower().split("<script>")[1].split("</script>")[0]
    # Title + meta surface the stage + project + snapshot.
    assert "orthobp" in html and "scout" in html
    assert "snapshot 3" in html.lower() or "snapshot </span>3" in html.lower() \
        or "snapshot 3" in html


def test_per_agent_templates_have_their_signature_sections():
    """Each stage template uses the section set spec §D mandates. We
    pick one distinguishing heading per template — that's enough to
    catch a wrong template firing."""
    s = render_report(_card(), "scout", "p"); assert 'id="prisma"' in s
    m = render_report(_card(), "critic_methods", "p"); assert 'id="impact-on-spec"' in m
    p = render_report(_card(), "planner", "p"); assert 'id="alternatives"' in p
    b = render_report(_card(), "builder", "p"); assert 'id="checklist"' in b
    v = render_report(_card(), "validator", "p", ctx=ReportContext(flags=["HARD: x", "SOFT: y"]))
    assert 'id="hard-flags"' in v and "HARD: x" in v
    r = render_report(_card(), "critic_results", "p", ctx=ReportContext(verdict="ship"))
    assert 'id="verdict"' in r and "ship" in r


def test_round_trip_buckets_annotations_by_state():
    annotations = [
        {  # kept (open critic note)
            "id": "a1", "creator": {"name": "scout_critic"},
            "state": "open", "severity": "high",
            "body": {"value": "PRISMA flow numbers don't add up"},
            "target": {"selector": [{"type": "FragmentSelector", "value": "methods"}]},
        },
        {  # rejected (with reason in log)
            "id": "a2", "creator": {"name": "scout_critic"},
            "state": "rejected", "severity": "low",
            "body": {"value": "minor wording nit"},
            "target": {"selector": [{"type": "FragmentSelector", "value": "results"}]},
            "log": [{"action": "rejected", "reason": "out of scope"}],
        },
        {  # researcher comment
            "id": "a3", "creator": {"name": "researcher"},
            "state": "open", "severity": "low",
            "body": {"value": "match glossary term 'hold-out'"},
            "target": {"selector": [{"type": "FragmentSelector", "value": "results"}]},
        },
        {  # explicit send-back
            "id": "a4", "creator": {"name": "scout_critic"},
            "state": "send_back", "severity": "high",
            "body": {"value": "H3 lacks a falsification condition"},
            "target": {"selector": [{"type": "FragmentSelector", "value": "discussion"}]},
        },
    ]
    html = render_report(_card(), "scout", "orthobp", annotations=annotations)
    rt = parse_round_trip(html)
    assert {a["id"] for a in rt.send_back} == {"a4"}
    assert {a["id"] for a in rt.rejected} == {"a2"}
    assert {a["id"] for a in rt.comments} == {"a3"}
    # kept = the still-open critic note (a1) — accepted ones would also land here
    assert {a["id"] for a in rt.kept} == {"a1"}


def test_send_back_feedback_is_agent_readable():
    annotations = [
        {"id": "a4", "creator": {"name": "scout_critic"},
         "state": "send_back", "severity": "high",
         "body": {"value": "H3 lacks falsification"},
         "target": {"selector": [{"type": "FragmentSelector", "value": "discussion"}]}},
        {"id": "a2", "creator": {"name": "scout_critic"},
         "state": "rejected", "body": {"value": "minor nit"},
         "target": {"selector": [{"type": "FragmentSelector", "value": "results"}]},
         "log": [{"action": "rejected", "reason": "out of scope"}]},
    ]
    html = render_report(_card(), "scout", "orthobp", annotations=annotations)
    rt = parse_round_trip(html)
    fb = build_send_back_feedback(rt)
    assert "SEND-BACK ITEMS" in fb and "H3 lacks falsification" in fb
    assert "REJECTED CRITIC NOTES" in fb and "out of scope" in fb
    # The rejected reason is included so the agent doesn't reintroduce it.


def test_parser_is_tolerant_of_garbage():
    # Missing annotation block → empty bundle, no exception.
    assert parse_round_trip("<html></html>").kept == []
    # Malformed JSON → empty bundle.
    bad = '<script id="hx-annotations" type="application/json">{not json</script>'
    assert parse_round_trip(bad).kept == []


def test_overlay_actions_present_in_emitted_html():
    """The overlay JS exposes the four required researcher actions
    (Accept / Reject / Reply / Send back) — sanity-check the source."""
    html = render_report(_card(), "scout", "p")
    js = html.split('<script>')[-1].split('</script>')[0]
    for label in ('"Accept"', '"Reject"', '"Reply"', '"Send back ↩"'):
        assert label in js, label


def test_overlay_uses_file_system_access_api_with_download_fallback():
    """Spec §D-4: round-trip via FSA API + Download-annotated-copy
    fallback for non-Chromium browsers."""
    html = render_report(_card(), "scout", "p")
    assert "showSaveFilePicker" in html
    assert "URL.createObjectURL" in html  # the Download fallback
