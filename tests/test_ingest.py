"""3b: inbox + .manifest.json delta ingest (idempotent, inbox→raw)."""

from __future__ import annotations

import json

from helix.core.atlas import Atlas
from helix.core.ingest import ingest_inbox


def _drop(atlas_root, name, text):
    inbox = atlas_root / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / name).write_text(text)


def test_inbox_ingest_creates_source_pages_and_moves_to_raw(tmp_path):
    root = tmp_path / "atlas"
    a = Atlas(root)
    _drop(root, "Chen 2025.md", "rPPG findings")
    _drop(root, "notes.txt", "side notes")

    res = ingest_inbox(a)
    assert res["new"] == 2 and sorted(res["ingested"]) == ["Chen 2025.md", "notes.txt"]

    pg = a.get("sources/chen-2025.md")          # slugged
    assert pg is not None and pg.meta.type == "source"
    assert pg.meta.aliases == ["Chen 2025"]
    # original moved out of inbox into raw/
    assert not (root / "inbox" / "Chen 2025.md").exists()
    assert (root / "raw" / "Chen 2025.md").read_text() == "rPPG findings"
    # manifest records sha256 per file
    man = json.loads((root / "inbox" / ".manifest.json").read_text())
    assert set(man["ingested"]) == {"inbox/Chen 2025.md", "inbox/notes.txt"}
    assert len(man["ingested"]["inbox/notes.txt"]["sha256"]) == 64


def test_reingest_is_idempotent(tmp_path):
    root = tmp_path / "atlas"
    a = Atlas(root)
    _drop(root, "p.md", "content")
    assert ingest_inbox(a)["new"] == 1
    _drop(root, "p.md", "content")               # identical bytes again
    res = ingest_inbox(a)
    assert res["new"] == 0 and res["skipped"] == 1


def test_modified_file_reingested(tmp_path):
    root = tmp_path / "atlas"
    a = Atlas(root)
    _drop(root, "p.md", "v1")
    ingest_inbox(a)
    created = a.get("sources/p.md").meta.created_at
    _drop(root, "p.md", "v2 different")          # new sha
    assert ingest_inbox(a)["new"] == 1
    pg = a.get("sources/p.md")
    assert "v2 different" in pg.content
    assert pg.meta.created_at == created          # update, not recreate


def test_per_file_ingest(tmp_path):
    root = tmp_path / "atlas"
    a = Atlas(root)
    _drop(root, "a.md", "aaa")
    _drop(root, "b.md", "bbb")
    res = ingest_inbox(a, only="inbox/a.md")
    assert res["new"] == 1 and res["ingested"] == ["a.md"]
    assert (root / "inbox" / "b.md").exists()      # untouched
