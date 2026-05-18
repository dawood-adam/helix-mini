"""LangGraph orchestrator — the ``helix[sdk]`` extra.

Each stage is a node that delegates to ``loop.advance`` (the same shared step
the plain loop uses), so the two runners cannot diverge on routing or
snapshots (Risk A). Arbitrary back-jumps use a full conditional-edge map, so
no minimum ``Command`` support is required. ``langgraph`` is imported lazily
so ``helix.core`` stays dependency-light.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path

from ..config import ModelConfig, atlas_path, call_cap_default, cost_cap, project_root
from ..core.atlas import Atlas
from ..core.decisions import save_decisions_md
from ..core.state import PipelineState, to_state
from ..core.transitions import END, stages
from .loop import _cost_exceeded, _decisions_path, _project_dir, advance, make_ctx

log = logging.getLogger(__name__)


def _require_langgraph():
    try:
        from langgraph.graph import StateGraph  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "The LangGraph orchestrator needs the sdk extra: "
            "pip install 'helix[sdk]'"
        ) from e


def build_graph(
    atlas: Atlas,
    model_config: ModelConfig,
    *,
    start_at: str,
    ask=None,
    interactive: bool = False,
    branch: str = "main",
):
    _require_langgraph()
    from langgraph.graph import END as LG_END
    from langgraph.graph import StateGraph

    from ..core.state import GraphState

    ctx = make_ctx(atlas, model_config)
    order = list(stages())

    def make_node(stage: str):
        def node(state: dict) -> dict:
            s = to_state(state)
            if _cost_exceeded(s):
                s.next_action = "paused-cost"
                return {**asdict(s), "_next": END, "_last_id": state.get("_last_id")}
            nxt, last_id = advance(
                s, ctx, atlas, stage, state.get("_last_id"),
                ask=ask, interactive=interactive, branch=branch,
            )
            out = asdict(s)
            out["_next"] = nxt or END
            out["_last_id"] = last_id
            return out

        return node

    graph = StateGraph(GraphState)
    for st in order:
        graph.add_node(st, make_node(st))
    graph.set_entry_point(start_at)
    # Router returns a stage name or our "END" string; map "END" -> the
    # LangGraph END sentinel so arbitrary back-jumps + termination both work.
    target_map = {st: st for st in order}
    target_map[END] = LG_END
    for st in order:
        graph.add_conditional_edges(st, lambda s: s.get("_next") or END, target_map)
    return graph


def _invoke(state: PipelineState, atlas, model_config, *, start_at, ask,
            interactive, branch, parent) -> PipelineState:
    graph = build_graph(
        atlas, model_config, start_at=start_at, ask=ask,
        interactive=interactive, branch=branch,
    )
    compiled = graph.compile()
    init = asdict(state)
    init["_last_id"] = parent
    final = compiled.invoke(init, {"recursion_limit": 500})
    s = to_state(final)
    if not s.error and s.next_action != "paused-cost":
        save_decisions_md(
            _project_dir(atlas, s.project_name),
            _decisions_path(atlas, s.project_name),
        )
    return s


def run_project(
    folder: Path,
    atlas: Atlas | None = None,
    model_config: ModelConfig | None = None,
    *,
    autonomy_until: str = "",
    research_question: str = "",
    ask=None,
    interactive: bool | None = None,
    progress_fn=None,
) -> PipelineState:
    atlas = atlas or Atlas(atlas_path())
    model_config = model_config or ModelConfig.cli("claude")
    state = PipelineState(
        project_name=folder.stem,
        research_question=research_question,
        input_folder=str(folder.resolve()),
        autonomy_until=autonomy_until,
        cost_cap=cost_cap(),
        call_cap=model_config.call_cap() or (
            call_cap_default() if model_config.model.startswith("cli/") else 0
        ),
    )
    return _invoke(
        state, atlas, model_config, start_at=stages()[0],
        ask=ask, interactive=bool(ask) if interactive is None else interactive,
        branch="main", parent=None,
    )


def resume_project(
    project: str,
    snapshot_id: str | int,
    atlas: Atlas | None = None,
    model_config: ModelConfig | None = None,
    *,
    start_at: str | None = None,
    autonomy_until: str = "",
    branch: str = "main",
    ask=None,
    interactive: bool | None = None,
    progress_fn=None,
) -> PipelineState:
    from ..core.snapshots import load_snapshot, resume_state

    atlas = atlas or Atlas(atlas_path())
    model_config = model_config or ModelConfig.cli("claude")
    snap = load_snapshot(project, snapshot_id)
    if snap is None:
        raise ValueError(f"No snapshot {snapshot_id} for project '{project}'")
    state = resume_state(project, snapshot_id)
    assert state is not None
    state.project_name = project
    state.autonomy_until = autonomy_until
    state.error = None
    state.next_action = ""
    stage = start_at or snap.get("stage") or "scout"
    if stage not in stages():
        raise ValueError(f"Unknown stage '{stage}'. One of: {', '.join(stages())}")
    return _invoke(
        state, atlas, model_config, start_at=stage,
        ask=ask, interactive=bool(ask) if interactive is None else interactive,
        branch=branch, parent=str(snapshot_id),
    )
