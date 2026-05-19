"""3f: label-propagation communities + the six-kind lint."""

from __future__ import annotations

from helix.core.atlas import Atlas, PageWrite
from helix.core.atlas_index import build
from helix.core.lint import communities, lint

_STALE = """---
id: atlas:concepts:old
type: concept
tier: scratch
aliases: [Old, ancient]
created_at: '2020-01-01T00:00:00+00:00'
updated_at: '2020-01-01T00:00:00+00:00'
claim_valid_at: '2020-01-01T00:00:00+00:00'
last_verified_at: '2020-01-01T00:00:00+00:00'
provenance: {}
links: {derived_from: [], related_to: [atlas:concepts:t1], contradicts: [], cites: []}
embeddings: {}
---

# Old

stale body
"""


def _seed(tmp_path):
    root = tmp_path / "atlas"
    a = Atlas(root)
    a.write([
        # triangle: a community of 3 concepts, none a synthesis → orphan-community
        PageWrite("concepts/t1.md", "T1", "x", "s",
                  links={"related_to": ["atlas:concepts:t2"]}),
        PageWrite("concepts/t2.md", "T2", "x", "s",
                  links={"related_to": ["atlas:concepts:t3"]}),
        PageWrite("concepts/t3.md", "T3", "x", "s",
                  links={"related_to": ["atlas:concepts:t1"]}),
        # orphan: no edges (give 2 aliases so it isn't *also* unaliased noise)
        PageWrite("concepts/lonely.md", "Lonely", "x", "s",
                  aliases=["Lonely", "solo"]),
        # contradiction edge
        PageWrite("concepts/cx.md", "CX", "x", "s",
                  links={"contradicts": ["atlas:concepts:cy"]}),
        PageWrite("concepts/cy.md", "CY", "x", "s",
                  aliases=["CY", "cee-why"]),
        # dangling internal link → missing-page
        PageWrite("concepts/dangle.md", "Dangle", "x", "s",
                  aliases=["Dangle", "dang"],
                  links={"related_to": ["atlas:concepts:ghost"]}),
    ], "seed")
    (root / "concepts" / "old.md").write_text(_STALE)
    return root


def test_label_propagation_groups_the_triangle(tmp_path):
    con = build(_seed(tmp_path))
    lab = communities(con)
    con.close()
    assert lab["atlas:concepts:t1"] == lab["atlas:concepts:t2"] == \
        lab["atlas:concepts:t3"]
    assert lab["atlas:concepts:lonely"] != lab["atlas:concepts:t1"]


def test_lint_surfaces_all_six_kinds(tmp_path):
    issues = lint(_seed(tmp_path))
    kinds = {i["kind"] for i in issues}
    assert kinds >= {"orphan", "contradiction", "stale",
                     "missing-page", "unaliased", "orphan-community"}

    assert any(i["kind"] == "missing-page" and i["id"] == "atlas:concepts:ghost"
               for i in issues)
    assert any(i["kind"] == "contradiction" and
               i["pages"] == ["atlas:concepts:cx", "atlas:concepts:cy"]
               for i in issues)
    assert any(i["kind"] == "orphan" and i["page"] == "atlas:concepts:lonely"
               for i in issues)
    stale = next(i for i in issues if i["kind"] == "stale")
    assert stale["page"] == "atlas:concepts:old" and stale["age_days"] > 365
    assert any(i["kind"] == "unaliased" and i["page"] == "atlas:concepts:t1"
               for i in issues)


def test_clean_atlas_has_no_issues(tmp_path):
    a = Atlas(tmp_path / "atlas")
    a.write([PageWrite("concepts/solo.md", "Solo", "x", "s",
                        type="finding", tier="published",
                        aliases=["Solo", "alone"])], "seed")
    # published + aliased + no dangling links + not in a cluster → clean
    assert lint(tmp_path / "atlas") == []
