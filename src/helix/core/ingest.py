"""Folder ingestion — reads source files into Pages, archives originals."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..sandbox import validate_ingest_source
from .atlas import Page

SUPPORTED_TEXT = {
    ".md", ".txt", ".py", ".json", ".csv", ".toml", ".yaml", ".yml", ".rst",
}
_MAX = 50_000


def read_source(path: Path) -> str | None:
    """Extract text from a supported file, size-capped. None if unreadable.

    Shared by folder ingestion and the inbox drop-zone so the supported-format
    and truncation rules live in one place.
    """
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_TEXT:
        try:
            content = path.read_text(errors="replace")
        except Exception:
            return None
    elif suffix == ".pdf":
        content = _read_pdf(path)
    else:
        return None
    if content is None:
        return None
    if len(content) > _MAX:
        content = content[:_MAX] + "\n\n[... truncated ...]"
    return content


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

        content = read_source(fp)
        if content is None:
            continue
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
