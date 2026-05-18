"""Frictionless ingest — drop a file in ``atlas/inbox/``, it's taken care of.

Deterministic and LLM-free: a dropped file is hashed, archived to
``atlas/raw/inbox/``, and written as a first-class ``sources/<slug>.md``
Atlas page (so it is immediately searchable and seen by the next pipeline
run). A sha256 ``.manifest.json`` makes re-ingest idempotent and records
provenance. The pipeline's Scout can later refine these into summaries; this
layer just makes capture zero-effort.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .. import config
from ..sandbox import validate_ingest_source
from .atlas import Atlas, PageWrite
from .ingest import read_source

MANIFEST = ".manifest.json"


def inbox_dir() -> Path:
    d = config.atlas_path() / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _raw_inbox() -> Path:
    d = config.atlas_path() / "raw" / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _manifest_path() -> Path:
    return inbox_dir() / MANIFEST


def _load_manifest() -> dict:
    p = _manifest_path()
    if not p.exists():
        return {"ingested": {}}
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {"ingested": {}}


def _save_manifest(m: dict) -> None:
    _manifest_path().write_text(json.dumps(m, indent=2))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "source"


def _pending(inbox: Path) -> list[Path]:
    """Files in the inbox that are not the manifest and are safe to read."""
    return [
        p for p in sorted(inbox.rglob("*"))
        if p.is_file()
        and p.name != MANIFEST
        and not p.name.startswith(".")
        and validate_ingest_source(p, inbox)
    ]


def pending_count() -> int:
    return len(_pending(inbox_dir()))


def ingest_inbox(atlas: Atlas | None = None, path: str | None = None) -> dict:
    """Process the inbox (or one ``path``). Returns a summary.

    Idempotent: a file whose sha is already recorded is skipped. Each new
    file becomes ``sources/<slug>.md`` in the Atlas and its original is
    archived under ``atlas/raw/inbox/``; the source is then removed from the
    drop zone so the inbox stays clean.
    """
    atlas = atlas or Atlas(config.atlas_path())
    inbox = inbox_dir()
    manifest = _load_manifest()
    ingested: dict = manifest.setdefault("ingested", {})

    if path:
        one = Path(path)
        if not one.is_absolute():
            one = inbox / path
        targets = [one] if one.is_file() else []
    else:
        targets = _pending(inbox)

    used_slugs = {e["page"] for e in ingested.values()}
    new: list[dict] = []
    skipped = 0

    for fp in targets:
        sha = _sha256(fp)
        if sha in ingested:
            skipped += 1
            if fp.is_relative_to(inbox):
                fp.unlink(missing_ok=True)  # already known; clear the dup
            continue

        content = read_source(fp)
        if content is None:
            continue

        slug = _slug(fp.stem)
        page = f"sources/{slug}.md"
        if page in used_slugs:
            page = f"sources/{slug}-{sha[:8]}.md"
        used_slugs.add(page)

        when = datetime.now(timezone.utc).isoformat()
        atlas.write(
            [PageWrite(
                path=page,
                title=fp.stem,
                content=content,
                summary=f"Ingested from inbox on {when[:10]} ({fp.name})",
            )],
            f"ingest | {fp.name}",
        )

        archived = _raw_inbox() / fp.name
        shutil.copy2(fp, archived)
        if fp.is_relative_to(inbox):
            fp.unlink(missing_ok=True)

        ingested[sha] = {
            "file": fp.name,
            "ingested_at": when,
            "raw_path": str(archived.relative_to(config.atlas_path())),
            "page": page,
            "version": 1,
        }
        new.append({"file": fp.name, "page": page})

    _save_manifest(manifest)
    return {"ingested": new, "skipped": skipped, "pending": pending_count()}
