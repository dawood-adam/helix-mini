"""Workstream E — threads (longitudinal artifacts).

A *thread* is a small, evolving Atlas page that spans the pipeline (the
``question/hypothesis``, ``data``, ``spec``, ``plan``, ``design``,
``code-org`` and ``glossary`` threads). Each lives at a known path
(``projects/<id>/threads/<name>.md`` for project-scoped threads; the
spec/plan are stored at ``projects/<id>/{spec,plan}.md`` and treated
as threads via the same load/save API), carries a tiny YAML
frontmatter, and uses the markdown body for *per-snapshot updates*
(one ``## snap-<id>`` section per stage transition).

Schema (frontmatter): ``{thread, status, opened_at, last_touched_at,
contributors}``. The status machine is ``Proposed → Accepted →
Superseded`` (write-time validated).

The reader (``read_at``) returns the thread's state *at* a given snapshot
— Graphiti's bi-temporal pattern done cheaply: walk the per-snapshot
sections in order and stop. Wired into the MCP server as
``thread://<project>/<name>[?at=<snap>]``.

Imports only stdlib + yaml — no Atlas / no sandbox / no model. Callers
(agents, the orchestrator, the MCP server) handle policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ..sandbox import SandboxError, validate_project_name

STATUSES = ("Proposed", "Accepted", "Superseded")

# Stages MAY include any of these. ``hypothesis`` is the Workstream-H
# alias; aliases live in ``_PATH_MAP`` so the canonical filename stays
# stable.
THREAD_NAMES = (
    "hypothesis", "data", "spec", "plan", "design", "code-org", "glossary",
)
_PATH_MAP = {
    "hypothesis": "threads/hypothesis.md",
    "data":       "threads/data.md",
    "spec":       "spec.md",
    "plan":       "plan.md",
    "design":     "threads/design.md",
    "code-org":   "threads/code-org.md",
    "glossary":   "threads/glossary.md",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ThreadError(Exception):
    """Raised on an invalid status transition or unknown thread name."""


@dataclass
class Thread:
    """One thread: frontmatter + body (with per-snapshot ``## snap-X`` sections)."""

    name: str
    status: str = "Proposed"
    opened_at: str = ""
    last_touched_at: str = ""
    contributors: list[str] = field(default_factory=list)
    body: str = ""

    def to_text(self) -> str:
        fm = yaml.safe_dump({
            "thread": self.name, "status": self.status,
            "opened_at": self.opened_at,
            "last_touched_at": self.last_touched_at,
            "contributors": list(self.contributors),
        }, sort_keys=False).strip()
        body = self.body if self.body.startswith("# ") else \
            f"# {_title_for(self.name)}\n\n{self.body}"
        return f"---\n{fm}\n---\n\n{body.rstrip()}\n"


def _title_for(name: str) -> str:
    return {
        "hypothesis": "Hypothesis thread",
        "data":       "Data thread",
        "spec":       "Spec",
        "plan":       "Plan",
        "design":     "Design thread",
        "code-org":   "Code organization thread",
        "glossary":   "Glossary (Ubiquitous Language)",
    }.get(name, f"{name.title()} thread")


def _resolve_path(atlas_root: Path, project: str, name: str) -> Path:
    if name not in _PATH_MAP:
        raise ThreadError(
            f"Unknown thread '{name}'. Known: {sorted(_PATH_MAP)}.")
    # Security: confine ``project`` the same way Atlas writes (snapshots,
    # runs, hot, atlas paths) do — no path separators, no ``..``, no
    # leading dot. Without this, an attacker-influenced MCP argument
    # could escape ``atlas_root/projects/`` and read or write arbitrary
    # files whose names happen to end in one of the seven _PATH_MAP
    # suffixes (e.g. another workspace's ``spec.md``).
    try:
        project = validate_project_name(project)
    except SandboxError as e:
        raise ThreadError(str(e)) from e
    return Path(atlas_root) / "projects" / project / _PATH_MAP[name]


def thread_path(atlas_root: Path, project: str, name: str) -> Path:
    """Resolve the on-disk path for a project thread (for callers that
    want to write through Atlas / sandbox themselves)."""
    return _resolve_path(atlas_root, project, name)


def _parse(text: str, name: str) -> Thread:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                fm = {}
            body = parts[2].lstrip("\n")
        else:
            fm, body = {}, text
    else:
        fm, body = {}, text
    fm = fm if isinstance(fm, dict) else {}
    contribs = fm.get("contributors")
    return Thread(
        name=str(fm.get("thread", name) or name),
        status=fm["status"] if fm.get("status") in STATUSES else "Proposed",
        opened_at=str(fm.get("opened_at", "")),
        last_touched_at=str(fm.get("last_touched_at", "")),
        contributors=[str(c) for c in contribs] if isinstance(contribs, list) else [],
        body=body,
    )


def load_thread(atlas_root: Path, project: str, name: str) -> Thread | None:
    p = _resolve_path(atlas_root, project, name)
    if not p.exists():
        return None
    return _parse(p.read_text(), name)


def ensure_thread(atlas_root: Path, project: str, name: str,
                  contributor: str = "") -> Thread:
    """Load the thread, creating a Proposed stub if missing.

    Idempotent. Used by the per-stage prompt builders (when Scout opens the
    glossary, Planner opens the data thread, etc.) so the agent always
    sees a well-formed page rather than having to create it from scratch."""
    t = load_thread(atlas_root, project, name)
    if t is not None:
        return t
    now = _now()
    t = Thread(name=name, status="Proposed",
               opened_at=now, last_touched_at=now,
               contributors=[contributor] if contributor.strip() else [],
               body=f"# {_title_for(name)}\n\n(opened {now})\n")
    save_thread(atlas_root, project, t)
    return t


def save_thread(atlas_root: Path, project: str, t: Thread) -> Path:
    p = _resolve_path(atlas_root, project, t.name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(t.to_text())
    return p


def _validate_transition(old: str, new: str) -> None:
    if new not in STATUSES:
        raise ThreadError(f"Unknown status {new!r}. One of: {STATUSES}.")
    # Allowed: stay; Proposed → Accepted; Accepted → Superseded;
    # Proposed → Superseded (skip Accepted, e.g. ruled out at Scout Critic).
    legal = {
        "Proposed":   {"Proposed", "Accepted", "Superseded"},
        "Accepted":   {"Accepted", "Superseded"},
        "Superseded": {"Superseded"},
    }
    if new not in legal.get(old, set()):
        raise ThreadError(f"Illegal transition {old} → {new}.")


_SNAP_HEADER = re.compile(r"^## snap-([^\s]+)\s*$", re.MULTILINE)


def append_update(atlas_root: Path, project: str, name: str,
                  snapshot_id: str, body: str,
                  status: str | None = None,
                  contributor: str = "") -> Thread:
    """Append a ``## snap-<id>`` section to the thread's body, update its
    ``last_touched_at`` clock, optionally transition status, and persist.

    Idempotent on snapshot_id: a second call with the same id REPLACES the
    section in place rather than duplicating it (a re-run after send-back
    should overwrite, not append-twice)."""
    t = ensure_thread(atlas_root, project, name, contributor=contributor)
    sid = str(snapshot_id).strip() or "?"
    # Be friendly: accept either the raw id ("3") or the conventional
    # display form ("snap-3") so callers don't have to think about it.
    if sid.startswith("snap-"):
        sid = sid[5:]
    new_section = f"\n## snap-{sid}\n\n{body.rstrip()}\n"
    # Replace any existing same-id section in place.
    matches = list(_SNAP_HEADER.finditer(t.body))
    replaced = False
    for i, m in enumerate(matches):
        if m.group(1) == sid:
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(t.body)
            t.body = (t.body[:start].rstrip()
                      + new_section
                      + ("\n" + t.body[end:].lstrip() if t.body[end:].strip() else "\n"))
            replaced = True
            break
    if not replaced:
        t.body = t.body.rstrip() + new_section
    t.last_touched_at = _now()
    if contributor.strip() and contributor not in t.contributors:
        t.contributors.append(contributor)
    if status is not None:
        _validate_transition(t.status, status)
        t.status = status
    save_thread(atlas_root, project, t)
    return t


def set_status(atlas_root: Path, project: str, name: str,
               new_status: str) -> Thread:
    """Surgical status transition (no body change)."""
    t = ensure_thread(atlas_root, project, name)
    _validate_transition(t.status, new_status)
    t.status = new_status
    t.last_touched_at = _now()
    save_thread(atlas_root, project, t)
    return t


def read_at(atlas_root: Path, project: str, name: str,
            snapshot_id: str) -> Thread | None:
    """The thread as it was *up to and including* ``snapshot_id``.

    Walks the per-snapshot sections in declaration order and truncates the
    body just after the matching section. Returns ``None`` if the thread
    doesn't exist; returns the thread with an empty body if ``snapshot_id``
    appears before any section (the agent should treat that as "nothing
    yet")."""
    t = load_thread(atlas_root, project, name)
    if t is None:
        return None
    matches = list(_SNAP_HEADER.finditer(t.body))
    if not matches:
        return t
    sid = str(snapshot_id)
    if sid.startswith("snap-"):
        sid = sid[5:]
    # Find prelude (everything before the first ## snap-X header).
    prelude = t.body[: matches[0].start()].rstrip()
    cut = None
    for i, m in enumerate(matches):
        if m.group(1) == sid:
            cut = matches[i + 1].start() if i + 1 < len(matches) else len(t.body)
            break
    if cut is None:
        # Snapshot id not in the body — return the thread with body truncated to
        # the prelude, signalling "this snapshot didn't touch the thread".
        return Thread(name=t.name, status=t.status,
                       opened_at=t.opened_at, last_touched_at=t.last_touched_at,
                       contributors=list(t.contributors),
                       body=prelude + "\n" if prelude else "")
    truncated = (prelude + "\n\n" if prelude else "") + t.body[matches[0].start():cut].rstrip() + "\n"
    return Thread(name=t.name, status=t.status,
                   opened_at=t.opened_at, last_touched_at=t.last_touched_at,
                   contributors=list(t.contributors),
                   body=truncated)


def list_threads(atlas_root: Path, project: str) -> list[Thread]:
    """Every thread on disk for a project, in canonical order."""
    out: list[Thread] = []
    for name in THREAD_NAMES:
        t = load_thread(atlas_root, project, name)
        if t is not None:
            out.append(t)
    return out


# --- Glossary helpers ------------------------------------------------------

# A glossary term is a markdown ``### <term>`` heading in the glossary
# thread body. The body of a term is everything up to the next ``###``
# or end-of-file. ``parse_glossary_terms`` returns ``{term: definition}``;
# trivially used by lint's ``vocabulary-drift`` and by agent prompts that
# want to inline the active vocabulary.

_TERM_HEADER = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)


def parse_glossary_terms(thread: Thread) -> dict[str, str]:
    """Return ``{term: short-definition}`` from a glossary thread body."""
    out: dict[str, str] = {}
    if thread is None or thread.name != "glossary":
        return out
    headers = list(_TERM_HEADER.finditer(thread.body))
    for i, h in enumerate(headers):
        term = h.group(1).strip()
        if not term:
            continue
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(thread.body)
        # Skip per-snapshot meta if the term body opens with one.
        defn = thread.body[start:end].strip().splitlines()
        first = next((ln.strip() for ln in defn if ln.strip()), "")
        out[term.lower()] = first[:240]
    return out
