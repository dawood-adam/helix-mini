"""Atlas hygiene (HELIX-v3 §3.4 communities, §7.7 lint).

Communities = label propagation over the 3c SQLite graph (dep-light, not
Leiden — milliseconds for <1000 pages per v3 §11.1). Lint surfaces six rot
patterns with suggested fixes; each check is deliberately cheap/exact rather
than NLP-fuzzy, so the output is trustworthy.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .atlas_index import _iter_pages, build

STALE_DAYS = 30


def communities(con: sqlite3.Connection) -> dict[str, str]:
    """label propagation → {page_id: community_label}. Only real pages
    (no-page link targets are handled by the missing-page lint)."""
    nodes = [r[0] for r in con.execute("SELECT id FROM nodes")]
    nodeset = set(nodes)
    adj: dict[str, set] = {n: set() for n in nodes}
    for s, d in con.execute("SELECT src, dst FROM edges"):
        if s in nodeset and d in nodeset:
            adj[s].add(d)
            adj[d].add(s)
    label = {n: n for n in nodes}
    for _ in range(20):
        changed = False
        for n in sorted(nodes):
            neigh = [label[m] for m in adj[n]]
            if not neigh:
                continue
            counts = Counter(neigh)
            top = min(l for l, c in counts.items() if c == max(counts.values()))
            if label[n] != top:
                label[n] = top
                changed = True
        if not changed:
            break
    return label


def _age_days(iso: str) -> float | None:
    try:
        dt = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400


def lint(root: Path) -> list[dict]:
    pages = list(_iter_pages(root))  # (id, rel, title, meta)
    by_id = {pid: (rel, title, meta) for pid, rel, title, meta in pages}
    con = build(root)
    try:
        deg: Counter = Counter()
        contradicts: set[tuple] = set()
        targets: Counter = Counter()
        for s, d, kind in con.execute("SELECT src, dst, kind FROM edges"):
            deg[s] += 1
            deg[d] += 1
            if kind == "contradicts":
                contradicts.add(tuple(sorted((s, d))))
            if d not in by_id:
                targets[d] += 1
        comm = communities(con)
    finally:
        con.close()

    issues: list[dict] = []

    # 1 orphan — zero edges, not already retired
    for pid, (_rel, title, meta) in by_id.items():
        if deg[pid] == 0 and meta.tier not in ("published", "archived"):
            issues.append({"kind": "orphan", "page": pid, "title": title,
                            "suggestion": "link it to related pages or archive"})

    # 2 contradiction — an explicit `contradicts` edge
    for a, b in sorted(contradicts):
        issues.append({"kind": "contradiction", "pages": [a, b],
                        "suggestion": "reconcile or write a comparison page"})

    # 3 stale — bi-temporal: overdue for re-verification
    src_dates = sorted(
        m.created_at for _, _, _, m in pages
        if m.type == "source" and m.created_at)
    for pid, (_rel, title, meta) in by_id.items():
        age = _age_days(meta.last_verified_at)
        if age is None or age <= STALE_DAYS:
            continue
        newer = sum(1 for sd in src_dates if sd > (meta.last_verified_at or ""))
        issues.append({"kind": "stale", "page": pid, "title": title,
                        "age_days": round(age), "newer_sources": newer,
                        "suggestion": "re-verify against current sources"})

    # 4 missing-page — internal links pointing nowhere
    for tgt, n in sorted(targets.items()):
        if str(tgt).startswith("atlas:"):
            issues.append({"kind": "missing-page", "id": tgt, "referenced_by": n,
                            "suggestion": "draft this page or fix the links"})

    # 5 unaliased — only the auto-default alias (== [title])
    for pid, (_rel, title, meta) in by_id.items():
        if meta.aliases == [title]:
            issues.append({"kind": "unaliased", "page": pid, "title": title,
                            "suggestion": "add ≥1 real alias for dedup"})

    # 6 orphan-community — a cluster with no synthesis page
    clusters: dict[str, list[str]] = {}
    for pid, lbl in comm.items():
        clusters.setdefault(lbl, []).append(pid)
    for lbl, members in clusters.items():
        if len(members) >= 3 and not any(
            by_id[m][2].type in ("comparison", "finding") for m in members
        ):
            issues.append({"kind": "orphan-community", "pages": sorted(members),
                            "suggestion": "draft a synthesis/comparison page"})

    return issues
