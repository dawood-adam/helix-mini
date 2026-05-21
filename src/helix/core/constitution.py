"""Workspace-level Constitution — the project's non-negotiables.

Pattern after GitHub Spec Kit's ``memory/constitution.md``: a short,
agent-readable file of immutable principles (language · framework ·
testing · architectural style · definition of done) injected into every
agent's system prompt at turn-start.

Default location: ``<workspace>/constitution.md``. A per-project override
at ``<atlas>/projects/<project>/constitution.md`` wins when present
(spec §F-1: workspace by default + optional per-project override).
"""

from __future__ import annotations

from pathlib import Path

from .. import config

WORKSPACE_FILENAME = "constitution.md"

DEFAULT_TEMPLATE = """# Constitution

The non-negotiables for every Helix run in this workspace. Agents read
this at the start of every turn; keep it short, concrete, and amendable.

## Language & runtime
- Python ≥ 3.11 by default; declare per-project alternatives only when
  needed.

## Testing
- Strict TDD: no implementation before a failing test.
- Never disable or delete a test to make code pass.

## Architecture
- Deep modules: small public interfaces, substantial implementations
  (Ousterhout, APoSD).
- Spec is the source of truth — drift creates a follow-up task in
  `tasks.md`, never a hand-wave or in-place patch.

## Definition of done
- All Validator bands met; Results Critic verdict `ship`; the stage's
  HTML report exists; the spec line(s) advanced are declared in the
  Decision Card.
"""


def _override_path(project: str) -> Path:
    return config.atlas_path() / "projects" / project / WORKSPACE_FILENAME


def constitution_path(project: str | None = None) -> Path:
    """Resolve the active Constitution: project override if present, else
    the workspace-level file."""
    if project:
        ov = _override_path(project)
        if ov.exists():
            return ov
    return config.workspace_root() / WORKSPACE_FILENAME


def load_constitution(project: str | None = None) -> str:
    """Return the Constitution body, or ``""`` if no file exists."""
    p = constitution_path(project)
    return p.read_text() if p.exists() else ""


def save_constitution(text: str, project: str | None = None) -> Path:
    """Write the Constitution (workspace by default, or the project
    override if ``project`` is given). Creates parents as needed."""
    if project:
        p = _override_path(project)
    else:
        p = config.workspace_root() / WORKSPACE_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def ensure_constitution(workspace_root: Path) -> Path:
    """Idempotent scaffold for ``helix init``: write the default template
    if no Constitution exists at the workspace root."""
    p = Path(workspace_root) / WORKSPACE_FILENAME
    if not p.exists():
        p.write_text(DEFAULT_TEMPLATE)
    return p
