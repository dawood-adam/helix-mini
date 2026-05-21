"""Atlas hygiene — communities + lint.

Communities = label propagation over the SQLite link graph (dep-light, not
Leiden — milliseconds for <1000 pages). Lint surfaces six rot patterns with
suggested fixes; each check is deliberately cheap/exact rather than
NLP-fuzzy, so the output is trustworthy.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .atlas_index import _iter_pages, build

STALE_DAYS = 30

# Core threads every project that's past the Scout stage should carry.
# Older projects (no threads/ folder yet) are exempt — we only nag when a
# project has opted into the thread model by having at least one thread.
_CORE_THREADS = ("data", "glossary")

# Boldface ``**term**`` is the agent's signal for "this is a defined
# term"; we use it to drive the vocabulary-drift heuristic. Trivial regex,
# no NLP: false positives are cheap (the lint is advisory).
_BOLD_TERM = re.compile(r"\*\*([A-Za-z][\w\s\-]{1,40})\*\*")


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

    # 6b orphan-by-policy (Workstream G) — a non-source page that's been
    # touched by the new write protocol (has a history entry) but doesn't
    # cite any spec line. Sources and archived pages are exempt. Pages
    # with no history are legacy / pre-protocol and don't trigger this —
    # we don't nag on material the agent never claimed to ground in spec.
    for pid, (_rel, title, meta) in by_id.items():
        if meta.type == "source" or meta.tier == "archived":
            continue
        if meta.spec_refs or not meta.history:
            continue
        issues.append({"kind": "orphan-by-policy", "page": pid, "title": title,
                       "suggestion": (
                           "declare which spec line this write supports / "
                           "contradicts / extends (set spec_refs)")})

    # 7 stale-report (Workstream D) — a report file under projects/<id>/reports/
    # that doesn't match the canonical <stage>.html naming, or for a stage
    # not in the known set. The agent (or a re-render) will replace stale
    # ones; the lint nudge keeps the directory tidy.
    from .agents import stage_order
    known_stages = set(stage_order()) | {"scout_critic"}  # F.6 alias
    for proj_dir in (root / "projects").glob("*"):
        if not proj_dir.is_dir():
            continue
        rep_dir = proj_dir / "reports"
        if not rep_dir.is_dir():
            continue
        for f in rep_dir.glob("*.html"):
            stage = f.stem
            if stage not in known_stages:
                issues.append({
                    "kind": "stale-report", "project": proj_dir.name,
                    "file": str(f.relative_to(root)), "stage": stage,
                    "suggestion": (
                        "non-canonical report name — delete or rename to "
                        f"<known-stage>.html (one of {sorted(known_stages)})"
                    ),
                })

    # 8 orphan-thread (Workstream E) — a project that has opted into the
    # thread model (any thread file present, or spec/plan written) but is
    # missing one of the core threads (data / glossary). Pre-thread
    # projects are silent.
    # Defensive: ``list_threads`` validates the project name and raises
    # SandboxError on an unsafe one (e.g. a stray ``.hidden`` dir under
    # ``projects/``); skip those rather than crash lint.
    from ..sandbox import SandboxError
    from .threads import (
        load_thread, parse_glossary_terms, list_threads,
    )
    for proj_dir in (root / "projects").glob("*"):
        if not proj_dir.is_dir():
            continue
        try:
            present = list_threads(root, proj_dir.name)
        except SandboxError:
            continue
        has_spec_or_plan = (proj_dir / "spec.md").exists() or \
                           (proj_dir / "plan.md").exists()
        if not present and not has_spec_or_plan:
            continue
        present_names = {t.name for t in present}
        for core in _CORE_THREADS:
            if core not in present_names:
                issues.append({
                    "kind": "orphan-thread", "project": proj_dir.name,
                    "thread": core,
                    "suggestion": (
                        f"open the '{core}' thread at projects/"
                        f"{proj_dir.name}/threads/{core}.md")
                })

    # 9 dataset-without-license / dataset-without-source (Workstream E) —
    # every entities/datasets/*.md page must declare license + source in
    # frontmatter so reproducibility and reuse are auditable.
    ds_dir = root / "entities" / "datasets"
    if ds_dir.is_dir():
        for fp in ds_dir.glob("*.md"):
            fm, _ = _read_frontmatter(fp)
            if not isinstance(fm, dict):
                fm = {}
            rel = str(fp.relative_to(root))
            if not str(fm.get("license", "")).strip():
                issues.append({
                    "kind": "dataset-without-license", "file": rel,
                    "suggestion": (
                        "add a `license:` field in the page frontmatter "
                        "(SPDX id or 'unknown — investigate')"),
                })
            if not str(fm.get("source", "")).strip():
                issues.append({
                    "kind": "dataset-without-source", "file": rel,
                    "suggestion": (
                        "add a `source:` field (URL / DOI / institution) "
                        "in the page frontmatter"),
                })

    # 10 vocabulary-drift (Workstream F.4) — bold terms used in a
    # project's spec/plan that aren't defined in its glossary. Cheap and
    # exact: only ``**term**`` boldface is flagged, so prose isn't noisy.
    # No glossary => no drift (the glossary thread is opt-in).
    for proj_dir in (root / "projects").glob("*"):
        if not proj_dir.is_dir():
            continue
        try:
            gloss = load_thread(root, proj_dir.name, "glossary")
        except SandboxError:
            continue
        if gloss is None:
            continue
        defined = set(parse_glossary_terms(gloss).keys())
        for which in ("spec.md", "plan.md"):
            fp = proj_dir / which
            if not fp.exists():
                continue
            text = fp.read_text(errors="replace")
            terms = {m.group(1).strip().lower() for m in _BOLD_TERM.finditer(text)}
            drift = sorted(t for t in terms if t and t not in defined)
            for t in drift:
                issues.append({
                    "kind": "vocabulary-drift", "project": proj_dir.name,
                    "file": str(fp.relative_to(root)), "term": t,
                    "suggestion": (
                        f"define '{t}' in projects/{proj_dir.name}/threads/"
                        "glossary.md (or rename to an existing term)"),
                })

    # 11 discovery-log (Workstream H) — a hypothesis on the project's
    # hypothesis thread marked ``Supported`` must cite at least one
    # support reference (Atlas page id). A bare 'Supported' status with
    # no support list is a discovery without evidence — flag it.
    from .hypothesis import parse_hypotheses
    for proj_dir in (root / "projects").glob("*"):
        if not proj_dir.is_dir():
            continue
        try:
            hyp_thread = load_thread(root, proj_dir.name, "hypothesis")
        except SandboxError:
            continue
        if hyp_thread is None:
            continue
        for h in parse_hypotheses(hyp_thread.body):
            if h.status == "Supported" and not h.support:
                issues.append({
                    "kind": "discovery-log", "project": proj_dir.name,
                    "hypothesis": h.id,
                    "suggestion": (
                        f"'{h.id}' is marked Supported but lists no "
                        "support — cite the validator pass / atlas pages "
                        "in the hypothesis thread's `support:` field")
                })

    return issues


def _read_frontmatter(fp: Path) -> tuple[dict, str]:
    text = fp.read_text(errors="replace")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                fm = {}
            return (fm if isinstance(fm, dict) else {}), parts[2].lstrip("\n")
    return {}, text
