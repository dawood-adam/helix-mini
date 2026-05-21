"""Atlas store — a markdown wiki with YAML-frontmatter pages.

Store only: imports nothing from ``sandbox`` (which imports ``PageWrite``
from here) so there is no cycle.

Every page carries typed frontmatter: id / type / tier /
aliases (≥1, mandatory) / created+updated / the bi-temporal pair
(claim_valid_at, last_verified_at) / provenance / links / embeddings. Writes
stay backward-tolerant — an agent may emit just {path,title,content,summary}
and the store fills sensible defaults, so the schema can't break a run.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

TYPES = ("concept", "entity", "source", "method", "finding", "comparison")
TIERS = ("scratch", "active", "canonical", "published", "archived")
_DIR_TYPE = {"sources": "source", "concepts": "concept", "entities": "entity"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _page_id(path: str) -> str:
    stem = path.rsplit(".", 1)[0] if "." in Path(path).name else path
    return "atlas:" + stem.strip("/").replace("/", ":")


def _empty_links() -> dict:
    return {"derived_from": [], "related_to": [], "contradicts": [], "cites": []}


@dataclass
class PageMeta:
    id: str = ""
    type: str = "concept"
    tier: str = "scratch"
    aliases: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    claim_valid_at: str = ""
    last_verified_at: str = ""
    provenance: dict = field(default_factory=dict)
    links: dict = field(default_factory=_empty_links)
    embeddings: dict = field(default_factory=dict)
    # Workstream G — write-protocol fields persisted in frontmatter so the
    # spec cross-reference survives a page round-trip (and the
    # orphan-by-policy lint can see them).
    spec_refs: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> PageMeta:
        d = d if isinstance(d, dict) else {}
        links = _empty_links()
        if isinstance(d.get("links"), dict):
            for k, v in d["links"].items():
                links[k] = list(v) if isinstance(v, list) else links.get(k, [])
        al = d.get("aliases")
        refs = d.get("spec_refs")
        hist = d.get("history")
        return cls(
            id=str(d.get("id", "")),
            type=d["type"] if d.get("type") in TYPES else "concept",
            tier=d["tier"] if d.get("tier") in TIERS else "scratch",
            aliases=[str(a) for a in al] if isinstance(al, list) and al else [],
            created_at=str(d.get("created_at", "")),
            updated_at=str(d.get("updated_at", "")),
            claim_valid_at=str(d.get("claim_valid_at", "")),
            last_verified_at=str(d.get("last_verified_at", "")),
            provenance=d.get("provenance") if isinstance(d.get("provenance"), dict) else {},
            links=links,
            embeddings=d.get("embeddings") if isinstance(d.get("embeddings"), dict) else {},
            spec_refs=[str(r) for r in refs] if isinstance(refs, list) else [],
            history=[h for h in hist if isinstance(h, dict)] if isinstance(hist, list) else [],
        )


@dataclass
class Page:
    path: str
    title: str
    content: str  # body only (frontmatter stripped)
    meta: PageMeta = field(default_factory=PageMeta)


@dataclass
class PageWrite:
    path: str
    title: str
    content: str
    summary: str
    # Optional structured metadata (defaults applied if omitted).
    type: str | None = None
    aliases: list[str] | None = None
    tier: str | None = None
    links: dict | None = None
    # Workstream G — write protocol fields. ``action`` is the closed-set
    # vocabulary (ADD/UPDATE/SUPERSEDE/LINK/NOOP); ``because`` is a
    # one-line rationale; ``provenance`` carries the stage/run/snap
    # context the sanitizer enforces; ``spec_refs`` records which spec
    # line(s) this write supports/contradicts/extends.
    action: str | None = None
    because: str | None = None
    provenance: dict | None = None
    spec_refs: list[str] | None = None


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            return (meta if isinstance(meta, dict) else {}), parts[2].lstrip("\n")
    return {}, text


# Directories that hold pages. Single source of truth — atlas_index, embed,
# recall and lint all iterate via ``iter_pages`` below.
_PAGE_DIRS = ("sources", "concepts", "entities", "projects")


@dataclass
class PageRecord:
    """One parsed page: everything any consumer needs, scanned once."""

    id: str
    path: str
    title: str
    meta: PageMeta
    body: str


def iter_pages(root: Path):
    """Yield a :class:`PageRecord` per page under ``root`` (sorted, stable).

    The one canonical page scan. Consumers (the SQLite graph, embeddings,
    recall, lint) adapt this rather than re-walking the tree."""
    for d in _PAGE_DIRS:
        base = Path(root) / d
        if not base.is_dir():
            continue
        for fp in sorted(base.rglob("*.md")):
            meta_dict, body = _split_frontmatter(fp.read_text(errors="replace"))
            meta = PageMeta.from_dict(meta_dict)
            rel = str(fp.relative_to(root))
            meta.id = meta.id or _page_id(rel)
            title = next((ln[2:].strip() for ln in body.splitlines()
                          if ln.startswith("# ")), "Untitled")
            yield PageRecord(id=meta.id, path=rel, title=title,
                             meta=meta, body=body)


class Atlas:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.Lock()
        self._ensure_structure()

    def _ensure_structure(self) -> None:
        for d in ("sources", "concepts", "entities", "projects"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        if not (self.root / "index.md").exists():
            (self.root / "index.md").write_text("# Atlas Index\n")
        if not (self.root / "log.md").exists():
            (self.root / "log.md").write_text("# Atlas Log\n")
        if not (self.root / "ATLAS.md").exists():
            (self.root / "ATLAS.md").write_text(_ATLAS_DOC)

    def read(self, query: str, limit: int = 20) -> list[Page]:
        index_text = (self.root / "index.md").read_text()
        keywords = query.lower().split()
        matches: list[Page] = []
        for line in index_text.splitlines():
            if not line.startswith("- ["):
                continue
            if any(kw in line.lower() for kw in keywords):
                path = self._parse_index_path(line)
                if not path:
                    continue
                try:
                    resolved = self._safe_resolve(path)
                except ValueError:
                    continue
                if resolved.exists():
                    matches.append(self._load(path, resolved.read_text()))
                    if len(matches) >= limit:
                        break
        return matches

    def get(self, path: str) -> Page | None:
        try:
            resolved = self._safe_resolve(path)
        except ValueError:
            return None
        if not resolved.exists():
            return None
        return self._load(path, resolved.read_text())

    def _load(self, path: str, raw: str) -> Page:
        meta_dict, body = _split_frontmatter(raw)
        meta = PageMeta.from_dict(meta_dict)
        if not meta.id:
            meta.id = _page_id(path)
        return Page(path=path, title=self._extract_title(body), content=body, meta=meta)

    def retier(self, relpath: str, tier: str) -> bool:
        """Surgically change a page's tier, preserving its body exactly."""
        if tier not in TIERS:
            return False
        try:
            fp = self._safe_resolve(relpath)
        except ValueError:
            return False
        if not fp.exists():
            return False
        meta_dict, body = _split_frontmatter(fp.read_text())
        meta = PageMeta.from_dict(meta_dict)
        meta.id = meta.id or _page_id(relpath)
        meta.tier = tier
        meta.updated_at = _now()
        fm = yaml.safe_dump(_meta_dict(meta), sort_keys=False).strip()
        fp.write_text(f"---\n{fm}\n---\n\n{body}")
        return True

    def read_all_summaries(self) -> str:
        return (self.root / "index.md").read_text()

    def _safe_resolve(self, relative: str) -> Path:
        resolved = (self.root / relative).resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise ValueError(f"Path traversal blocked: {relative}")
        return resolved

    def write(self, writes: list[PageWrite], log_entry: str) -> None:
        with self._lock:
            for w in writes:
                path = self._safe_resolve(w.path)
                path.parent.mkdir(parents=True, exist_ok=True)
                prior, _ = _split_frontmatter(
                    path.read_text()) if path.exists() else ({}, "")
                meta = self._meta_for(w, prior)
                fm = yaml.safe_dump(_meta_dict(meta), sort_keys=False).strip()
                path.write_text(f"---\n{fm}\n---\n\n# {w.title}\n\n{w.content}")
            self._update_index(writes)
            self._append_log(log_entry)

    def _meta_for(self, w: PageWrite, prior: dict) -> PageMeta:
        now = _now()
        aliases = [str(a).strip() for a in (w.aliases or []) if str(a).strip()]
        if not aliases:  # mandatory ≥1
            aliases = [w.title]
        links = _empty_links()
        if isinstance(w.links, dict):
            for k, v in w.links.items():
                if k in links and isinstance(v, list):
                    links[k] = [str(x) for x in v]
        # Workstream G — merge the write's provenance (stage / run_id /
        # snapshot_id / sources / confidence) into the page's, preserving
        # any prior keys we don't overwrite. Then append the action /
        # because / spec_refs to a short history list so we keep a
        # per-page audit trail without bloating the frontmatter.
        prior_prov = prior.get("provenance") if isinstance(
            prior.get("provenance"), dict) else {}
        prov = dict(prior_prov)
        if isinstance(w.provenance, dict):
            prov.update(w.provenance)
        prior_refs = prior.get("spec_refs") if isinstance(
            prior.get("spec_refs"), list) else []
        merged_refs = list(dict.fromkeys(
            [str(r) for r in prior_refs] + [str(r) for r in (w.spec_refs or [])]))
        prior_hist = prior.get("history") if isinstance(
            prior.get("history"), list) else []
        history = [h for h in prior_hist if isinstance(h, dict)]
        entry = {"at": now}
        if w.action:
            entry["action"] = w.action
        if w.because:
            entry["because"] = w.because
        if w.spec_refs:
            entry["spec_refs"] = [str(r) for r in w.spec_refs]
        run_id = prov.get("run_id") if isinstance(prov, dict) else None
        if run_id:
            entry["run_id"] = run_id
        if len(entry) > 1:  # don't append a timestamp-only no-op
            history.append(entry)
            history = history[-20:]  # cap so a chatty stage can't bloat frontmatter
        return PageMeta(
            id=_page_id(w.path),
            type=w.type if w.type in TYPES else _DIR_TYPE.get(
                Path(w.path).parts[0] if Path(w.path).parts else "", "concept"),
            tier=w.tier if w.tier in TIERS else str(prior.get("tier") or "scratch"),
            aliases=list(dict.fromkeys(aliases)),
            created_at=str(prior.get("created_at") or now),
            updated_at=now,
            claim_valid_at=str(prior.get("claim_valid_at") or now),
            last_verified_at=now,
            provenance=prov,
            links=links,
            embeddings=prior.get("embeddings") if isinstance(
                prior.get("embeddings"), dict) else {},
            spec_refs=merged_refs,
            history=history,
        )

    def _update_index(self, writes: list[PageWrite]) -> None:
        index_path = self.root / "index.md"
        lines = index_path.read_text().splitlines()
        existing: dict[str, int] = {}
        for i, line in enumerate(lines):
            p = self._parse_index_path(line)
            if p:
                existing[p] = i
        for w in writes:
            entry = f"- [{w.title}]({w.path}) — {w.summary}"
            if w.path in existing:
                lines[existing[w.path]] = entry
            else:
                lines.append(entry)
        index_path.write_text("\n".join(lines) + "\n")

    def _append_log(self, entry: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        with open(self.root / "log.md", "a") as f:
            f.write(f"\n## [{ts}] {entry}\n")

    @staticmethod
    def _parse_index_path(line: str) -> str | None:
        start = line.find("](")
        end = line.find(")", start + 2) if start != -1 else -1
        if start != -1 and end != -1:
            return line[start + 2 : end]
        return None

    @staticmethod
    def _extract_title(content: str) -> str:
        for line in content.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return "Untitled"


def _meta_dict(m: PageMeta) -> dict:
    return {
        "id": m.id, "type": m.type, "tier": m.tier, "aliases": m.aliases,
        "created_at": m.created_at, "updated_at": m.updated_at,
        "claim_valid_at": m.claim_valid_at, "last_verified_at": m.last_verified_at,
        "provenance": m.provenance, "links": m.links, "embeddings": m.embeddings,
        "spec_refs": m.spec_refs, "history": m.history,
    }


_ATLAS_DOC = """# Atlas schema

The Atlas is the LLM-maintained research wiki. Every page is markdown with a
YAML frontmatter header:

```yaml
id: atlas:<dir>:<slug>          # derived from the file path
type: concept|entity|source|method|finding|comparison
tier: scratch|active|canonical|published|archived
aliases: [<≥1, mandatory>]      # drives duplicate detection
created_at / updated_at         # ISO-8601
claim_valid_at                  # when the strongest claim was made
last_verified_at                # when reconciled against sources (bi-temporal)
provenance: {source, run_id, parent_decision}
links: {derived_from, related_to, contradicts, cites}
embeddings: {model, hash}       # populated by the embeddings pass
```

Edit this file in plain English to change conventions; it is the only
configuration the agents read.
"""
