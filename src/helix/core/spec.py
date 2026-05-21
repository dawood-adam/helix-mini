"""Workstream B + F.2/F.3 — the project spec + clarify loop.

The spec is the researcher-facing artifact Scout produces (its FINER /
PICOT / GQM framing, candidate datasets, and any open questions). It
lives at ``projects/<id>/spec.md`` inside the Atlas as YAML frontmatter
+ a free-form markdown body. ``question.md`` (the original brief, in
the project's source folder) is the same shape — both flow through the
same loader.

Two related operations:

* ``question_check(project, atlas_root)`` validates the frontmatter
  (every FINER axis filled in, PICOT covers P/I/O at minimum, GQM has
  a goal + ≥1 question + ≥1 metric, ``gate.status == 'ready'``) and
  scans the body for unresolved markers. Returns structured findings;
  the orchestrator refuses to advance past Scout while findings remain.
* ``scan_clarifications(text)`` finds the three marker styles the
  spec_kit-style clarify loop knows about
  (``[NEEDS CLARIFICATION: ...]`` · ``TODO:`` · ``@open-question:``).
  ``apply_clarification(text, marker, replacement)`` does an anchored
  SEARCH/REPLACE patch so the spec mutates in place — no rewrites.

Pure stdlib + ``yaml``; no MCP, no model, no sandbox imports. Callers
(the MCP server's ``hx_question_check`` / ``hx_clarify`` tools, the
orchestrator's Scout submit gate) handle policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..sandbox import validate_project_name

# --- Schema ---------------------------------------------------------------

# Required frontmatter shape for a spec / question. Recommended axes only:
# spec drift earlier than this is fine. ``gate.status: ready`` is the
# Scout exit condition.
_FINER_AXES = ("feasible", "interesting", "novel", "ethical", "relevant")
_PICOT_AXES = ("population", "intervention", "outcome")  # comparator+time optional
_GQM_REQUIRED = ("goal", "questions", "metrics")

CLARIFY_MARKER = re.compile(
    r"\[NEEDS CLARIFICATION:\s*(.+?)\]|"
    r"(?:^|\s)TODO:\s*(.+?)$|"
    r"(?:^|\s)@open-question:\s*(.+?)$",
    re.MULTILINE,
)


# --- Dataclasses ----------------------------------------------------------


@dataclass
class Spec:
    """One parsed spec / question — frontmatter + body, round-trip safe."""

    frontmatter: dict = field(default_factory=dict)
    body: str = ""

    def to_text(self) -> str:
        fm = yaml.safe_dump(self.frontmatter or {}, sort_keys=False).strip()
        body = self.body if self.body.startswith("# ") else \
            "# Spec\n\n" + self.body
        return f"---\n{fm}\n---\n\n{body.rstrip()}\n"


@dataclass
class Finding:
    """One issue from question_check."""

    kind: str            # 'missing-finer' | 'missing-picot' | 'missing-gqm'
                          # | 'gate-not-ready' | 'clarification-marker'
    where: str           # frontmatter axis name OR snippet of the marker
    suggestion: str
    severity: str = "blocker"  # 'blocker' | 'soft'


@dataclass
class QuestionCheck:
    """Aggregate of all findings for one spec/question."""

    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True iff there are no blocker findings."""
        return not any(f.severity == "blocker" for f in self.findings)


# --- File I/O -------------------------------------------------------------


def spec_path(atlas_root: Path, project: str) -> Path:
    """The Atlas location of the project spec (``projects/<id>/spec.md``).

    Security: ``project`` is confined via ``validate_project_name`` —
    same pattern runs.py / snapshots.py / hot.py use. Without this an
    attacker-influenced MCP argument (``hx_clarify`` / ``hx_question_check``)
    could escape ``atlas_root/projects/`` and read/write arbitrary
    ``spec.md`` files (e.g. another workspace's spec) via ``..`` in the
    project name. Raises ``SandboxError`` on an unsafe name."""
    project = validate_project_name(project)
    return Path(atlas_root) / "projects" / project / "spec.md"


def load_spec(atlas_root: Path, project: str) -> Spec | None:
    p = spec_path(atlas_root, project)
    if not p.exists():
        return None
    return _parse(p.read_text())


def save_spec(atlas_root: Path, project: str, spec: Spec) -> Path:
    p = spec_path(atlas_root, project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(spec.to_text())
    return p


def load_question(folder: Path) -> Spec | None:
    """Load ``<folder>/question.md`` — the researcher's brief."""
    p = Path(folder) / "question.md"
    if not p.exists():
        return None
    return _parse(p.read_text())


def save_question(folder: Path, spec: Spec) -> Path:
    p = Path(folder) / "question.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(spec.to_text())
    return p


def _parse(text: str) -> Spec:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                fm = {}
            return Spec(frontmatter=fm if isinstance(fm, dict) else {},
                         body=parts[2].lstrip("\n"))
    return Spec(frontmatter={}, body=text)


# --- Validation -----------------------------------------------------------


def _is_filled(v) -> bool:
    """A spec axis counts as 'filled' if it's a non-blank string OR a
    non-empty list of non-blank strings. Anything else is a hole."""
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, list):
        return any(isinstance(x, str) and x.strip() for x in v)
    return False


def _check_finer(fm: dict) -> list[Finding]:
    finer = fm.get("finer")
    out: list[Finding] = []
    if not isinstance(finer, dict):
        for ax in _FINER_AXES:
            out.append(Finding(
                kind="missing-finer", where=ax,
                suggestion=f"add finer.{ax}: a one-sentence justification"))
        return out
    for ax in _FINER_AXES:
        if not _is_filled(finer.get(ax)):
            out.append(Finding(
                kind="missing-finer", where=ax,
                suggestion=f"fill in finer.{ax}"))
    return out


def _check_picot(fm: dict) -> list[Finding]:
    picot = fm.get("picot")
    out: list[Finding] = []
    if not isinstance(picot, dict):
        for ax in _PICOT_AXES:
            out.append(Finding(
                kind="missing-picot", where=ax,
                suggestion=f"add picot.{ax} (the {ax} of the question)"))
        return out
    for ax in _PICOT_AXES:
        if not _is_filled(picot.get(ax)):
            out.append(Finding(
                kind="missing-picot", where=ax,
                suggestion=f"fill in picot.{ax}"))
    return out


def _check_gqm(fm: dict) -> list[Finding]:
    gqm = fm.get("gqm")
    out: list[Finding] = []
    if not isinstance(gqm, dict):
        for ax in _GQM_REQUIRED:
            out.append(Finding(
                kind="missing-gqm", where=ax,
                suggestion=f"add gqm.{ax}"))
        return out
    for ax in _GQM_REQUIRED:
        if not _is_filled(gqm.get(ax)):
            out.append(Finding(
                kind="missing-gqm", where=ax,
                suggestion=f"fill in gqm.{ax}"))
    return out


def _check_gate(fm: dict) -> list[Finding]:
    gate = fm.get("gate")
    status = gate.get("status") if isinstance(gate, dict) else None
    if status == "ready":
        return []
    return [Finding(
        kind="gate-not-ready", where="gate.status",
        suggestion=(
            "once FINER / PICOT / GQM are filled and there are no "
            "[NEEDS CLARIFICATION] markers, set gate.status: ready"))]


def scan_clarifications(text: str) -> list[str]:
    """Return every unresolved clarification marker in ``text``.

    Three styles are recognised: ``[NEEDS CLARIFICATION: ...]``,
    ``TODO: ...``, ``@open-question: ...``. The returned strings are the
    captured bodies (with the marker stripped), in document order. Used by
    ``question_check`` and by the ``hx_clarify`` tool."""
    out: list[str] = []
    for m in CLARIFY_MARKER.finditer(text):
        for g in m.groups():
            if g is not None:
                out.append(g.strip())
                break
    return out


def question_check(atlas_root: Path, project: str,
                   source_folder: Path | None = None) -> QuestionCheck:
    """Validate the spec (or, if absent, the question) for ``project``.

    Tries ``projects/<id>/spec.md`` first; if missing and a
    ``source_folder`` is given, falls back to ``<folder>/question.md``.
    Returns blocker findings for: missing FINER axis · missing PICOT
    axis · missing GQM field · gate.status != 'ready' · any
    [NEEDS CLARIFICATION] (or TODO / @open-question) marker in the body."""
    spec = load_spec(atlas_root, project)
    if spec is None and source_folder is not None:
        spec = load_question(source_folder)
    if spec is None:
        return QuestionCheck(findings=[Finding(
            kind="missing-spec", where="projects/" + project + "/spec.md",
            suggestion=(
                "write the spec at projects/" + project + "/spec.md "
                "(or seed question.md in the project source folder)"))])

    findings: list[Finding] = []
    findings.extend(_check_finer(spec.frontmatter))
    findings.extend(_check_picot(spec.frontmatter))
    findings.extend(_check_gqm(spec.frontmatter))
    for marker in scan_clarifications(spec.body):
        findings.append(Finding(
            kind="clarification-marker", where=marker[:80],
            suggestion=(
                "resolve this marker (delete or replace with the answer) "
                "before Scout can submit")))
    findings.extend(_check_gate(spec.frontmatter))
    return QuestionCheck(findings=findings)


# --- Clarify SEARCH/REPLACE -----------------------------------------------


def apply_clarification(text: str, marker: str, replacement: str) -> tuple[str, bool]:
    """Anchored SEARCH/REPLACE patch for one clarification marker.

    ``marker`` is the captured body of a ``[NEEDS CLARIFICATION: ...]``
    (or TODO / @open-question) entry; we anchor on the full bracketed form
    so we never overshoot. Returns ``(new_text, patched)`` — ``patched`` is
    False if the marker wasn't found verbatim (no edit is applied).
    Idempotent on repeat calls with the same replacement."""
    needle = marker.strip()
    candidates = [
        f"[NEEDS CLARIFICATION: {needle}]",
        f"TODO: {needle}",
        f"@open-question: {needle}",
    ]
    for c in candidates:
        if c in text:
            return text.replace(c, replacement, 1), True
    return text, False
