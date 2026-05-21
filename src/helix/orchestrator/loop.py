"""The orchestrator — the one runner over the core.

Wires the core together: run stage → snapshot → gate (HITL / autonomy) →
transition. Unbounded cycling is safe because the only bound is a configurable
token/call ceiling that *pauses* (resumable) instead of failing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import ModelConfig, atlas_path, project_root
from ..core.agents import AgentCtx, llm_stages
from ..core.atlas import Atlas
from ..core.decisions import append_decision, save_decisions_md
from ..core.gates import decide_gate, record_feedback
from ..core.plan import Plan
from ..core.snapshots import mint_snapshot, resume_state
from ..core.stages import run_stage
from ..core.state import PipelineState
from ..core.transitions import END, next_stage, stages
from ..io import ClientUnavailable, Declined, NeedsModel
from ..llm import parse_json_text, use_responder

log = logging.getLogger(__name__)


def _project_dir(atlas: Atlas, project: str) -> Path:
    d = atlas.root / "projects" / project
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_report(state, atlas: Atlas, project: str, stage: str,
                  snapshot_id, result) -> None:
    """Workstream D: write the stage's self-contained HTML report.

    One canonical file per stage (overwritten on each (re-)run); the
    annotation overlay lives inside the same file (W3C Web Annotation
    Data Model — spec §D-3). Stale annotations from a prior run are
    already captured into the next-run feedback by
    ``hx_report_send_back`` before re-rendering, so it's safe to
    overwrite here."""
    from ..core import reports as _reports

    reports_dir = _project_dir(atlas, project) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    flags = state.sanity_check_flags or []
    rctx = _reports.ReportContext(
        verdict=state.verdict or "",
        flags=[str(f) for f in flags] if flags else [],
        threads_touched=[],   # Workstream E will populate
        spec_refs=[],         # Workstream F will populate
    )
    html_str = _reports.render_report(
        result.card, stage, project,
        snapshot_id=snapshot_id, ctx=rctx, annotations=[],
    )
    (reports_dir / f"{stage}.html").write_text(html_str)


def _decisions_path(atlas: Atlas, project: str) -> Path:
    return _project_dir(atlas, project) / ".decisions.json"


def _budget_exceeded(state: PipelineState) -> str | None:
    if state.token_cap and state.tokens_used >= state.token_cap:
        return f"~{state.tokens_used} tokens >= cap {state.token_cap}"
    if state.call_cap:
        used = sum(1 for st in state.completed_stages if st in llm_stages())
        if used >= state.call_cap:
            return f"LLM calls {used} >= cap {state.call_cap}"
    return None


def make_ctx(atlas: Atlas, model_config: ModelConfig) -> AgentCtx:
    return AgentCtx(
        atlas=atlas,
        model_config=model_config,
        raw_root=atlas.root.parent / "raw",
        project_dir=project_root(),
    )


def advance(
    state: PipelineState,
    ctx: AgentCtx,
    atlas: Atlas,
    current: str,
    last_id: str | None,
    *,
    ask=None,
    interactive: bool = False,
    plan: Plan | None = None,
    branch: str = "main",
) -> tuple[str | None, str | None]:
    """Execute one stage: run → bookkeep → snapshot → gate → next.

    Returns ``(next_stage_or_END, last_snapshot_id)``; ``next_stage`` is
    ``None`` when the run must stop on a stage error.
    """
    project = state.project_name
    result = run_stage(current, state, ctx)
    if result.error:
        state.error = result.error
        state.current_stage = "error"
        mint_snapshot(state, project, stage=current,
                      report={"decision": "error", "rationale": result.error},
                      parent=last_id, branch=branch)
        return None, last_id

    for k, v in result.updates.items():
        if hasattr(state, k):
            setattr(state, k, v)
    state.tokens_used += result.tokens
    state.current_stage = current
    state.completed_stages.append(current)  # append-only execution trace

    record = append_decision(
        _decisions_path(atlas, project), current,
        result.decision, result.rationale,
    )
    meta = mint_snapshot(
        state, project, stage=current, report=record, card=result.card,
        parent=last_id, branch=branch,
    )

    # Workstream D: emit / overwrite the per-stage HTML report (latest only;
    # history lives in the snapshot DAG). Best-effort — a renderer failure
    # never breaks a run, just logs and skips.
    try:
        _write_report(state, atlas, project, current, meta["id"], result)
    except Exception as e:  # noqa: BLE001 - non-fatal by design
        log.warning("report renderer failed for %s: %s", current, e)

    gate = decide_gate(
        state, current, result.decision, result.rationale,
        ask=ask, interactive=interactive, plan=plan,
    )
    nxt = next_stage(current, gate)
    if nxt == "builder" and "builder" in state.completed_stages:
        state.build_iterations += 1
    # Workstream H — rediscover loop. After Results Critic in
    # ``autonomy_until: "rediscover"`` mode, restart from Scout with the
    # hypothesis thread carried forward; capped at H.REDISCOVER_CAP.
    if nxt == END and current == "critic_results":
        from .. import core
        from ..core import hypothesis as _hyp

        if plan is not None and _hyp.should_loop_again(state, plan):
            nxt = "scout"
            log.info("rediscover: looping from critic_results → scout "
                     "(iteration %d of %d)",
                     _hyp.iterations_so_far(state), _hyp.REDISCOVER_CAP)
    return nxt, meta["id"]


def _run(
    state: PipelineState,
    atlas: Atlas,
    model_config: ModelConfig,
    *,
    start_at: str,
    ask=None,
    interactive: bool | None = None,
    plan: Plan | None = None,
    progress_fn=None,
    branch: str = "main",
    parent: str | None = None,
) -> PipelineState:
    interactive = bool(ask) if interactive is None else interactive
    plan = plan or Plan()
    ctx = make_ctx(atlas, model_config)
    project = state.project_name
    current = start_at
    last_id = parent
    injected: set[str] = set()  # plan directives already threaded as feedback

    while current != END:
        reason = _budget_exceeded(state)
        if reason:
            if interactive and ask:
                gd = ask(_ceiling_report(current, reason, state))
                if gd.action == "stop":
                    state.next_action = "paused-budget"
                    return state
                state.token_cap *= 2  # "raise the ceiling and continue"
            else:
                state.next_action = "paused-budget"
                mint_snapshot(state, project, stage=current,
                              report={"decision": "paused", "rationale": reason},
                              parent=last_id, branch=branch)
                log.warning("Paused (%s) — resumable", reason)
                return state

        if progress_fn:
            progress_fn(current, project, state.tokens_used)

        directive = plan.directive_for(current)
        if directive and current not in injected:
            record_feedback(state, "plan", current, directive)
            injected.add(current)

        try:
            nxt, last_id = advance(
                state, ctx, atlas, current, last_id,
                ask=ask, interactive=interactive, plan=plan, branch=branch,
            )
        except Declined:
            # Standardized: user declined a gate elicitation. The completed
            # stage's snapshot already exists (advance mints it before the
            # gate), so the run is resumable from there — same contract as
            # the cost-ceiling pause.
            state.next_action = "paused-input"
            log.info("Paused (user declined elicitation) — resumable")
            return state
        except ClientUnavailable as e:
            # The seam died at the gate (after the stage's snapshot was
            # minted). Backstop for the stage-path conversion in run_stage:
            # represent it like a stage error so it reports legibly and the
            # existing stage snapshot makes it resumable — never an opaque
            # crash that loses the run.
            state.error = str(e)
            state.current_stage = "error"
            log.warning("Stopped (MCP client unavailable) — resumable")
            return state
        if nxt is None:
            return state
        current = nxt

    save_decisions_md(_project_dir(atlas, project), _decisions_path(atlas, project))
    return state


def _ceiling_report(stage: str, reason: str, state: PipelineState):
    from ..core.gates import GateReport

    return GateReport(
        stage="budget-ceiling", decision=f"ceiling reached before {stage}",
        rationale=reason, summary={"tokens": state.tokens_used},
        note="continue doubles the ceiling; stop pauses (resumable)",
    )


def run_project(
    folder: Path,
    atlas: Atlas | None = None,
    model_config: ModelConfig | None = None,
    *,
    autonomy_until: str = "",
    plan: Plan | None = None,
    research_question: str = "",
    project_name: str = "",
    ask=None,
    interactive: bool | None = None,
    progress_fn=None,
) -> PipelineState:
    from ..config import token_cap

    atlas = atlas or Atlas(atlas_path())
    model_config = model_config or ModelConfig()
    state = PipelineState(
        project_name=project_name or folder.stem,
        research_question=research_question,
        input_folder=str(folder.resolve()),
        token_cap=token_cap(),
        call_cap=model_config.call_cap(),
    )
    log.info("Starting pipeline: %s", state.project_name)
    return _run(
        state, atlas, model_config, start_at=stages()[0],
        ask=ask, interactive=interactive,
        plan=plan or Plan.from_autonomy_until(autonomy_until),
        progress_fn=progress_fn,
    )


def resume_project(
    project: str,
    snapshot_id: str | int,
    atlas: Atlas | None = None,
    model_config: ModelConfig | None = None,
    *,
    start_at: str | None = None,
    autonomy_until: str = "",
    plan: Plan | None = None,
    branch: str = "main",
    ask=None,
    interactive: bool | None = None,
    progress_fn=None,
) -> PipelineState:
    from ..core.snapshots import load_snapshot, resume_state

    atlas = atlas or Atlas(atlas_path())
    model_config = model_config or ModelConfig()
    snap = load_snapshot(project, snapshot_id)
    if snap is None:
        raise ValueError(f"No snapshot {snapshot_id} for project '{project}'")
    state = resume_state(project, snapshot_id)
    assert state is not None
    state.project_name = project
    state.error = None
    state.next_action = ""
    state.call_cap = model_config.call_cap() or state.call_cap
    stage = start_at or snap.get("stage") or "scout"
    if stage not in stages():
        raise ValueError(f"Unknown stage '{stage}'. One of: {', '.join(stages())}")
    log.info("Resuming %s at '%s' from snap-%s", project, stage, snapshot_id)
    return _run(
        state, atlas, model_config, start_at=stage,
        ask=ask, interactive=interactive,
        plan=plan or Plan.from_autonomy_until(autonomy_until),
        progress_fn=progress_fn, branch=branch, parent=str(snapshot_id),
    )


# --- Agent-driven stepping --------------------------------------------------
#
# Same `advance`, same `next_stage`, same snapshot DAG — only the model
# acquisition differs. `_advance_loop` runs deterministic stages straight
# through and *suspends* at the first LLM stage (the render responder raises
# NeedsModel before any snapshot/Atlas write). The client agent answers; a
# submit re-enters from the prior snapshot with that answer injected, then
# the loop continues to the next suspension or END. The autonomous `_run`
# loop above is untouched.


@dataclass
class StepOutcome:
    kind: str  # "needs_model" | "done" | "paused" | "error"
    state: PipelineState
    last_id: str | None
    stage: str = ""   # needs_model: the suspended stage
    system: str = ""  # needs_model: pinned prompt shown to the agent
    user: str = ""    # needs_model: pinned prompt shown to the agent


def _render_responder(stage: str):
    def _r(model: str, system: str, user: str):
        raise NeedsModel(stage, system, user)
    return _r


def _inject_responder(answer):
    def _r(model: str, system: str, user: str):
        parsed = answer if isinstance(answer, (dict, list)) \
            else parse_json_text(str(answer))
        tokens = (len(system) + len(user)
                  + len(json.dumps(parsed, default=str))) // 4
        return parsed, int(tokens)
    return _r


def _advance_loop(
    state: PipelineState, ctx: AgentCtx, atlas: Atlas, current: str,
    last_id: str | None, *, ask, plan: Plan, branch: str, inject=None,
) -> StepOutcome:
    project = state.project_name
    first = True
    while current != END:
        reason = _budget_exceeded(state)
        if reason:
            state.next_action = "paused-budget"
            mint_snapshot(state, project, stage=current,
                          report={"decision": "paused", "rationale": reason},
                          parent=last_id, branch=branch)
            log.warning("Paused (%s) — resumable", reason)
            return StepOutcome("paused", state, last_id)

        responder = inject if (first and inject is not None) \
            else _render_responder(current)
        try:
            with use_responder(responder):
                nxt, last_id = advance(
                    state, ctx, atlas, current, last_id,
                    ask=ask, interactive=True, plan=plan, branch=branch)
        except NeedsModel as nm:
            # Suspended before any mutation: prior snapshot is the resume
            # point, the pinned prompt goes to the client agent.
            return StepOutcome("needs_model", state, last_id,
                               stage=nm.stage, system=nm.system, user=nm.user)
        except Declined:
            state.next_action = "paused-input"
            log.info("Paused (user declined gate) — resumable")
            return StepOutcome("paused", state, last_id)
        except ClientUnavailable as e:
            state.error = str(e)
            state.current_stage = "error"
            return StepOutcome("error", state, last_id)
        first = False
        if nxt is None:  # advance minted an error/decline snapshot and stopped
            return StepOutcome(
                "error" if state.error else "paused", state, last_id)
        current = nxt

    save_decisions_md(_project_dir(atlas, project),
                      _decisions_path(atlas, project))
    return StepOutcome("done", state, last_id)


def step_begin(
    state: PipelineState, atlas: Atlas, model_config: ModelConfig | None,
    *, last_id: str | None, ask=None, plan: Plan | None = None,
    branch: str = "main",
) -> StepOutcome:
    """Advance a fresh run to its first model suspension (or END)."""
    ctx = make_ctx(atlas, model_config or ModelConfig())
    return _advance_loop(
        state, ctx, atlas, stages()[0], last_id,
        ask=ask, plan=plan or Plan(), branch=branch)


def submit_stage(
    project: str, resume_from: str, stage: str, answer,
    atlas: Atlas, model_config: ModelConfig | None,
    *, ask=None, plan: Plan | None = None, branch: str = "main",
) -> StepOutcome:
    """Inject the client agent's answer for ``stage`` (re-entering from the
    prior snapshot) and advance to the next suspension or END."""
    state = resume_state(project, resume_from)
    if state is None:
        raise ValueError(f"No snapshot {resume_from} for project '{project}'")
    state.error = None
    state.next_action = ""
    ctx = make_ctx(atlas, model_config or ModelConfig())
    return _advance_loop(
        state, ctx, atlas, stage, resume_from,
        ask=ask, plan=plan or Plan(), branch=branch,
        inject=_inject_responder(answer))


def resume_step(
    project: str, resume_from: str, start_at: str,
    atlas: Atlas, model_config: ModelConfig | None,
    *, ask=None, plan: Plan | None = None, branch: str = "main",
) -> StepOutcome:
    """Rehydrate ``resume_from`` and advance (no injected answer) to the next
    model suspension or END — re-entering an existing run at ``start_at``."""
    state = resume_state(project, resume_from)
    if state is None:
        raise ValueError(f"No snapshot {resume_from} for project '{project}'")
    if start_at not in stages():
        raise ValueError(
            f"Unknown stage '{start_at}'. One of: {', '.join(stages())}")
    state.error = None
    state.next_action = ""
    ctx = make_ctx(atlas, model_config or ModelConfig())
    return _advance_loop(
        state, ctx, atlas, start_at, resume_from,
        ask=ask, plan=plan or Plan(), branch=branch)
