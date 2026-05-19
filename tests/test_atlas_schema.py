"""3a: every page carries valid frontmatter; minimal writes still work."""

from __future__ import annotations

import yaml

from helix.core.atlas import TIERS, TYPES, Atlas, PageWrite
from helix.sandbox import sanitize_atlas_writes


def test_minimal_write_gets_default_frontmatter(tmp_path):
    a = Atlas(tmp_path / "atlas")
    a.write([PageWrite("sources/p.md", "Paper", "body text", "sum")], "scout")

    raw = (tmp_path / "atlas" / "sources" / "p.md").read_text()
    assert raw.startswith("---\n")
    fm = yaml.safe_load(raw.split("---", 2)[1])
    assert fm["id"] == "atlas:sources:p"
    assert fm["type"] == "source"            # inferred from the dir
    assert fm["tier"] == "scratch"           # new knowledge starts scratch
    assert fm["aliases"] == ["Paper"]        # mandatory ≥1 → defaults to title
    assert fm["created_at"] and fm["last_verified_at"]
    assert set(fm["links"]) == {"derived_from", "related_to", "contradicts", "cites"}


def test_explicit_metadata_is_honored_and_roundtrips(tmp_path):
    a = Atlas(tmp_path / "atlas")
    a.write([PageWrite(
        "concepts/rppg.md", "rPPG", "what it is", "remote ppg",
        type="method", aliases=["rPPG", "remote photoplethysmography"],
        tier="canonical", links={"cites": ["doi:10.1/x"], "junk": ["no"]},
    )], "scout")

    pg = a.get("concepts/rppg.md")
    assert pg is not None
    assert pg.meta.type == "method" and pg.meta.tier == "canonical"
    assert pg.meta.aliases == ["rPPG", "remote photoplethysmography"]
    assert pg.meta.links["cites"] == ["doi:10.1/x"]
    assert "junk" not in pg.meta.links          # only the 4 link kinds kept
    assert pg.title == "rPPG"                    # body parsed, frontmatter stripped
    assert pg.content.startswith("# rPPG")


def test_update_preserves_creation_clock(tmp_path):
    a = Atlas(tmp_path / "atlas")
    a.write([PageWrite("concepts/x.md", "X", "v1", "s")], "scout")
    created = a.get("concepts/x.md").meta.created_at
    a.write([PageWrite("concepts/x.md", "X", "v2", "s")], "scout")
    m = a.get("concepts/x.md").meta
    assert m.created_at == created               # creation clock preserved
    assert m.updated_at and m.last_verified_at   # re-verification clock moves


def test_frontmatterless_page_reads_with_defaults(tmp_path):
    a = Atlas(tmp_path / "atlas")
    p = tmp_path / "atlas" / "concepts" / "legacy.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Legacy\n\nno frontmatter here")
    pg = a.get("concepts/legacy.md")
    assert pg.title == "Legacy" and pg.meta.tier == "scratch"
    assert pg.meta.id == "atlas:concepts:legacy"  # derived when absent


def test_sanitize_passes_structured_fields(tmp_path):
    ok = sanitize_atlas_writes([{
        "path": "concepts/a.md", "title": "A", "content": "c", "summary": "s",
        "type": "concept", "tier": "active",
        "aliases": ["a1", "  ", "a2"], "links": {"related_to": ["concepts/b.md"]},
    }], tmp_path)
    assert len(ok) == 1
    w = ok[0]
    assert w.type == "concept" and w.tier == "active"
    assert w.aliases == ["a1", "a2"]             # blank cleaned out
    assert w.links == {"related_to": ["concepts/b.md"]}
    assert TYPES and TIERS  # exported for callers/tests


def test_sanitize_still_skips_malformed(tmp_path):
    assert sanitize_atlas_writes([{"path": "concepts/a.md"}], tmp_path) == []
