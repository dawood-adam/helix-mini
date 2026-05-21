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


def validate_project_name(name: str) -> str:
    """A project / run / bundle name used as a single filesystem path
    segment. Model-controlled (MCP tool args, ingest-influenced), so it is
    confined the same way Atlas writes are: no separators, no ``..``, no
    leading dot. Returns the cleaned name or raises ``SandboxError``."""
    n = CONTROL_CHAR_PATTERN.sub("", str(name or "")).strip()
    if (
        not n
        or len(n) > 128
        or n in (".", "..")
        or ".." in n
        or n[0] in ".-"
        or "/" in n
        or "\\" in n
    ):
        raise SandboxError(f"Unsafe project/run name: {name!r}")
    return n


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


_ATLAS_ACTIONS = ("ADD", "UPDATE", "SUPERSEDE", "LINK", "NOOP")


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
        # Workstream G — write protocol fields. Compat: missing action
        # defaults to ADD with a "agent-emitted (no action declared)"
        # rationale, with a warning. Per phase-4 plan, hard-fail comes
        # later when all prompts have been updated.
        action = _clean_opt_str(w.get("action"))
        if action:
            action = action.upper()
            if action not in _ATLAS_ACTIONS:
                log.warning("Unknown atlas action %r, treating as ADD", action)
                action = "ADD"
        else:
            action = "ADD"
        because = _clean_opt_str(w.get("because")) or "agent-emitted (no action declared)"
        provenance = _clean_provenance(w.get("provenance"))
        spec_refs = _clean_str_list(w.get("spec_refs"))
        writes.append(PageWrite(
            path=w["path"], title=title, content=content, summary=summary,
            type=_clean_opt_str(w.get("type")),
            tier=_clean_opt_str(w.get("tier")),
            aliases=_clean_str_list(w.get("aliases")),
            links=_clean_links(w.get("links")),
            action=action, because=because,
            provenance=provenance, spec_refs=spec_refs,
        ))
    return writes


def _clean_provenance(v) -> dict | None:
    """Coerce a provenance dict to a small whitelist of expected keys, all
    stringified + control-stripped. Returns None if the input isn't a dict
    (the sanitizer's caller may derive defaults: stage / run_id /
    snapshot_id are knowable server-side)."""
    if not isinstance(v, dict):
        return None
    out: dict = {}
    for k in ("stage", "run_id", "snapshot_id", "confidence"):
        if v.get(k) is not None:
            out[k] = CONTROL_CHAR_PATTERN.sub("", str(v[k])).strip()[:128]
    srcs = _clean_str_list(v.get("sources"), cap=20)
    if srcs:
        out["sources"] = srcs
    return out or None


def _clean_opt_str(v) -> str | None:
    if not isinstance(v, str):
        return None
    v = CONTROL_CHAR_PATTERN.sub("", v).strip()
    return v[:64] or None


def _clean_str_list(v, cap: int = 12) -> list[str] | None:
    if not isinstance(v, list):
        return None
    out = [
        CONTROL_CHAR_PATTERN.sub("", str(x)).strip()[:MAX_PAGE_TITLE_LENGTH]
        for x in v[:cap]
    ]
    out = [x for x in out if x]
    return out or None


def _clean_links(v) -> dict | None:
    if not isinstance(v, dict):
        return None
    allowed = ("derived_from", "related_to", "contradicts", "cites")
    out: dict[str, list[str]] = {}
    for k in allowed:
        lst = _clean_str_list(v.get(k), cap=50)
        if lst:
            out[k] = lst
    return out or None


def validate_artifact_name(name: str, root: Path) -> Path:
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
) -> list[dict]:
    """Validate builder artifacts for safe writing under ``artifacts_root``.

    Returns one sanitized record per accepted artifact::

        {"path": <abs Path>, "name": <safe relative str>,
         "type": ..., "description": ..., "content": <size-capped str>}

    This is the single source of truth for what gets written *and* what is
    stored in pipeline state, so an unsafe name can never be persisted into a
    snapshot. Files are written by the caller but never executed.
    """
    if not isinstance(artifacts, list):
        return []
    if len(artifacts) > MAX_WRITES_PER_BATCH:
        log.warning("Artifact batch %d exceeds %d, truncating", len(artifacts), MAX_WRITES_PER_BATCH)
        artifacts = artifacts[:MAX_WRITES_PER_BATCH]
    out: list[dict] = []
    for a in artifacts:
        if not isinstance(a, dict):
            continue
        name, content = a.get("name"), a.get("content")
        if not isinstance(name, str) or not isinstance(content, str):
            log.warning("Skipping artifact missing string name/content")
            continue
        try:
            abs_path = validate_artifact_name(name, artifacts_root)
        except SandboxError as e:
            log.warning("Sandbox blocked artifact: %s", e)
            continue
        out.append({
            "path": abs_path,
            "name": str(abs_path.relative_to(artifacts_root.resolve())),
            "type": a.get("type"),
            "description": a.get("description"),
            "content": validate_content(content),
        })
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
