"""File ingestion — reads folders into Pages for the pipeline."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..sandbox import validate_ingest_source
from .store import Page

SUPPORTED_TEXT = {".md", ".txt", ".py", ".json", ".csv", ".toml", ".yaml", ".yml", ".rst"}


def ingest_folder(folder: Path, raw_root: Path) -> list[Page]:
    """Read all files from a folder, copy to raw/, return as Pages."""
    pages: list[Page] = []

    raw_dest = raw_root / folder.name
    raw_dest.mkdir(parents=True, exist_ok=True)

    for file_path in sorted(folder.rglob("*")):
        if not file_path.is_file():
            continue
        if not validate_ingest_source(file_path, folder):
            continue

        # Copy to raw
        dest = raw_dest / file_path.relative_to(folder)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, dest)

        # Read content for supported text formats
        if file_path.suffix.lower() in SUPPORTED_TEXT:
            try:
                content = file_path.read_text(errors="replace")
                if len(content) > 50_000:
                    content = content[:50_000] + "\n\n[... truncated ...]"
                pages.append(Page(
                    path=str(file_path.relative_to(folder)),
                    title=file_path.stem,
                    content=content,
                ))
            except Exception:
                continue
        elif file_path.suffix.lower() == ".pdf":
            content = _read_pdf(file_path)
            if content:
                pages.append(Page(
                    path=str(file_path.relative_to(folder)),
                    title=file_path.stem,
                    content=content,
                ))

    return pages


def _read_pdf(path: Path) -> str | None:
    """Read PDF text if pymupdf is available."""
    try:
        import fitz  # pymupdf

        doc = fitz.open(str(path))
        text = "\n\n".join(page.get_text() for page in doc)
        doc.close()
        if len(text) > 50_000:
            text = text[:50_000] + "\n\n[... truncated ...]"
        return text
    except ImportError:
        return f"[PDF file — install pymupdf to extract text: {path.name}]"
    except Exception:
        return None
