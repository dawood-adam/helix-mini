"""Sandbox — validates and sanitizes all LLM output before it reaches the filesystem."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from .atlas.store import PageWrite

log = logging.getLogger(__name__)

# --- Configuration constants ---
ALLOWED_SUBDIRS = {"sources", "concepts", "entities", "projects"}
MAX_PAGE_CONTENT_BYTES = 500_000  # 500 KB per page
MAX_PAGE_TITLE_LENGTH = 200
MAX_WRITES_PER_BATCH = 50
MAX_PATH_LENGTH = 255
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class SandboxError(Exception):
    """Raised when LLM output violates sandbox rules."""


def validate_path(path: str, atlas_root: Path) -> Path:
    """Validate a relative path from LLM output. Returns resolved Path.

    Checks: not absolute, no .., starts with allowed subdir, stays within root.
    """
    if len(path) > MAX_PATH_LENGTH:
        raise SandboxError(f"Path too long ({len(path)} chars): {path[:80]}...")

    if path.startswith("/") or path.startswith("\\"):
        raise SandboxError(f"Absolute path blocked: {path}")

    parts = Path(path).parts
    if ".." in parts:
        raise SandboxError(f"Path traversal blocked: {path}")

    if not parts or parts[0] not in ALLOWED_SUBDIRS:
        raise SandboxError(
            f"Path must start with one of {ALLOWED_SUBDIRS}, got: {path}"
        )

    resolved = (atlas_root / path).resolve()
    if not resolved.is_relative_to(atlas_root.resolve()):
        raise SandboxError(f"Resolved path escapes atlas root: {path}")

    return resolved


def validate_title(title: str) -> str:
    """Validate and clean a page title. Strips control chars, enforces length."""
    cleaned = CONTROL_CHAR_PATTERN.sub("", title).strip()
    if not cleaned:
        raise SandboxError("Empty page title after sanitization")
    if len(cleaned) > MAX_PAGE_TITLE_LENGTH:
        cleaned = cleaned[:MAX_PAGE_TITLE_LENGTH]
        log.warning("Truncated page title to %d chars", MAX_PAGE_TITLE_LENGTH)
    return cleaned


def validate_content(content: str) -> str:
    """Validate page content size. Truncates if too large."""
    if len(content.encode("utf-8", errors="replace")) > MAX_PAGE_CONTENT_BYTES:
        truncated = content[:MAX_PAGE_CONTENT_BYTES]
        log.warning("Page content truncated to %d bytes", MAX_PAGE_CONTENT_BYTES)
        return truncated + "\n\n[... content truncated by sandbox ...]"
    return content


def sanitize_atlas_writes(
    raw_writes: list[dict],
    atlas_root: Path,
) -> list[PageWrite]:
    """Parse and validate LLM atlas_writes through the full sandbox pipeline."""
    if len(raw_writes) > MAX_WRITES_PER_BATCH:
        log.warning(
            "Batch size %d exceeds limit %d, truncating",
            len(raw_writes), MAX_WRITES_PER_BATCH,
        )
        raw_writes = raw_writes[:MAX_WRITES_PER_BATCH]

    writes: list[PageWrite] = []
    for w in raw_writes:
        if not all(k in w for k in ("path", "title", "content", "summary")):
            log.warning("Skipping write missing required fields: %s", list(w.keys()))
            continue

        try:
            validate_path(w["path"], atlas_root)
            title = validate_title(w["title"])
            content = validate_content(w["content"])
            summary = validate_title(w["summary"])
        except SandboxError as e:
            log.warning("Sandbox blocked write: %s", e)
            continue

        writes.append(PageWrite(path=w["path"], title=title, content=content, summary=summary))

    return writes


def validate_ingest_source(file_path: Path, base_folder: Path) -> bool:
    """Validate that a source file is safe to read (rejects external symlinks)."""
    if file_path.is_symlink():
        try:
            target = file_path.resolve()
            if not target.is_relative_to(base_folder.resolve()):
                log.warning(
                    "Skipping symlink pointing outside folder: %s -> %s",
                    file_path, target,
                )
                return False
        except (OSError, ValueError):
            log.warning("Skipping unresolvable symlink: %s", file_path)
            return False
    return True
