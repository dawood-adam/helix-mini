"""Stage HTML reports + the inline annotation overlay (spec §D).

Every stage emits one self-contained HTML report at
``projects/<id>/reports/<stage>.html``, overwritten on every (re-)run.
The same file carries:

- the rendered per-agent template (IMRaD/PRISMA · Blameless PIR · Rust
  RFC · MADR · IMRaD-Methods/Results · Blameless PIR + verdict);
- an embedded W3C-Web-Annotation JSON block (critic notes + researcher
  marks + kept/rejected state + comment threads);
- a small inline JS/CSS overlay that paints Distill-style side-notes
  and offers Accept · Reject · Reply · Send back · Comment / Suggest;
- a save-back path using the File System Access API (with a
  "Download annotated copy" fallback for non-Chromium browsers).

Round-trip on send-back: :func:`parse_round_trip` extracts the embedded
JSON from the modified HTML so :func:`build_send_back_feedback` can
produce a structured feedback string for the stage re-run (kept
annotations · rejections + reasons · replies · researcher comments ·
previous report).

The module is pure: no MCP, no model, no network. SDK-light core
invariant preserved.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import constitution
from .decisions import DecisionCard

# --- Embedded overlay JS + CSS (self-contained, no external runtime) -------

_OVERLAY_CSS = """
:root {
  --hx-bg:#fff; --hx-fg:#1b1f23; --hx-muted:#57606a; --hx-line:#d0d7de;
  --hx-accent:#0550ae; --hx-warn:#bf3989; --hx-ok:#1a7f37; --hx-err:#cf222e;
  --hx-sidebg:#f6f8fa; --hx-code:#f6f8fa;
}
@media (prefers-color-scheme: dark) {
  :root { --hx-bg:#0d1117; --hx-fg:#e6edf3; --hx-muted:#8b949e;
    --hx-line:#30363d; --hx-accent:#58a6ff; --hx-warn:#db61a2;
    --hx-ok:#3fb950; --hx-err:#f85149; --hx-sidebg:#161b22; --hx-code:#161b22; }
}
* { box-sizing: border-box; }
body { background: var(--hx-bg); color: var(--hx-fg); margin: 0;
  font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI",
  Helvetica, Arial, sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 24px;
  display: grid; grid-template-columns: minmax(0,1fr) 260px; gap: 24px; }
@media (max-width: 880px) { main { grid-template-columns: 1fr; }
  aside.hx-gutter { position: static !important; } }
article { min-width: 0; }
article h1 { font-size: 26px; margin: 0 0 8px; }
article h2 { font-size: 19px; margin: 22px 0 6px; padding-top: 8px;
  border-top: 1px solid var(--hx-line); }
article h3 { font-size: 16px; margin: 16px 0 4px; }
article p, article ul, article ol { margin: 8px 0; }
article ul, article ol { padding-left: 22px; }
code, pre { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-size: 13px; }
code { background: var(--hx-code); padding: 1px 5px; border-radius: 4px; }
pre { background: var(--hx-code); padding: 12px 14px; border-radius: 6px;
  overflow: auto; border: 1px solid var(--hx-line); }
table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 14px; }
th, td { border: 1px solid var(--hx-line); padding: 6px 10px;
  vertical-align: top; text-align: left; }
th { background: var(--hx-sidebg); font-weight: 600; }
.hx-meta { color: var(--hx-muted); font-size: 13px; margin: 4px 0 14px; }
.hx-badge { display: inline-block; padding: 1px 8px; border-radius: 999px;
  font-size: 11px; font-weight: 600; background: var(--hx-sidebg);
  border: 1px solid var(--hx-line); }
.hx-section { padding: 4px 6px; border-radius: 4px; }
.hx-section.hx-anchored { background: rgba(187, 137, 0, 0.10); }
aside.hx-gutter { position: sticky; top: 24px; align-self: start;
  font-size: 12px; display: flex; flex-direction: column; gap: 10px;
  max-height: calc(100vh - 48px); overflow: auto; }
.hx-anno { border-left: 3px solid var(--hx-warn); background: var(--hx-sidebg);
  padding: 8px 10px; border-radius: 0 4px 4px 0; }
.hx-anno[data-state="accepted"] { border-left-color: var(--hx-ok); opacity: 0.7; }
.hx-anno[data-state="rejected"] { border-left-color: var(--hx-muted); opacity: 0.5; }
.hx-anno .hx-who { font-weight: 600; color: var(--hx-warn); }
.hx-anno[data-state="accepted"] .hx-who { color: var(--hx-ok); }
.hx-anno .hx-body { margin: 4px 0; color: var(--hx-fg); }
.hx-anno .hx-acts { display: flex; gap: 6px; flex-wrap: wrap; }
.hx-anno button { font-size: 11px; padding: 2px 8px; border: 1px solid var(--hx-line);
  border-radius: 999px; background: var(--hx-bg); color: var(--hx-fg); cursor: pointer; }
.hx-anno button.primary { background: var(--hx-accent); color: white;
  border-color: var(--hx-accent); }
.hx-anno button.danger { color: var(--hx-err); }
.hx-toolbar { position: fixed; right: 24px; bottom: 24px;
  background: var(--hx-bg); border: 1px solid var(--hx-line);
  border-radius: 999px; padding: 6px 12px; display: flex; gap: 8px;
  align-items: center; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }
.hx-toolbar .hx-count { font-size: 12px; color: var(--hx-muted); }
.hx-toolbar button { padding: 4px 12px; border-radius: 999px;
  border: 1px solid var(--hx-line); background: var(--hx-bg);
  color: var(--hx-fg); cursor: pointer; font-size: 12px; }
.hx-toolbar button.primary { background: var(--hx-accent); color: white;
  border-color: var(--hx-accent); }
.hx-suggest { background: rgba(63, 185, 80, 0.18); text-decoration: none; }
.hx-strike  { background: rgba(248, 81, 73, 0.18); text-decoration: line-through; }
"""

_OVERLAY_JS = r"""
(function () {
  const SCRIPT_ID = "hx-annotations";
  const dataEl = document.getElementById(SCRIPT_ID);
  if (!dataEl) return;
  let data;
  try { data = JSON.parse(dataEl.textContent || "{}"); }
  catch (e) { console.error("hx: bad annotations JSON", e); return; }
  data.annotations = data.annotations || [];
  let fileHandle = null;

  function persist() {
    dataEl.textContent = "\n" + JSON.stringify(data, null, 2) + "\n";
    saveInPlace();
    paint();
  }

  async function saveInPlace() {
    const html = "<!doctype html>\n" + document.documentElement.outerHTML;
    if (fileHandle) {
      try {
        const w = await fileHandle.createWritable();
        await w.write(html); await w.close();
        return;
      } catch (e) { console.warn("hx: in-place save failed", e); }
    }
    // Fallback: silent — explicit Download button writes to disk.
  }

  async function pickFile() {
    if (!window.showSaveFilePicker) {
      alert("File System Access API not available. Use Download.");
      return;
    }
    try {
      fileHandle = await window.showSaveFilePicker({
        suggestedName: location.pathname.split("/").pop(),
        types: [{ description: "Helix report", accept: { "text/html": [".html"] } }],
      });
      saveInPlace();
    } catch (e) { /* user cancelled */ }
  }

  function download() {
    const html = "<!doctype html>\n" + document.documentElement.outerHTML;
    const blob = new Blob([html], { type: "text/html" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = location.pathname.split("/").pop();
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 500);
  }

  function findAnchor(target) {
    for (const sel of target.selector || []) {
      if (sel.type === "FragmentSelector") {
        const el = document.getElementById(sel.value);
        if (el) return el;
      }
    }
    return null;
  }

  function paint() {
    const gutter = document.getElementById("hx-gutter");
    gutter.innerHTML = "";
    // remove old highlights
    document.querySelectorAll(".hx-anchored").forEach(e => e.classList.remove("hx-anchored"));
    let openCount = 0;
    data.annotations.forEach(ann => {
      if (ann.state === "open") openCount++;
      const node = document.createElement("div");
      node.className = "hx-anno";
      node.setAttribute("data-state", ann.state || "open");
      node.setAttribute("data-id", ann.id);
      const who = (ann.creator && ann.creator.name) || "annotation";
      const sev = (ann.severity || "med")[0].toUpperCase();
      const stateLabel = ann.state && ann.state !== "open" ? " · " + ann.state : " · open";
      node.innerHTML =
        '<div class="hx-who">[' + sev + '] ' + escapeHtml(who) + stateLabel + '</div>' +
        '<div class="hx-body">' + escapeHtml((ann.body && ann.body.value) || "") + '</div>' +
        '<div class="hx-acts"></div>';
      const acts = node.querySelector(".hx-acts");
      if (ann.state === "open") {
        addBtn(acts, "Accept", "primary", () => resolve(ann, "accepted"));
        addBtn(acts, "Reject", "", () => {
          const r = prompt("Reason (optional):") || "";
          resolve(ann, "rejected", r);
        });
        addBtn(acts, "Reply", "", () => {
          const r = prompt("Reply:") || "";
          if (r) reply(ann, r);
        });
        addBtn(acts, "Send back ↩", "danger", () => sendBack(ann));
      } else {
        addBtn(acts, "Re-open", "", () => resolve(ann, "open"));
      }
      gutter.appendChild(node);
      // highlight the anchored section
      const anchor = findAnchor(ann.target || {});
      if (anchor) anchor.classList.add("hx-anchored");
    });
    document.getElementById("hx-open-count").textContent = openCount + " unresolved";
  }

  function addBtn(parent, label, cls, onClick) {
    const b = document.createElement("button");
    b.textContent = label; if (cls) b.className = cls;
    b.onclick = onClick; parent.appendChild(b);
  }

  function logEvent(ann, action, extra) {
    ann.log = ann.log || [];
    ann.log.push({ actor: "researcher", action, at: new Date().toISOString(),
      ...(extra || {}) });
  }

  function resolve(ann, newState, reason) {
    ann.state = newState;
    logEvent(ann, newState, reason ? { reason } : null);
    persist();
  }

  function reply(ann, text) {
    ann.replies = ann.replies || [];
    ann.replies.push({ actor: "researcher", body: text,
      at: new Date().toISOString() });
    logEvent(ann, "replied", { reply: text });
    persist();
  }

  function sendBack(ann) {
    ann.state = "send_back";
    logEvent(ann, "send_back_requested");
    persist();
  }

  function addComment() {
    const sel = window.getSelection();
    const quote = (sel && sel.toString()) || "";
    if (!quote) { alert("Select text to comment on."); return; }
    const body = prompt("Your comment:");
    if (!body) return;
    const target = buildTargetForSelection(sel);
    const ann = {
      id: "hx-ann-" + (Date.now()),
      type: "Annotation",
      creator: { type: "Person", name: "researcher" },
      created: new Date().toISOString(),
      state: "open",
      severity: "low",
      body: { type: "TextualBody", value: body, purpose: "commenting" },
      target, log: [],
    };
    data.annotations.push(ann);
    persist();
  }

  function buildTargetForSelection(sel) {
    const target = { source: location.pathname, selector: [] };
    const node = sel.anchorNode;
    const sec = node && (node.nodeType === 1 ? node : node.parentElement);
    if (sec) {
      const sectionEl = sec.closest("[id]");
      if (sectionEl) target.selector.push({
        type: "FragmentSelector", value: sectionEl.id });
    }
    target.selector.push({ type: "TextQuoteSelector", exact: sel.toString() });
    return target;
  }

  function escapeHtml(s) {
    return (s || "").replace(/[&<>"']/g, c =>
      ({ "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;" }[c]));
  }

  function mountToolbar() {
    const t = document.createElement("div");
    t.className = "hx-toolbar";
    t.innerHTML = '<span class="hx-count" id="hx-open-count">0 unresolved</span>';
    addBtn(t, "+ Comment", "", addComment);
    addBtn(t, "Pin file", "primary", pickFile);
    addBtn(t, "Download", "", download);
    document.body.appendChild(t);
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (!document.getElementById("hx-gutter")) {
      const aside = document.createElement("aside");
      aside.className = "hx-gutter"; aside.id = "hx-gutter";
      document.querySelector("main").appendChild(aside);
    }
    mountToolbar();
    paint();
  });
})();
"""

# --- Per-agent templates (industry-shaped per spec §D) ---------------------
# Templates are plain Python string formatters (no Jinja dep). Each
# returns the body HTML; the shell wraps it with the overlay + scaffolding.


def _scout_body(card: DecisionCard, ctx: dict) -> str:
    return f"""
<h2 id="introduction">Introduction</h2>
<div class="hx-section">{_p(card.summary)}</div>

<h2 id="methods">Methods · search strategy</h2>
<div class="hx-section">{_p(', '.join(card.assumptions) or '—')}</div>

<h2 id="results">Results · synthesis · contradictions · gaps</h2>
<div class="hx-section">{_ul(card.key_findings)}</div>

<h2 id="discussion">Discussion</h2>
<div class="hx-section">{_p(card.directive_for_next or '—')}</div>

<h2 id="prisma">PRISMA flow</h2>
<div class="hx-section">{_p('Identified / Screened / Eligible / Included — '
                              'tracked by the agent.')}</div>

<h2 id="references">References</h2>
<div class="hx-section">{_ul(ctx.get('sources') or [])}</div>
"""


def _critic_body(card: DecisionCard, ctx: dict) -> str:
    return f"""
<h2 id="summary">Summary</h2>
<div class="hx-section">{_p(card.summary)}</div>

<h2 id="impact-on-spec">Impact on the spec</h2>
<div class="hx-section">{_p(card.directive_for_next or '—')}</div>

<h2 id="root-causes">Root causes</h2>
<div class="hx-section">{_ul(card.key_findings)}</div>

<h2 id="recommendations">Recommendations</h2>
<div class="hx-section">{_ul(card.open_questions)}</div>

<h2 id="action-items">Action items</h2>
<div class="hx-section">{_ul(card.assumptions)}</div>
"""


def _planner_body(card: DecisionCard, ctx: dict) -> str:
    return f"""
<h2 id="motivation">Motivation</h2>
<div class="hx-section">{_p(card.summary)}</div>

<h2 id="guide-level">Guide-level explanation</h2>
<div class="hx-section">{_p(card.directive_for_next or '—')}</div>

<h2 id="reference-level">Reference-level explanation</h2>
<div class="hx-section">{_ul(card.key_findings)}</div>

<h2 id="drawbacks">Drawbacks</h2>
<div class="hx-section">{_ul(card.open_questions)}</div>

<h2 id="alternatives">Rationale &amp; alternatives</h2>
<div class="hx-section">{_ul(card.assumptions)}</div>

<h2 id="unresolved">Unresolved questions</h2>
<div class="hx-section">{_ul(card.open_questions)}</div>
"""


def _builder_body(card: DecisionCard, ctx: dict) -> str:
    return f"""
<h2 id="context">Context &amp; Problem Statement</h2>
<div class="hx-section">{_p(card.summary)}</div>

<h2 id="decision-drivers">Decision drivers</h2>
<div class="hx-section">{_ul(card.assumptions)}</div>

<h2 id="decision">Decision outcome</h2>
<div class="hx-section">{_p(card.directive_for_next or '—')}</div>

<h2 id="consequences">Consequences</h2>
<div class="hx-section">{_ul(card.key_findings)}</div>

<h2 id="checklist">PR-style checklist</h2>
<div class="hx-section">{_ul([
    'Tests pass', 'Docs updated', 'Self-review done',
    'Links to spec line(s) declared',
])}</div>
"""


def _validator_body(card: DecisionCard, ctx: dict) -> str:
    return f"""
<h2 id="methods">Methods · what was checked</h2>
<div class="hx-section">{_p(card.summary)}</div>

<h2 id="results">Results · per-band pass/fail</h2>
<div class="hx-section">{_ul(card.key_findings)}</div>

<h2 id="hard-flags">Hard flags</h2>
<div class="hx-section">{_ul([f for f in (ctx.get('flags') or []) if str(f).startswith('HARD:')])}</div>

<h2 id="soft-flags">Soft flags</h2>
<div class="hx-section">{_ul([f for f in (ctx.get('flags') or []) if str(f).startswith('SOFT:')])}</div>

<h2 id="artifacts">Pointers to artifacts</h2>
<div class="hx-section">{_ul(card.open_questions)}</div>
"""


def _results_critic_body(card: DecisionCard, ctx: dict) -> str:
    verdict = ctx.get("verdict") or "—"
    return f"""
<h2 id="summary">Summary</h2>
<div class="hx-section">{_p(card.summary)}</div>

<h2 id="impact-on-spec">Impact on the spec</h2>
<div class="hx-section">{_p(card.directive_for_next or '—')}</div>

<h2 id="root-causes">Root causes</h2>
<div class="hx-section">{_ul(card.key_findings)}</div>

<h2 id="went-well">What went well · went wrong</h2>
<div class="hx-section">{_ul(card.assumptions)}</div>

<h2 id="action-items">Action items</h2>
<div class="hx-section">{_ul(card.open_questions)}</div>

<h2 id="verdict">Verdict</h2>
<div class="hx-section"><strong>{html.escape(verdict)}</strong></div>
"""


_TEMPLATES = {
    "scout": _scout_body,
    "critic_methods": _critic_body,
    "scout_critic": _critic_body,  # post-F.6 rename target
    "planner": _planner_body,
    "builder": _builder_body,
    "validator": _validator_body,
    "critic_results": _results_critic_body,
}


# --- Public render API -----------------------------------------------------

@dataclass
class ReportContext:
    """Extra context fed into the renderer beyond the Decision Card."""
    spec_refs: list[str] = field(default_factory=list)
    threads_touched: list[str] = field(default_factory=list)
    verdict: str = ""
    flags: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def render_report(
    card: DecisionCard, stage: str, project: str,
    snapshot_id: str | int | None = None,
    ctx: ReportContext | None = None,
    annotations: list[dict] | None = None,
) -> str:
    """Render a self-contained HTML report for ``stage``.

    The annotations list (W3C Web Annotation Data Model) is embedded as a
    JSON ``<script type="application/json" id="hx-annotations">`` block so
    the overlay JS can read/write it without a sidecar (spec §D-3).
    """
    ctx = ctx or ReportContext()
    body_fn = _TEMPLATES.get(stage, _critic_body)
    body = body_fn(card, ctx.__dict__)
    annotations = annotations or []
    payload = {
        "@context": "http://www.w3.org/ns/anno.jsonld",
        "annotations": annotations,
        "context": {
            "stage": stage, "project": project,
            "snapshot_id": str(snapshot_id) if snapshot_id is not None else None,
            "spec_refs": ctx.spec_refs,
            "threads_touched": ctx.threads_touched,
            "rendered_at": datetime.now(timezone.utc).isoformat(),
            "constitution_present": bool(constitution.load_constitution(project).strip()),
        },
    }
    threads_chip = ""
    if ctx.threads_touched:
        threads_chip = " · threads: " + ", ".join(
            html.escape(t) for t in ctx.threads_touched)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(project)} · {html.escape(stage)}</title>
<style>{_OVERLAY_CSS}</style>
</head>
<body>
<main>
<article>
<h1>{html.escape(project)} · {html.escape(stage)}</h1>
<p class="hx-meta">
  <span class="hx-badge">{html.escape(stage)}</span>
  · snapshot {html.escape(str(snapshot_id) if snapshot_id is not None else '?')}
  · confidence {html.escape(card.confidence or '?')}
  {threads_chip}
</p>
{body}
</article>
<aside class="hx-gutter" id="hx-gutter"></aside>
</main>
<script type="application/json" id="hx-annotations">
{json.dumps(payload, indent=2, default=str)}
</script>
<script>{_OVERLAY_JS}</script>
</body>
</html>
"""


# --- Round-trip parser (read a modified report → structured feedback) -------

@dataclass
class ReportRoundTrip:
    """The structured feedback bundle a re-run receives."""
    kept: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    replies: list[dict] = field(default_factory=list)
    comments: list[dict] = field(default_factory=list)
    send_back: list[dict] = field(default_factory=list)
    context: dict = field(default_factory=dict)


_DATA_RE = re.compile(
    r'<script[^>]*id="hx-annotations"[^>]*>\s*(.*?)\s*</script>',
    re.DOTALL,
)


def parse_round_trip(html_text: str) -> ReportRoundTrip:
    """Extract the embedded annotations JSON and bucket the entries by
    state (kept / rejected / replies / comments / send-back)."""
    m = _DATA_RE.search(html_text or "")
    if not m:
        return ReportRoundTrip()
    try:
        data = json.loads(m.group(1) or "{}")
    except json.JSONDecodeError:
        return ReportRoundTrip()
    out = ReportRoundTrip(context=data.get("context") or {})
    for ann in data.get("annotations") or []:
        state = (ann.get("state") or "open").lower()
        creator = (ann.get("creator") or {}).get("name", "")
        is_researcher = creator == "researcher"
        if state == "send_back":
            out.send_back.append(ann)
        elif state == "rejected":
            out.rejected.append(ann)
        elif is_researcher:
            out.comments.append(ann)
        else:
            # critic notes still open OR accepted = "kept" for the agent's
            # next-pass context (it should NOT reintroduce rejected ones).
            out.kept.append(ann)
        if ann.get("replies"):
            out.replies.extend(ann["replies"])
    return out


def build_send_back_feedback(rt: ReportRoundTrip) -> str:
    """Render the round-trip bundle into the structured feedback string the
    re-run sees as `human_feedback`. Plain, agent-readable text."""
    parts: list[str] = []
    if rt.send_back:
        parts.append("## SEND-BACK ITEMS (the researcher escalated these)")
        for a in rt.send_back:
            parts.append(_anno_line(a))
    if rt.kept:
        parts.append("## STILL-OPEN OR ACCEPTED CRITIC NOTES (address these)")
        for a in rt.kept:
            parts.append(_anno_line(a))
    if rt.rejected:
        parts.append("## REJECTED CRITIC NOTES (do NOT reintroduce — reasons:)")
        for a in rt.rejected:
            reason = ""
            for log in (a.get("log") or []):
                if log.get("action") == "rejected" and log.get("reason"):
                    reason = log["reason"]; break
            parts.append(_anno_line(a) + (f"  · reason: {reason}" if reason else ""))
    if rt.replies:
        parts.append("## RESEARCHER REPLIES ON CRITIC NOTES")
        for r in rt.replies:
            parts.append(f"- {r.get('actor','researcher')}: {r.get('body','')}")
    if rt.comments:
        parts.append("## RESEARCHER COMMENTS / SUGGESTED EDITS")
        for a in rt.comments:
            parts.append(_anno_line(a))
    return "\n".join(parts).strip()


def _anno_line(a: dict) -> str:
    body = ((a.get("body") or {}).get("value") or "").strip()
    target = a.get("target") or {}
    anchor = ""
    for sel in target.get("selector") or []:
        if sel.get("type") == "FragmentSelector":
            anchor = f" @#{sel.get('value','?')}"; break
    return f"- [{a.get('severity','med')}]{anchor}  {body}"


# --- Tiny HTML helpers (no Jinja dep) --------------------------------------

def _p(s: Any) -> str:
    return f"<p>{html.escape(str(s or '—'))}</p>"


def _ul(items: list[Any]) -> str:
    items = [str(x) for x in (items or []) if x is not None and str(x).strip()]
    if not items:
        return "<p>—</p>"
    return "<ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in items) + "</ul>"
