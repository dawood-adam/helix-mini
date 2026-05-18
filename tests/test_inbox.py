"""Frictionless inbox ingest: drop a file, it becomes a searchable source."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from helix import config
from helix.cli import cli
from helix.core.atlas import Atlas
from helix.core.inbox import inbox_dir, ingest_inbox, pending_count


@pytest.fixture
def atlas_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIX_HOME", str(tmp_path))
    return tmp_path


def test_drop_and_ingest_makes_searchable_source(atlas_home):
    box = inbox_dir()
    (box / "cardiac.md").write_text("# Cardiac\nCFD simulation of the aorta.")
    (box / "notes.txt").write_text("orthostatic maneuver protocol")
    assert pending_count() == 2

    summary = ingest_inbox()

    assert len(summary["ingested"]) == 2
    assert summary["pending"] == 0
    # Inbox is cleared; originals archived.
    assert not list(box.glob("*.md")) and not list(box.glob("*.txt"))
    raw = config.atlas_path() / "raw" / "inbox"
    assert (raw / "cardiac.md").exists() and (raw / "notes.txt").exists()
    # Now a first-class, searchable Atlas source.
    hits = Atlas(config.atlas_path()).read("cardiac")
    assert any("CFD simulation" in p.content for p in hits)
    # Manifest recorded provenance.
    m = json.loads((box / ".manifest.json").read_text())
    assert len(m["ingested"]) == 2


def test_ingest_is_idempotent(atlas_home):
    box = inbox_dir()
    (box / "paper.md").write_text("rPPG amplitude noise floor study")
    ingest_inbox()
    pages_after_first = len(list((config.atlas_path() / "sources").glob("*.md")))

    # Same content dropped again -> recognized by sha, skipped, no dup page.
    (box / "paper.md").write_text("rPPG amplitude noise floor study")
    summary = ingest_inbox()
    assert summary["ingested"] == [] and summary["skipped"] == 1
    assert len(list((config.atlas_path() / "sources").glob("*.md"))) == pages_after_first


def test_single_path_and_unsupported_skipped(atlas_home):
    box = inbox_dir()
    (box / "keep.md").write_text("alpha beta gamma")
    (box / "blob.bin").write_bytes(b"\x00\x01\x02")

    summary = ingest_inbox(path="keep.md")
    assert [i["file"] for i in summary["ingested"]] == ["keep.md"]
    # Unsupported binary is left untouched, not ingested.
    assert (box / "blob.bin").exists()


def test_cli_ingest_and_status(atlas_home, monkeypatch):
    monkeypatch.chdir(atlas_home)
    (inbox_dir() / "lupus-cohort.md").write_text("lupus case series cohort")
    r = CliRunner().invoke(cli, ["atlas", "ingest"])
    assert r.exit_code == 0 and "lupus-cohort.md -> sources/" in r.output

    s = CliRunner().invoke(cli, ["status"])
    assert s.exit_code == 0 and "Inbox:" not in s.output  # cleared after ingest
    found = CliRunner().invoke(cli, ["atlas", "search", "lupus"])
    assert "lupus case series" in found.output
