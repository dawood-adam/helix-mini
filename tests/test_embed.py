"""3d: embedding cache + invalidation (model-free; fastembed is optional)."""

from __future__ import annotations

import pytest

from helix import config
from helix.core import embed
from helix.core.atlas import Atlas, PageWrite


class _Fake:
    """Deterministic, distinct-per-text embedder; records what it embedded."""

    def __init__(self):
        self.seen: list[str] = []

    def __call__(self, texts):
        self.seen.extend(texts)
        return [[float(len(t)), float(sum(map(ord, t[:30])) % 997), 1.0]
                for t in texts]


def _atlas(project):
    a = Atlas(config.atlas_path())
    a.write([PageWrite("concepts/a.md", "A", "alpha body", "s"),
             PageWrite("concepts/b.md", "B", "beta body", "s")], "seed")
    return config.atlas_path()


def test_embeds_then_cache_hits(project):
    root = _atlas(project)
    f1 = _Fake()
    vecs = embed.ensure_embeddings(root, embed_fn=f1)
    assert set(vecs) == {"atlas:concepts:a", "atlas:concepts:b"}
    assert len(f1.seen) == 2                      # both embedded first pass

    f2 = _Fake()
    again = embed.ensure_embeddings(root, embed_fn=f2)
    assert set(again) == set(vecs)
    assert f2.seen == []                          # unchanged → cache hit


def test_only_modified_page_reembedded(project):
    root = _atlas(project)
    embed.ensure_embeddings(root, embed_fn=_Fake())
    Atlas(root).write([PageWrite("concepts/a.md", "A", "ALPHA changed", "s")], "u")
    f = _Fake()
    embed.ensure_embeddings(root, embed_fn=f)
    assert len(f.seen) == 1 and "ALPHA changed" in f.seen[0]


def test_deleted_page_pruned(project):
    root = _atlas(project)
    embed.ensure_embeddings(root, embed_fn=_Fake())
    (root / "concepts" / "b.md").unlink()
    out = embed.ensure_embeddings(root, embed_fn=_Fake())
    assert set(out) == {"atlas:concepts:a"}


def test_cosine_and_query():
    assert embed.cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert embed.cosine([1, 0], [0, 1]) == 0.0
    assert embed.cosine([], [1]) == 0.0
    assert embed.embed_query("hi", embed_fn=_Fake()) == [2.0, float(
        sum(map(ord, "hi")) % 997), 1.0]


def test_unavailable_without_fastembed():
    if embed.available():
        pytest.skip("fastembed installed; the EmbedUnavailable path is moot")
    with pytest.raises(embed.EmbedUnavailable):
        embed.embed_query("x")
