"""Idempotent Atlas tree scaffolder.

Shared by ``helix init`` (scaffolding a new workspace) and lint's
one-click fix for a missing standard directory. Pure path I/O — no MCP,
no model, no surprises."""

from __future__ import annotations

from pathlib import Path

# The canonical Atlas tree. Stable directories the rest of the system
# (recall · lint · write protocol · threads · datasets) expects to find.
_DIRS = (
    "inbox",                                # unprocessed sources
    "raw",                                  # ingested originals
    "sources",                              # type: source pages
    "concepts",                             # type: concept pages
    "concepts/contradictions",              # surfaced by Scout (Workstream G)
    "concepts/methods",                     # methods that generalize across projects
    "concepts/glossary",                    # Ubiquitous Language workspace-shared terms (F.4)
    "entities",                             # type: entity pages
    "entities/datasets",                    # data thread anchors (Workstream E)
    "projects",                             # per-project subtrees
)


def ensure_atlas_tree(root: Path) -> Path:
    """Create the canonical Atlas tree at ``root`` (idempotent). Returns
    the resolved root for convenience."""
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for d in _DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    return root
