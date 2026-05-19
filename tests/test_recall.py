"""3e: auto-routing recall — router + 4 modes, refs-only, get fetches body."""

from __future__ import annotations

from helix import config
from helix.core.atlas import Atlas, PageWrite
from helix.core.recall import get, recall


def _atlas(project):
    a = Atlas(config.atlas_path())
    a.write([
        PageWrite("concepts/rppg.md", "rPPG",
                  "remote photoplethysmography measuring pulse from a camera",
                  "camera pulse", aliases=["rPPG", "remote photoplethysmography"],
                  links={"related_to": ["atlas:concepts:bp"]}),
        PageWrite("concepts/bp.md", "BP estimation",
                  "blood pressure estimation from physiological signals", "bp"),
        PageWrite("sources/chen.md", "Chen 2025",
                  "chen study on rppg noise floor", "chen", type="source"),
    ], "seed")
    return config.atlas_path()


def _fake_embed(texts):
    out = []
    for t in texts:
        tl = t.lower()
        out.append([
            float(tl.count("photoplethysmography") + tl.count("camera")
                  + tl.count("pulse")),
            float(tl.count("blood") + tl.count("pressure")),
            float(tl.count("chen") + tl.count("noise")),
        ])
    return out


def test_lexical_refs_only(project):
    root = _atlas(project)
    refs = recall(root, "photoplethysmography", mode="lexical")
    assert refs and refs[0]["id"] == "atlas:concepts:rppg"
    r = refs[0]
    assert r["mode"] == "lexical" and r["score"] > 0
    assert set(r) == {"id", "title", "tier", "summary", "mode", "score"}
    assert "remote photoplethysmography" in r["summary"]  # refs carry a snippet


def test_router_picks_modes(project):
    root = _atlas(project)
    assert recall(root, "rppg")[0]["mode"] == "lexical"          # short term
    g = recall(root, "how does rppg relate to bp")
    assert g[0]["mode"] == "graph"
    # graph mode seeds from the best lexical hit and walks the link, so the
    # rppg↔bp edge surfaces regardless of which end is the seed.
    assert {x["id"] for x in g} & {"atlas:concepts:rppg", "atlas:concepts:bp"}
    c = recall(root, "everything about rppg")
    assert c[0]["mode"] == "community"
    by_id = recall(root, "atlas:concepts:rppg")                   # id → graph
    assert by_id[0]["mode"] == "graph"
    assert any(x["id"] == "atlas:concepts:bp" for x in by_id)


def test_semantic_with_injected_embedder(project):
    root = _atlas(project)
    refs = recall(root, "video camera pulse signal sensing approach",
                  mode="semantic", embed_fn=_fake_embed)
    assert refs[0]["id"] == "atlas:concepts:rppg"
    assert refs[0]["mode"] == "semantic"


def test_semantic_falls_back_to_lexical_when_unavailable(project):
    root = _atlas(project)
    # No embed_fn + fastembed absent → graceful fallback, never crashes.
    refs = recall(root, "remote photoplethysmography camera pulse method",
                  mode="semantic")
    assert refs and refs[0]["mode"] == "lexical"


def test_get_fetches_body_by_id_and_path(project):
    root = _atlas(project)
    p = get(root, "atlas:concepts:rppg")
    assert p and p["title"] == "rPPG" and "photoplethysmography" in p["body"]
    assert get(root, "concepts/bp.md")["id"] == "atlas:concepts:bp"
    assert get(root, "atlas:nope:nope") is None
