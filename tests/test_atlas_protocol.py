"""Workstream G — Atlas write protocol.

Closed action vocabulary (ADD/UPDATE/SUPERSEDE/LINK/NOOP), a one-line
``because`` rationale, mandatory ``provenance``, and a spec cross-reference
(``spec_refs``). The sanitizer applies compat defaults so older agents keep
working; the page frontmatter persists history + spec_refs so the
orphan-by-policy lint can flag pages that didn't ground in spec. The
``hx_atlas_propose`` MCP tool is the dedup gate the agent runs before ADD;
``hx_atlas_reconcile`` is the periodic sweep.
"""

from __future__ import annotations

import json

import pytest
import yaml

from helix.core.atlas import Atlas, PageWrite
from helix.core.lint import lint
from helix.sandbox import sanitize_atlas_writes


# --- Sanitizer: action vocabulary + compat defaults ------------------------


def test_sanitize_normalizes_known_action(tmp_path):
    writes = sanitize_atlas_writes([{
        "path": "concepts/a.md", "title": "A", "content": "c", "summary": "s",
        "action": "update", "because": "fixed a typo",
        "provenance": {"stage": "scout", "run_id": "r1", "snapshot_id": "s1"},
        "spec_refs": ["spec:0001:G.1"],
    }], tmp_path)
    assert len(writes) == 1
    w = writes[0]
    assert w.action == "UPDATE"
    assert w.because == "fixed a typo"
    assert w.provenance == {"stage": "scout", "run_id": "r1",
                             "snapshot_id": "s1"}
    assert w.spec_refs == ["spec:0001:G.1"]


def test_sanitize_unknown_action_defaults_to_add(tmp_path, caplog):
    with caplog.at_level("WARNING"):
        writes = sanitize_atlas_writes([{
            "path": "concepts/a.md", "title": "A", "content": "c",
            "summary": "s", "action": "DELETE",
        }], tmp_path)
    assert writes[0].action == "ADD"
    assert any("Unknown atlas action" in r.message for r in caplog.records)


def test_sanitize_missing_action_defaults_with_rationale(tmp_path):
    writes = sanitize_atlas_writes([{
        "path": "concepts/a.md", "title": "A", "content": "c", "summary": "s",
    }], tmp_path)
    assert writes[0].action == "ADD"
    assert "no action declared" in writes[0].because


def test_sanitize_strips_control_chars_in_provenance(tmp_path):
    writes = sanitize_atlas_writes([{
        "path": "concepts/a.md", "title": "A", "content": "c", "summary": "s",
        "action": "ADD",
        "provenance": {"stage": "scout\x00", "run_id": "  r1  ",
                       "snapshot_id": "s1", "junk_key": "ignored"},
    }], tmp_path)
    p = writes[0].provenance
    assert p == {"stage": "scout", "run_id": "r1", "snapshot_id": "s1"}


def test_sanitize_provenance_keeps_sources_list(tmp_path):
    writes = sanitize_atlas_writes([{
        "path": "concepts/a.md", "title": "A", "content": "c", "summary": "s",
        "provenance": {"stage": "scout",
                       "sources": ["sources/p1.md", "  ", "sources/p2.md"]},
    }], tmp_path)
    assert writes[0].provenance["sources"] == ["sources/p1.md", "sources/p2.md"]


# --- Atlas: write-protocol fields are persisted in frontmatter -------------


def test_atlas_persists_history_and_spec_refs(tmp_path):
    a = Atlas(tmp_path / "atlas")
    a.write([PageWrite(
        "concepts/x.md", "X", "body", "sum",
        action="ADD", because="first cut",
        provenance={"stage": "scout", "run_id": "r1", "snapshot_id": "s1"},
        spec_refs=["spec:0001:G.1"],
    )], "scout/atlas")
    raw = (tmp_path / "atlas" / "concepts" / "x.md").read_text()
    fm = yaml.safe_load(raw.split("---", 2)[1])
    assert fm["spec_refs"] == ["spec:0001:G.1"]
    assert fm["provenance"]["run_id"] == "r1"
    assert len(fm["history"]) == 1
    h = fm["history"][0]
    assert h["action"] == "ADD" and h["because"] == "first cut"
    assert h["run_id"] == "r1" and h["spec_refs"] == ["spec:0001:G.1"]


def test_atlas_merges_provenance_and_appends_history(tmp_path):
    a = Atlas(tmp_path / "atlas")
    a.write([PageWrite(
        "concepts/x.md", "X", "v1", "sum",
        action="ADD", because="first",
        provenance={"stage": "scout", "run_id": "r1"},
        spec_refs=["spec:0001:G.1"],
    )], "scout")
    a.write([PageWrite(
        "concepts/x.md", "X", "v2", "sum",
        action="UPDATE", because="refined",
        provenance={"stage": "critic_methods", "run_id": "r2",
                    "snapshot_id": "s2"},
        spec_refs=["spec:0001:G.2"],
    )], "critic")
    fm = yaml.safe_load(
        (tmp_path / "atlas" / "concepts" / "x.md").read_text().split("---", 2)[1])
    # Provenance overlays — most recent run wins, prior keys preserved.
    assert fm["provenance"]["run_id"] == "r2"
    assert fm["provenance"]["snapshot_id"] == "s2"
    assert fm["provenance"]["stage"] == "critic_methods"
    # Spec refs accumulate, deduped.
    assert fm["spec_refs"] == ["spec:0001:G.1", "spec:0001:G.2"]
    # History keeps both entries.
    assert [h["action"] for h in fm["history"]] == ["ADD", "UPDATE"]


def test_atlas_legacy_writes_have_no_history(tmp_path):
    """A direct PageWrite with no action/because/spec_refs (the
    pre-Workstream-G path) leaves the history list empty so the
    orphan-by-policy lint stays silent on legacy pages."""
    a = Atlas(tmp_path / "atlas")
    a.write([PageWrite("concepts/x.md", "X", "body", "sum")], "legacy")
    fm = yaml.safe_load(
        (tmp_path / "atlas" / "concepts" / "x.md").read_text().split("---", 2)[1])
    assert fm["history"] == [] and fm["spec_refs"] == []


# --- Lint: orphan-by-policy -------------------------------------------------


def test_lint_orphan_by_policy_fires_on_protocol_pages_without_spec_refs(tmp_path):
    a = Atlas(tmp_path / "atlas")
    a.write([PageWrite(
        "concepts/no_refs.md", "NoRefs", "body", "sum",
        aliases=["NoRefs", "without"],
        action="ADD", because="forgot to ground",
        provenance={"stage": "scout"},
    )], "scout")
    a.write([PageWrite(
        "concepts/grounded.md", "Grounded", "body", "sum",
        aliases=["Grounded", "with"],
        action="ADD", because="grounded in spec",
        provenance={"stage": "scout"},
        spec_refs=["spec:0001:G.3"],
    )], "scout")
    issues = lint(tmp_path / "atlas")
    flagged = {i["page"] for i in issues if i["kind"] == "orphan-by-policy"}
    assert "atlas:concepts:no_refs" in flagged
    assert "atlas:concepts:grounded" not in flagged


def test_lint_orphan_by_policy_silent_for_legacy_pages(tmp_path):
    a = Atlas(tmp_path / "atlas")
    # Pre-protocol direct writes: no history, no spec_refs — must NOT fire.
    a.write([PageWrite("concepts/legacy.md", "Legacy", "body", "sum",
                       aliases=["Legacy", "old"])], "legacy")
    issues = lint(tmp_path / "atlas")
    assert not any(i["kind"] == "orphan-by-policy" for i in issues)


def test_lint_orphan_by_policy_skips_sources_and_archived(tmp_path):
    a = Atlas(tmp_path / "atlas")
    # A source is exempt by type even after the protocol touches it.
    a.write([PageWrite(
        "sources/paper.md", "Paper", "body", "sum",
        action="ADD", because="ingested",
        provenance={"stage": "ingest"},
    )], "ingest")
    # An archived concept is exempt by tier.
    a.write([PageWrite(
        "concepts/old.md", "Old", "body", "sum",
        aliases=["Old", "retired"],
        tier="archived",
        action="ADD", because="archived for posterity",
        provenance={"stage": "scout"},
    )], "scout")
    issues = lint(tmp_path / "atlas")
    flagged = {i["page"] for i in issues if i["kind"] == "orphan-by-policy"}
    assert "atlas:sources:paper" not in flagged
    assert "atlas:concepts:old" not in flagged


# --- MCP tools: hx_atlas_propose + hx_atlas_reconcile ----------------------

pytest.importorskip("mcp")
from helix.mcp.server import _propose, _reconcile  # noqa: E402


def test_propose_no_near_duplicates_on_empty_atlas(project):
    out = _propose(json.dumps({
        "path": "concepts/new.md", "title": "Brand new concept",
        "content": "body", "summary": "sum", "action": "ADD",
        "because": "first ever",
        "provenance": {"stage": "scout", "run_id": "r1"},
        "spec_refs": ["spec:0001:G.1"],
    }))
    assert "ok: no near duplicates" in out


def test_propose_flags_near_duplicate(project):
    from helix import config

    # Seed an existing concept and propose another with overlapping wording.
    a = Atlas(config.atlas_path())
    a.write([PageWrite(
        "concepts/rppg.md", "remote photoplethysmography",
        "remote photoplethysmography is a technique to measure pulse from "
        "video without contact, using subtle skin colour changes.",
        "sum", aliases=["rPPG", "remote photoplethysmography"])], "seed")
    out = _propose(json.dumps({
        "path": "concepts/rppg2.md", "title": "remote photoplethysmography",
        "content": "remote photoplethysmography technique notes",
        "summary": "sum", "action": "ADD",
        "because": "duplicate try",
        "provenance": {"stage": "scout", "run_id": "r1"},
    }))
    assert out.startswith("DEDUP:")
    assert "rppg" in out.lower()


def test_propose_non_add_action_short_circuits(project):
    out = _propose(json.dumps({
        "path": "concepts/x.md", "title": "X", "content": "c", "summary": "s",
        "action": "UPDATE", "because": "refine",
        "provenance": {"stage": "scout"},
    }))
    assert "ok (UPDATE)" in out


def test_propose_rejects_bad_json(project):
    out = _propose("{not json")
    assert "Bad write_json" in out


def test_propose_rejects_unsafe_path(project):
    out = _propose(json.dumps({
        "path": "../escape.md", "title": "X", "content": "c", "summary": "s",
    }))
    assert "Rejected (sandbox)" in out


def test_reconcile_summarises_lint_and_promotion_candidates(project):
    from helix import config

    # Seed a small Atlas with: a protocol page missing spec_refs (→
    # orphan-by-policy) + a hub concept with three inbound links (→
    # promotion candidate).
    a = Atlas(config.atlas_path())
    a.write([
        PageWrite("concepts/hub.md", "Hub", "body", "sum",
                  aliases=["Hub", "centre"], tier="active"),
        PageWrite("concepts/a.md", "A", "body", "sum",
                  aliases=["A", "alpha"],
                  links={"related_to": ["atlas:concepts:hub"]}),
        PageWrite("concepts/b.md", "B", "body", "sum",
                  aliases=["B", "beta"],
                  links={"related_to": ["atlas:concepts:hub"]}),
        PageWrite("concepts/c.md", "C", "body", "sum",
                  aliases=["C", "gamma"],
                  links={"related_to": ["atlas:concepts:hub"]}),
        PageWrite("concepts/np.md", "NoPolicy", "body", "sum",
                  aliases=["NoPolicy", "ungrounded"],
                  action="ADD", because="forgot spec",
                  provenance={"stage": "scout"}),
    ], "seed")
    out = _reconcile()
    assert out.startswith("Reconcile:")
    assert "[orphan-by-policy]" in out
    assert "atlas:concepts:np" in out
    assert "[promotion-candidate]" in out
    assert "atlas:concepts:hub" in out
