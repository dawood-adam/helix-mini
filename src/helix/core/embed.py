"""Page embeddings + body-hash cache (HELIX-v3 §3.3 / semantic recall).

The ONE surviving model dependency. MCP sampling is chat-only (no embeddings
endpoint — verified against the SDK), so semantic recall needs a *local*
model. ``fastembed`` is optional (``pip install 'helix[embed]'``); without
it semantic mode is simply unavailable and 3e falls back to lexical/graph.

The cache + invalidation is model-free and fully tested (inject ``embed_fn``);
the fastembed call is an isolated adapter. Vectors persist in
``.helix/embeddings.json`` keyed by page id, invalidated by the sha256 of
the page body (the ``embeddings.hash`` field 3a reserved). Rebuilding the
SQLite graph is cheap so it is derived; embeddings are expensive so they are
cached.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .. import config
from .atlas import iter_pages

_MODEL = "BAAI/bge-small-en-v1.5"


class EmbedUnavailable(RuntimeError):
    """Raised when a real embedding is needed but fastembed is absent."""


def available() -> bool:
    try:
        import fastembed  # noqa: F401
        return True
    except Exception:
        return False


_FE = None


def _fastembed_embed(texts: list[str]) -> list[list[float]]:
    global _FE
    try:
        from fastembed import TextEmbedding
    except Exception as e:  # pragma: no cover - exercised only without the extra
        raise EmbedUnavailable(
            "fastembed not installed — `pip install 'helix[embed]'` for "
            "semantic recall (sampling can't embed)."
        ) from e
    if _FE is None:
        _FE = TextEmbedding(model_name=_MODEL)
    return [list(map(float, v)) for v in _FE.embed(list(texts))]


def _store_path() -> Path:
    return config.helix_dir() / "embeddings.json"


def _load_store() -> dict:
    p = _store_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            pass
    return {"model": _MODEL, "pages": {}}


def _body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()


def _iter_bodies(root: Path):
    for r in iter_pages(root):
        yield r.id, r.body


def ensure_embeddings(root: Path, embed_fn=None) -> dict[str, list[float]]:
    """Embed pages whose body changed/is missing; prune deleted pages;
    persist; return ``{page_id: vector}``."""
    embed_fn = embed_fn or _fastembed_embed
    store = _load_store()
    pages: dict = store.setdefault("pages", {})
    todo_ids: list[str] = []
    todo_texts: list[str] = []
    current: dict[str, str] = {}
    for pid, body in _iter_bodies(root):
        h = _body_hash(body)
        current[pid] = h
        rec = pages.get(pid)
        if not rec or rec.get("hash") != h:
            todo_ids.append(pid)
            todo_texts.append(body[:8000])
    if todo_texts:
        vecs = embed_fn(todo_texts)
        for pid, vec in zip(todo_ids, vecs):
            pages[pid] = {"hash": current[pid], "vector": list(vec)}
    for gone in [pid for pid in pages if pid not in current]:
        del pages[gone]
    _store_path().write_text(json.dumps(store))
    return {pid: rec["vector"] for pid, rec in pages.items()}


def embed_query(text: str, embed_fn=None) -> list[float]:
    embed_fn = embed_fn or _fastembed_embed
    return list(embed_fn([text])[0])


def cosine(a, b) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
