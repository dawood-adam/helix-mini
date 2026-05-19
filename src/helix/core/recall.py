"""Auto-routing recall (HELIX-v3 §3.5) — the right retrieval per question.

One entry point, ``recall(root, query, mode="auto")``. A query-shape router
picks lexical (BM25) / semantic (embeddings) / graph (k-hop) / community
(cluster of the best hit). Every mode returns **refs only** — id, title,
tier, ~120-char summary, score — never bodies. Bodies come from ``get`` and
are capped. The find/fetch split protects the model's context budget.

Falls back to lexical whenever a richer mode can't run (no embeddings, no
resolvable graph node), so recall never hard-fails.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from . import embed
from .atlas import iter_pages
from .atlas_index import neighbors

_BODY_CAP = 24_000
_TOK = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return [t for t in _TOK.findall(text.lower()) if len(t) > 1]


def _iter_pages(root: Path):
    for r in iter_pages(root):
        yield {
            "id": r.id, "path": r.path, "title": r.title,
            "tier": r.meta.tier, "aliases": r.meta.aliases, "body": r.body,
        }


def _summary(body: str) -> str:
    text = "\n".join(
        ln for ln in body.splitlines() if not ln.startswith("# ")).strip()
    text = " ".join(text.split())
    return text[:120] + ("…" if len(text) > 120 else "")


def _ref(p: dict, score: float, mode: str) -> dict:
    return {"id": p["id"], "title": p["title"], "tier": p["tier"],
            "summary": _summary(p["body"]), "score": round(float(score), 4),
            "mode": mode}


# --- modes ------------------------------------------------------------------


def _bm25(pages: list[dict], query: str, k: int) -> list[dict]:
    q = _tokens(query)
    if not q or not pages:
        return []
    docs = [_tokens(p["title"] + " " + " ".join(p["aliases"]) + " " + p["body"])
            for p in pages]
    n = len(docs)
    avgdl = sum(len(d) for d in docs) / n
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    k1, b = 1.5, 0.75
    scored = []
    for p, d in zip(pages, docs):
        dl = len(d) or 1
        s = 0.0
        for t in q:
            if t not in df:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            tf = d.count(t)
            s += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
        if s > 0:
            scored.append((s, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [_ref(p, s, "lexical") for s, p in scored[:k]]


def _semantic(root: Path, pages: list[dict], query: str, k: int,
              embed_fn=None) -> list[dict] | None:
    if embed_fn is None and not embed.available():
        return None
    try:
        vecs = embed.ensure_embeddings(root, embed_fn=embed_fn)
        qv = embed.embed_query(query, embed_fn=embed_fn)
    except embed.EmbedUnavailable:
        return None
    by_id = {p["id"]: p for p in pages}
    scored = [(embed.cosine(qv, v), by_id[i]) for i, v in vecs.items()
              if i in by_id]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [_ref(p, s, "semantic") for s, p in scored[:k] if s > 0]


def _graph(root: Path, pages: list[dict], query: str, k: int,
           hops: int, mode: str) -> list[dict]:
    by_id = {p["id"]: p for p in pages}
    start = query.strip()
    if start not in by_id and not any(p["path"] == start for p in pages):
        seed = _bm25(pages, query, 1)
        if not seed:
            return []
        start = seed[0]["id"]
    out = []
    for n in neighbors(root, start, hops)[:k]:
        p = by_id.get(n["id"])
        out.append(_ref(p, 1.0 / n["hops"], mode) if p else {
            "id": n["id"], "title": n["title"], "tier": n["tier"],
            "summary": "(no page)", "score": round(1.0 / n["hops"], 4),
            "mode": mode})
    return out


# --- router -----------------------------------------------------------------

_REL = re.compile(r"\b(relate|related|relationship|connect|link|vs|versus)\b")
_GLOBAL = re.compile(r"\b(everything|overview|summari|all about|landscape)\b")


def _route(query: str, pages: list[dict]) -> str:
    q = query.strip().lower()
    if query.strip().startswith("atlas:") or query.strip() in {
            p["path"] for p in pages}:
        return "graph"
    if _GLOBAL.search(q):
        return "community"
    if _REL.search(q) and " and " in q or "how does" in q:
        return "graph"
    if len(_tokens(q)) >= 5:
        return "semantic"
    return "lexical"


def recall(root: Path, query: str, k: int = 8, mode: str = "auto",
           embed_fn=None) -> list[dict]:
    pages = list(_iter_pages(root))
    chosen = _route(query, pages) if mode == "auto" else mode
    if chosen == "semantic":
        sem = _semantic(root, pages, query, k, embed_fn)
        if sem is not None:
            return sem
        chosen = "lexical"          # graceful fallback
    if chosen == "graph":
        res = _graph(root, pages, query, k, 1, "graph")
        return res or _bm25(pages, query, k)
    if chosen == "community":
        res = _graph(root, pages, query, k, 2, "community")
        return res or _bm25(pages, query, k)
    return _bm25(pages, query, k)


def get(root: Path, id_or_path: str) -> dict | None:
    """Fetch one page's capped body + key frontmatter (the fetch half)."""
    for p in _iter_pages(root):
        if p["id"] == id_or_path or p["path"] == id_or_path:
            return {"id": p["id"], "title": p["title"], "tier": p["tier"],
                    "path": p["path"], "body": p["body"][:_BODY_CAP]}
    return None
