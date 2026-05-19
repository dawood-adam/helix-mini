"""Ingestion — the legacy folder path (scout) + the inbox/manifest drop zone.

``ingest_folder`` is unchanged (scout still ingests ``state.input_folder``).
``ingest_inbox`` is the frictionless path: drop files in ``atlas/inbox/``,
a ``.manifest.json`` sha256 delta makes re-runs idempotent, each new file
becomes a ``type: source`` frontmatter page and its original moves to
``atlas/raw/`` so the inbox stays a clean drop zone.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..sandbox import validate_ingest_source
from .atlas import Atlas, Page, PageWrite

SUPPORTED_TEXT = {
    ".md", ".txt", ".py", ".json", ".csv", ".toml", ".yaml", ".yml", ".rst",
}
_MAX = 50_000


def ingest_folder(folder: Path, raw_root: Path) -> list[Page]:
    """Read all files in ``folder``, copy to ``raw_root``, return Pages."""
    pages: list[Page] = []
    raw_dest = raw_root / folder.name
    raw_dest.mkdir(parents=True, exist_ok=True)

    for fp in sorted(folder.rglob("*")):
        if not fp.is_file() or not validate_ingest_source(fp, folder):
            continue
        dest = raw_dest / fp.relative_to(folder)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fp, dest)

        suffix = fp.suffix.lower()
        if suffix in SUPPORTED_TEXT:
            try:
                content = fp.read_text(errors="replace")
            except Exception:
                continue
        elif suffix == ".pdf":
            content = _read_pdf(fp)
        else:
            continue
        if content is None:
            continue
        if len(content) > _MAX:
            content = content[:_MAX] + "\n\n[... truncated ...]"
        pages.append(
            Page(path=str(fp.relative_to(folder)), title=fp.stem, content=content)
        )
    return pages


def _read_pdf(path: Path) -> str | None:
    try:
        import fitz  # pymupdf
    except ImportError:
        return f"[PDF file — install pymupdf to extract text: {path.name}]"
    try:
        doc = fitz.open(str(path))
        text = "\n\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    except Exception:
        return None


# --- inbox / manifest delta ingest -----------------------------------------


def _slug(stem: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return s or "source"


def _extract(fp: Path) -> str:
    suffix = fp.suffix.lower()
    if suffix in SUPPORTED_TEXT:
        try:
            content = fp.read_text(errors="replace")
        except Exception:
            content = f"[unreadable text source: {fp.name}]"
    elif suffix == ".pdf":
        content = _read_pdf(fp) or f"[unreadable PDF: {fp.name}]"
    else:
        content = f"[binary source: {fp.name}]"
    if len(content) > _MAX:
        content = content[:_MAX] + "\n\n[... truncated ...]"
    return content


def ingest_inbox(atlas: Atlas, *, only: str | None = None) -> dict:
    """Process new/changed files in ``atlas/inbox/`` (idempotent via sha256).

    Returns ``{"new": n, "ingested": [names], "skipped": n}``.
    """
    inbox = atlas.root / "inbox"
    raw = atlas.root / "raw"
    inbox.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    mpath = inbox / ".manifest.json"
    try:
        manifest = json.loads(mpath.read_text()) if mpath.exists() else {}
    except (OSError, ValueError):
        manifest = {}
    manifest.setdefault("ingested", {})

    if only:
        target = inbox / Path(only).name
        candidates = [target] if target.is_file() else []
    else:
        candidates = sorted(
            p for p in inbox.iterdir()
            if p.is_file() and not p.name.startswith(".")
        )

    writes: list[PageWrite] = []
    moves: list[tuple[Path, Path]] = []
    new: list[str] = []
    skipped = 0
    for fp in candidates:
        sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        key = f"inbox/{fp.name}"
        if manifest["ingested"].get(key, {}).get("sha256") == sha:
            skipped += 1
            continue
        page_path = f"sources/{_slug(fp.stem)}.md"
        writes.append(PageWrite(
            path=page_path, title=fp.stem, content=_extract(fp),
            summary=f"Ingested source: {fp.name}", type="source",
            aliases=[fp.stem],
        ))
        moves.append((fp, raw / fp.name))
        manifest["ingested"][key] = {
            "sha256": sha,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "raw_path": f"raw/{fp.name}",
            "source_page": page_path,
        }
        new.append(fp.name)

    if writes:
        atlas.write(writes, f"ingest | {len(writes)} source(s) from inbox")
        for src, dest in moves:
            shutil.move(str(src), str(dest))
    mpath.write_text(json.dumps(manifest, indent=2))
    return {"new": len(new), "ingested": new, "skipped": skipped}
