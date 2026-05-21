"""Workstream E — threads (longitudinal artifacts) + F.4 glossary.

Covers: the thread schema and status machine (Proposed → Accepted →
Superseded); ``append_update`` preserves per-snapshot history and is
idempotent on re-runs; bi-temporal ``read_at`` truncates the body to a
snapshot; the glossary parser drives F.4's vocabulary-drift lint;
``thread://`` and ``thread-at://`` MCP resources resolve."""

from __future__ import annotations

import pytest
import yaml

from helix.core import threads


# --- Schema / status machine -----------------------------------------------


def test_ensure_thread_creates_proposed_stub(tmp_path):
    root = tmp_path / "atlas"
    t = threads.ensure_thread(root, "p1", "data", contributor="scout")
    assert t.status == "Proposed"
    assert t.opened_at and t.last_touched_at
    assert "scout" in t.contributors
    # Persisted on disk at the expected path.
    p = root / "projects" / "p1" / "threads" / "data.md"
    assert p.exists()
    fm = yaml.safe_load(p.read_text().split("---", 2)[1])
    assert fm["thread"] == "data" and fm["status"] == "Proposed"


def test_ensure_thread_is_idempotent(tmp_path):
    root = tmp_path / "atlas"
    t1 = threads.ensure_thread(root, "p1", "glossary")
    t2 = threads.ensure_thread(root, "p1", "glossary")
    assert t1.opened_at == t2.opened_at
    assert t1.status == t2.status == "Proposed"


def test_set_status_legal_transitions(tmp_path):
    root = tmp_path / "atlas"
    threads.ensure_thread(root, "p1", "design")
    t = threads.set_status(root, "p1", "design", "Accepted")
    assert t.status == "Accepted"
    t = threads.set_status(root, "p1", "design", "Superseded")
    assert t.status == "Superseded"


def test_set_status_rejects_illegal_transition(tmp_path):
    root = tmp_path / "atlas"
    threads.ensure_thread(root, "p1", "design")
    threads.set_status(root, "p1", "design", "Superseded")
    with pytest.raises(threads.ThreadError):
        # Superseded → Accepted is not allowed.
        threads.set_status(root, "p1", "design", "Accepted")


def test_unknown_thread_raises(tmp_path):
    with pytest.raises(threads.ThreadError):
        threads.ensure_thread(tmp_path / "atlas", "p1", "frobnitz")


# --- Security: project-name confinement (regression for path traversal) ---


def test_resolve_path_rejects_traversal_in_project_name(tmp_path):
    """A path-traversal attempt in ``project`` (e.g. ``../../secret``)
    must be blocked by ``validate_project_name`` — the same rule that
    confines snapshots, runs, hot, and atlas writes. Without this, an
    MCP client could read files outside the atlas via the ``thread://``
    resource."""
    root = tmp_path / "atlas"
    for unsafe in ("../escape", "..", ".hidden", "a/b", "a\\b", ""):
        with pytest.raises(threads.ThreadError):
            threads.load_thread(root, unsafe, "data")
        with pytest.raises(threads.ThreadError):
            threads.ensure_thread(root, unsafe, "data")
        with pytest.raises(threads.ThreadError):
            threads.read_at(root, unsafe, "data", "snap-1")


def test_thread_resources_block_traversal_attempt(project):
    """The MCP ``thread://`` resource handlers must surface the
    rejection cleanly rather than leak file contents from outside the
    atlas root."""
    import anyio

    from mcp.shared.memory import create_connected_server_and_client_session as conn
    from helix.mcp.server import mcp as server

    async def drive():
        async with conn(server) as client:
            await client.initialize()
            res = await client.read_resource(
                "thread://..%2Fescape/data")
            txt = "".join(c.text for c in res.contents
                          if hasattr(c, "text"))
            return txt

    out = anyio.run(drive)
    # The resource returns a clean error message; no file contents leak.
    assert "invalid thread" in out.lower() or "unsafe" in out.lower()


# --- append_update ---------------------------------------------------------


def test_append_update_preserves_history_per_snapshot(tmp_path):
    root = tmp_path / "atlas"
    threads.append_update(root, "p1", "data", "snap-1", "ingested CIFAR-10.")
    threads.append_update(root, "p1", "data", "snap-2", "split 80/20.")
    body = threads.load_thread(root, "p1", "data").body
    assert "## snap-1" in body and "ingested CIFAR-10" in body
    assert "## snap-2" in body and "split 80/20" in body
    # Order matters: snap-1 before snap-2.
    assert body.index("snap-1") < body.index("snap-2")


def test_append_update_is_idempotent_on_same_snapshot(tmp_path):
    """A send-back re-runs a stage; the new write should REPLACE the
    section for that snapshot rather than append a duplicate."""
    root = tmp_path / "atlas"
    threads.append_update(root, "p1", "data", "snap-1", "first try")
    threads.append_update(root, "p1", "data", "snap-1", "second (better) try")
    body = threads.load_thread(root, "p1", "data").body
    assert body.count("## snap-1") == 1
    assert "second (better) try" in body
    assert "first try" not in body


def test_append_update_optionally_transitions_status(tmp_path):
    root = tmp_path / "atlas"
    t = threads.append_update(
        root, "p1", "data", "snap-1", "first cut", status="Accepted")
    assert t.status == "Accepted"


def test_append_update_accumulates_contributors(tmp_path):
    root = tmp_path / "atlas"
    threads.append_update(
        root, "p1", "design", "snap-1", "v1", contributor="planner")
    threads.append_update(
        root, "p1", "design", "snap-2", "v2", contributor="builder")
    t = threads.load_thread(root, "p1", "design")
    assert "planner" in t.contributors and "builder" in t.contributors


# --- Bi-temporal read ------------------------------------------------------


def test_read_at_truncates_to_snapshot(tmp_path):
    root = tmp_path / "atlas"
    threads.append_update(root, "p1", "data", "snap-1", "v1 body")
    threads.append_update(root, "p1", "data", "snap-2", "v2 body")
    threads.append_update(root, "p1", "data", "snap-3", "v3 body")
    at_2 = threads.read_at(root, "p1", "data", "snap-2")
    assert "v1 body" in at_2.body and "v2 body" in at_2.body
    assert "v3 body" not in at_2.body


def test_read_at_unknown_snapshot_returns_prelude_only(tmp_path):
    root = tmp_path / "atlas"
    threads.ensure_thread(root, "p1", "data")
    threads.append_update(root, "p1", "data", "snap-1", "v1 body")
    at_x = threads.read_at(root, "p1", "data", "snap-does-not-exist")
    assert "v1 body" not in at_x.body


# --- Glossary parser (drives the vocabulary-drift lint) --------------------


def test_parse_glossary_terms_picks_up_term_headings(tmp_path):
    root = tmp_path / "atlas"
    t = threads.ensure_thread(root, "p1", "glossary")
    t.body = (
        "# Glossary (Ubiquitous Language)\n\n"
        "### rPPG\nremote photoplethysmography.\n\n"
        "### Hypothesis\na falsifiable claim about the world.\n"
    )
    threads.save_thread(root, "p1", t)
    parsed = threads.parse_glossary_terms(
        threads.load_thread(root, "p1", "glossary"))
    assert set(parsed) == {"rppg", "hypothesis"}
    assert "photoplethysmography" in parsed["rppg"]


# --- Lint extensions: orphan-thread / dataset-* / vocabulary-drift ---------


def test_lint_flags_orphan_thread_once_project_opts_in(tmp_path):
    from helix.core.atlas import Atlas
    from helix.core.lint import lint
    a = Atlas(tmp_path / "atlas")  # noqa: F841 -- triggers structure scaffold
    # A project with a design thread is "opted in"; data + glossary are
    # the core threads we expect.
    threads.ensure_thread(tmp_path / "atlas", "p1", "design")
    issues = lint(tmp_path / "atlas")
    missing = {(i["project"], i["thread"]) for i in issues
               if i["kind"] == "orphan-thread"}
    assert ("p1", "data") in missing and ("p1", "glossary") in missing


def test_lint_silent_when_no_thread_or_spec(tmp_path):
    from helix.core.atlas import Atlas
    from helix.core.lint import lint
    Atlas(tmp_path / "atlas")  # scaffold, no threads
    issues = lint(tmp_path / "atlas")
    assert not any(i["kind"] == "orphan-thread" for i in issues)


def test_lint_flags_dataset_without_license_or_source(tmp_path):
    from helix.core.atlas import Atlas
    from helix.core.lint import lint
    Atlas(tmp_path / "atlas")
    ds = tmp_path / "atlas" / "entities" / "datasets"
    ds.mkdir(parents=True, exist_ok=True)
    (ds / "cifar.md").write_text(
        "---\n"
        "thread: cifar\n"
        "license: ''\n"  # blank
        "source: 'https://www.cs.toronto.edu/~kriz/cifar.html'\n"
        "---\n\n# CIFAR-10\n"
    )
    (ds / "secret.md").write_text(
        "---\n"
        "thread: secret\n"
        "license: 'MIT'\n"
        # no source
        "---\n\n# Secret dataset\n"
    )
    issues = lint(tmp_path / "atlas")
    flagged = {(i["kind"], i["file"]) for i in issues
               if i["kind"].startswith("dataset-")}
    assert ("dataset-without-license", "entities/datasets/cifar.md") in flagged
    assert ("dataset-without-source", "entities/datasets/secret.md") in flagged


def test_lint_flags_vocabulary_drift(tmp_path):
    from helix.core.atlas import Atlas
    from helix.core.lint import lint
    Atlas(tmp_path / "atlas")
    # Seed a glossary with one term, then a spec that uses both that term
    # AND an undefined one.
    t = threads.ensure_thread(tmp_path / "atlas", "p1", "glossary")
    t.body = "# Glossary\n\n### rPPG\nremote photoplethysmography.\n"
    threads.save_thread(tmp_path / "atlas", "p1", t)
    spec = tmp_path / "atlas" / "projects" / "p1" / "spec.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(
        "# Spec\n\nWe will use **rPPG** to estimate **blood pressure** via "
        "video.\n")
    issues = lint(tmp_path / "atlas")
    drift = {i["term"] for i in issues if i["kind"] == "vocabulary-drift"}
    assert "blood pressure" in drift and "rppg" not in drift


def test_lint_vocabulary_drift_silent_without_glossary(tmp_path):
    from helix.core.atlas import Atlas
    from helix.core.lint import lint
    Atlas(tmp_path / "atlas")
    spec = tmp_path / "atlas" / "projects" / "p1" / "spec.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text("# Spec\n\nWe will use **rPPG**.\n")
    issues = lint(tmp_path / "atlas")
    assert not any(i["kind"] == "vocabulary-drift" for i in issues)


# --- MCP resource ----------------------------------------------------------


pytest.importorskip("mcp")


def test_thread_resources_resolve_over_mcp(project):
    """Drive the in-memory MCP client, read the thread URIs back."""
    import anyio

    from mcp.shared.memory import create_connected_server_and_client_session as conn
    from helix import config
    from helix.mcp.server import mcp as server

    # Seed a thread + a snapshotted update.
    threads.append_update(config.atlas_path(), "src-papers", "data",
                          "snap-1", "ingested CIFAR-10")

    async def drive():
        async with conn(server) as client:
            await client.initialize()
            cur = await client.read_resource("thread://src-papers/data")
            past = await client.read_resource(
                "thread-at://src-papers/data/snap-1")
            txt = lambda r: "".join(c.text for c in r.contents
                                    if hasattr(c, "text"))
            return txt(cur), txt(past)

    cur, past = anyio.run(drive)
    assert "thread: data" in cur and "## snap-1" in cur
    assert "## snap-1" in past
