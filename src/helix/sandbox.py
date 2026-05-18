"""Sandbox — validates all LLM output before it reaches the filesystem.

Imports ``PageWrite`` from ``helix.core.atlas`` (the store, which imports no
sandbox) so there is no import cycle: only ``helix.core.ingest`` depends on
this module.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from .core.atlas import PageWrite

log = logging.getLogger(__name__)

ALLOWED_SUBDIRS = {"sources", "concepts", "entities", "projects"}
MAX_PAGE_CONTENT_BYTES = 500_000
MAX_PAGE_TITLE_LENGTH = 200
MAX_WRITES_PER_BATCH = 50
MAX_PATH_LENGTH = 255
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class SandboxError(Exception):
    """Raised when LLM output violates sandbox rules."""


def validate_path(path: str, atlas_root: Path) -> Path:
    if len(path) > MAX_PATH_LENGTH:
        raise SandboxError(f"Path too long ({len(path)} chars): {path[:80]}...")
    if path.startswith(("/", "\\")):
        raise SandboxError(f"Absolute path blocked: {path}")
    parts = Path(path).parts
    if ".." in parts:
        raise SandboxError(f"Path traversal blocked: {path}")
    if not parts or parts[0] not in ALLOWED_SUBDIRS:
        raise SandboxError(f"Path must start with one of {ALLOWED_SUBDIRS}: {path}")
    resolved = (atlas_root / path).resolve()
    if not resolved.is_relative_to(atlas_root.resolve()):
        raise SandboxError(f"Resolved path escapes atlas root: {path}")
    return resolved


def validate_title(title: str) -> str:
    cleaned = CONTROL_CHAR_PATTERN.sub("", title).strip()
    if not cleaned:
        raise SandboxError("Empty page title after sanitization")
    if len(cleaned) > MAX_PAGE_TITLE_LENGTH:
        cleaned = cleaned[:MAX_PAGE_TITLE_LENGTH]
        log.warning("Truncated page title to %d chars", MAX_PAGE_TITLE_LENGTH)
    return cleaned


def validate_content(content: str) -> str:
    if len(content.encode("utf-8", errors="replace")) > MAX_PAGE_CONTENT_BYTES:
        log.warning("Page content truncated to %d bytes", MAX_PAGE_CONTENT_BYTES)
        return content[:MAX_PAGE_CONTENT_BYTES] + "\n\n[... truncated by sandbox ...]"
    return content


def sanitize_atlas_writes(raw_writes: list[dict], atlas_root: Path) -> list[PageWrite]:
    if len(raw_writes) > MAX_WRITES_PER_BATCH:
        log.warning("Batch %d exceeds %d, truncating", len(raw_writes), MAX_WRITES_PER_BATCH)
        raw_writes = raw_writes[:MAX_WRITES_PER_BATCH]
    writes: list[PageWrite] = []
    for w in raw_writes:
        if not isinstance(w, dict) or not all(
            k in w for k in ("path", "title", "content", "summary")
        ):
            log.warning("Skipping malformed atlas write")
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


def _validate_artifact_name(name: str, root: Path) -> Path:
    name = CONTROL_CHAR_PATTERN.sub("", name).strip()
    if not name:
        raise SandboxError("Empty artifact name")
    if len(name) > MAX_PATH_LENGTH:
        raise SandboxError(f"Artifact name too long: {name[:80]}...")
    if name.startswith(("/", "\\")) or (len(name) > 1 and name[1] == ":"):
        raise SandboxError(f"Absolute artifact path blocked: {name}")
    parts = Path(name).parts
    if not parts or any(p in ("..", "", ".") for p in parts):
        raise SandboxError(f"Unsafe artifact path blocked: {name}")
    resolved = (root / name).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise SandboxError(f"Artifact path escapes project dir: {name}")
    return resolved


def sanitize_code_artifacts(
    artifacts: list[dict], artifacts_root: Path
) -> list[tuple[Path, str]]:
    """Validate builder artifacts for safe writing under ``artifacts_root``.

    Returns ``(absolute_path, content)`` pairs. Files are written but never
    executed.
    """
    if not isinstance(artifacts, list):
        return []
    if len(artifacts) > MAX_WRITES_PER_BATCH:
        log.warning("Artifact batch %d exceeds %d, truncating", len(artifacts), MAX_WRITES_PER_BATCH)
        artifacts = artifacts[:MAX_WRITES_PER_BATCH]
    out: list[tuple[Path, str]] = []
    for a in artifacts:
        if not isinstance(a, dict):
            continue
        name, content = a.get("name"), a.get("content")
        if not isinstance(name, str) or not isinstance(content, str):
            log.warning("Skipping artifact missing string name/content")
            continue
        try:
            abs_path = _validate_artifact_name(name, artifacts_root)
        except SandboxError as e:
            log.warning("Sandbox blocked artifact: %s", e)
            continue
        out.append((abs_path, validate_content(content)))
    return out


def validate_ingest_source(file_path: Path, base_folder: Path) -> bool:
    """Reject symlinks that point outside the input folder."""
    if file_path.is_symlink():
        try:
            target = file_path.resolve()
            if not target.is_relative_to(base_folder.resolve()):
                log.warning("Skipping external symlink: %s -> %s", file_path, target)
                return False
        except (OSError, ValueError):
            log.warning("Skipping unresolvable symlink: %s", file_path)
            return False
    return True
