"""SQLite edge index over the Atlas link graph.

Source of truth is the markdown frontmatter ``links:``. This is a
*rebuildable* in-memory index for fast k-hop traversal — rebuilt per query,
which is trivial at the hundreds-of-pages scale. Persisting it is
a later optimization; keeping it derived means ``Atlas.write`` stays
decoupled (no index in the write hot path).

3e (graph-mode recall) and 3f (communities) build on ``build()``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Re-exported for back-compat (embed/recall import _PAGE_DIRS from here).
from .atlas import _PAGE_DIRS, iter_pages  # noqa: F401


def _iter_pages(root: Path):
    """(id, path, title, meta) view over the canonical page scan."""
    for r in iter_pages(root):
        yield r.id, r.path, r.title, r.meta


def build(root: Path) -> sqlite3.Connection:
    """An in-memory SQLite graph of the Atlas: nodes + typed edges."""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE nodes(id TEXT PRIMARY KEY, path TEXT, "
                "title TEXT, tier TEXT)")
    con.execute("CREATE TABLE edges(src TEXT, dst TEXT, kind TEXT)")
    for pid, rel, title, meta in _iter_pages(root):
        con.execute("INSERT OR REPLACE INTO nodes VALUES(?,?,?,?)",
                    (pid, rel, title, meta.tier))
        for kind, targets in (meta.links or {}).items():
            for dst in targets or []:
                con.execute("INSERT INTO edges VALUES(?,?,?)",
                            (pid, str(dst), kind))
    con.commit()
    return con


def neighbors(root: Path, start: str, k: int = 1) -> list[dict]:
    """k-hop neighbours of a page (id or path), undirected over all link
    kinds. Returns refs (id/title/tier/hops), never bodies."""
    con = build(root)
    try:
        row = con.execute("SELECT id FROM nodes WHERE id=? OR path=?",
                           (start, start)).fetchone()
        start_id = row[0] if row else start
        seen = {start_id: 0}
        frontier = [start_id]
        for dist in range(1, max(1, k) + 1):
            nxt = []
            for n in frontier:
                rows = con.execute(
                    "SELECT dst FROM edges WHERE src=? "
                    "UNION SELECT src FROM edges WHERE dst=?", (n, n)).fetchall()
                for (adj,) in rows:
                    if adj not in seen:
                        seen[adj] = dist
                        nxt.append(adj)
            frontier = nxt
            if not frontier:
                break
        out = []
        for nid, dist in sorted(seen.items(), key=lambda x: (x[1], x[0])):
            if nid == start_id:
                continue
            r = con.execute("SELECT title,tier FROM nodes WHERE id=?",
                            (nid,)).fetchone()
            out.append({"id": nid, "title": r[0] if r else "(no page)",
                        "tier": r[1] if r else "-", "hops": dist})
        return out
    finally:
        con.close()
