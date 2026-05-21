"""Workstream B + F.2/F.3 — spec schema, question_check, clarify loop.

Covers: spec frontmatter round-trip; ``question_check`` finds missing
FINER / PICOT / GQM axes, unresolved [NEEDS CLARIFICATION] markers,
``TODO:`` / ``@open-question:`` markers, and a not-ready gate;
``apply_clarification`` does anchored SEARCH/REPLACE; the MCP tools
(``hx_question_check`` · ``hx_clarify``) drive over the in-memory client.
"""

from __future__ import annotations

import pytest

from helix.core import spec as _spec


# --- Parse / save round-trip ----------------------------------------------


def test_spec_round_trip_preserves_frontmatter_and_body(tmp_path):
    sp = _spec.Spec(
        frontmatter={
            "finer": {"feasible": "yes", "interesting": "yes",
                       "novel": "yes", "ethical": "yes", "relevant": "yes"},
            "picot": {"population": "p", "intervention": "i",
                       "outcome": "o"},
            "gqm": {"goal": "g", "questions": ["q1"],
                     "metrics": ["m1"]},
            "datasets": ["ds1"],
            "open_questions": [],
            "gate": {"status": "ready"},
        },
        body="# Spec\n\nfull text\n",
    )
    p = _spec.save_spec(tmp_path / "atlas", "p1", sp)
    assert p.exists()
    back = _spec.load_spec(tmp_path / "atlas", "p1")
    assert back.frontmatter["finer"]["feasible"] == "yes"
    assert back.body.startswith("# Spec")


def test_load_question_falls_back_to_source_folder(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "question.md").write_text(
        "---\nfiner: {feasible: 'y'}\n---\n\n# Question\nWhat is X?\n")
    q = _spec.load_question(folder)
    assert q.frontmatter["finer"]["feasible"] == "y"
    assert "What is X" in q.body


# --- question_check -------------------------------------------------------


def _bare(tmp_path) -> tuple:
    """Save an empty-but-present spec and return (root, project)."""
    root = tmp_path / "atlas"
    _spec.save_spec(root, "p1", _spec.Spec(frontmatter={}, body="# Spec\n"))
    return root, "p1"


def test_question_check_flags_missing_finer_picot_gqm(tmp_path):
    root, proj = _bare(tmp_path)
    qc = _spec.question_check(root, proj)
    kinds = {f.kind for f in qc.findings}
    assert "missing-finer" in kinds
    assert "missing-picot" in kinds
    assert "missing-gqm" in kinds
    assert "gate-not-ready" in kinds
    assert qc.ok is False


def test_question_check_flags_clarification_markers(tmp_path):
    root, proj = _bare(tmp_path)
    sp = _spec.load_spec(root, proj)
    sp.body = (
        "# Spec\n\nWe will study [NEEDS CLARIFICATION: which population?].\n"
        "TODO: name the metric\n"
        "Next steps @open-question: how do we measure baseline?\n"
    )
    _spec.save_spec(root, proj, sp)
    qc = _spec.question_check(root, proj)
    markers = [f for f in qc.findings if f.kind == "clarification-marker"]
    assert len(markers) == 3
    where = [m.where for m in markers]
    assert any("population" in w for w in where)
    assert any("metric" in w for w in where)
    assert any("baseline" in w for w in where)


def test_question_check_passes_when_complete(tmp_path):
    root = tmp_path / "atlas"
    sp = _spec.Spec(frontmatter={
        "finer": {ax: "ok" for ax in
                   ("feasible", "interesting", "novel", "ethical", "relevant")},
        "picot": {"population": "p", "intervention": "i", "outcome": "o"},
        "gqm": {"goal": "g", "questions": ["q"], "metrics": ["m"]},
        "gate": {"status": "ready"},
    }, body="# Spec\n\nclean prose, no markers.\n")
    _spec.save_spec(root, "p1", sp)
    qc = _spec.question_check(root, "p1")
    assert qc.ok and qc.findings == []


def test_question_check_falls_back_to_question_md(tmp_path):
    root = tmp_path / "atlas"
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "question.md").write_text(
        "---\n{}\n---\n\n# Q\nbody\n")  # empty frontmatter
    qc = _spec.question_check(root, "p1", source_folder=folder)
    # No spec.md AND a question.md → run the same checks against the question.
    assert any(f.kind == "missing-finer" for f in qc.findings)


# --- Clarify SEARCH/REPLACE -----------------------------------------------


def test_apply_clarification_patches_marker_in_place():
    text = "We study [NEEDS CLARIFICATION: which population?] over time."
    new, ok = _spec.apply_clarification(
        text, "which population?", "adults 18-65")
    assert ok and "adults 18-65" in new and "NEEDS CLARIFICATION" not in new
    # Idempotent: re-running with the same args (marker gone) returns ok=False.
    again, ok2 = _spec.apply_clarification(
        new, "which population?", "adults 18-65")
    assert ok2 is False and again == new


def test_apply_clarification_handles_todo_and_at_open_question():
    text = "TODO: name the metric\nand @open-question: baseline?"
    new, ok = _spec.apply_clarification(text, "name the metric", "accuracy")
    assert ok and "accuracy" in new
    new2, ok2 = _spec.apply_clarification(new, "baseline?", "median group")
    assert ok2 and "median group" in new2


def test_apply_clarification_fails_silently_on_missing_marker():
    new, ok = _spec.apply_clarification("plain text", "no such marker", "x")
    assert ok is False and new == "plain text"


# --- Security: project-name confinement (regression for path traversal) ---


def test_spec_path_rejects_traversal_in_project_name(tmp_path):
    """A path-traversal attempt in ``project`` (e.g. ``../../secret``)
    must be blocked by ``validate_project_name`` — the same rule
    snapshots / runs / hot use. Without this, MCP tools could read or
    overwrite ``spec.md`` files outside the active workspace."""
    from helix.sandbox import SandboxError

    for unsafe in ("../escape", "..", ".hidden", "a/b", "a\\b", ""):
        with pytest.raises(SandboxError):
            _spec.spec_path(tmp_path / "atlas", unsafe)
        with pytest.raises(SandboxError):
            _spec.load_spec(tmp_path / "atlas", unsafe)
        with pytest.raises(SandboxError):
            _spec.save_spec(tmp_path / "atlas", unsafe,
                            _spec.Spec(frontmatter={}, body="x"))
        with pytest.raises(SandboxError):
            _spec.question_check(tmp_path / "atlas", unsafe)


def test_hx_question_check_returns_clean_error_on_traversal(project):
    """The MCP tool surfaces a sandbox-rejection message and never
    triggers the file read."""
    from helix.mcp.server import _question_check

    out = _question_check(folder=str(project), project="../escape")
    assert "Rejected (sandbox)" in out
    # And the rejection mentions WHY (the unsafe name).
    assert "escape" in out.lower() or "unsafe" in out.lower()


def test_hx_clarify_returns_clean_error_on_traversal(project):
    """``_clarify`` is normally invoked through the MCP ``_drive``
    wrapper, but the same sandbox guard fires before any elicitation
    runs. We can drive ``_clarify`` directly with a stub IO since the
    rejection happens before the first elicit."""
    from helix.mcp.server import _clarify

    class _StubIO:
        def elicit(self, req):  # never called when sandbox blocks
            raise AssertionError("elicit must not run on a rejected project")

    out = _clarify(_StubIO(), str(project), "../escape")
    assert "Rejected (sandbox)" in out


# --- MCP tools ------------------------------------------------------------


pytest.importorskip("mcp")


def test_hx_question_check_returns_findings(project):
    from helix import config
    from helix.mcp.server import _question_check

    # No spec yet → falls back to question.md (which conftest fixture didn't
    # create) → "missing-spec" finding.
    out = _question_check(folder=str(project), project="src-papers")
    # The output is a string; with no spec/question we get a clear blocker.
    assert "missing-spec" in out or "finding" in out

    # Now seed a bare spec → it should report missing FINER / PICOT / GQM /
    # gate.
    sp = _spec.Spec(frontmatter={}, body="# Spec\n")
    _spec.save_spec(config.atlas_path(), "src-papers", sp)
    out2 = _question_check(folder=str(project), project="src-papers")
    assert "missing-finer" in out2 and "missing-picot" in out2
    assert "missing-gqm" in out2 and "gate-not-ready" in out2


def test_hx_question_check_passes_for_ready_spec(project):
    from helix import config
    from helix.mcp.server import _question_check

    sp = _spec.Spec(frontmatter={
        "finer": {ax: "ok" for ax in
                   ("feasible", "interesting", "novel", "ethical", "relevant")},
        "picot": {"population": "p", "intervention": "i", "outcome": "o"},
        "gqm": {"goal": "g", "questions": ["q"], "metrics": ["m"]},
        "gate": {"status": "ready"},
    }, body="# Spec\n\nclean.\n")
    _spec.save_spec(config.atlas_path(), "src-papers", sp)
    out = _question_check(folder=str(project), project="src-papers")
    assert "ready" in out.lower()


def test_hx_clarify_drives_search_replace_via_elicitation(project):
    """End-to-end: seed a spec with one [NEEDS CLARIFICATION], drive
    hx_clarify with a scripted elicitation, assert the marker is gone."""
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session as conn

    import mcp.types as T
    from helix import config
    from helix.mcp.server import mcp as server

    sp = _spec.Spec(frontmatter={}, body=(
        "# Spec\n\nWe will study [NEEDS CLARIFICATION: which dataset?].\n"))
    _spec.save_spec(config.atlas_path(), "src-papers", sp)

    async def elicit_cb(context, params):
        return T.ElicitResult(
            action="accept", content={"answer": "CIFAR-10"})

    async def drive():
        async with conn(server, elicitation_callback=elicit_cb) as client:
            await client.initialize()
            res = await client.call_tool("hx_clarify", {
                "folder": str(project), "project": "src-papers",
            })
            txt = "".join(c.text for c in res.content if c.type == "text")
            return res.isError, txt

    is_error, txt = anyio.run(drive)
    assert is_error is False, txt
    assert "1 patched" in txt and "0 remaining" in txt
    new = _spec.load_spec(config.atlas_path(), "src-papers")
    assert "CIFAR-10" in new.body
    assert "NEEDS CLARIFICATION" not in new.body
