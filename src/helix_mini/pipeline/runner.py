"""Pipeline execution — single project and parallel runners."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..atlas import Atlas
from ..config import HELIX_HOME, ModelConfig
from .agents import Agents
from .graph import GRAPH_NODES, CostCapExceeded, build_graph
from .router import make_autonomy
from .state import ForgeState, GraphState, to_state

log = logging.getLogger(__name__)


def _execute(
    *,
    agents: Agents,
    home: Path,
    ask_fn,
    progress_fn,
    initial_state: GraphState,
    start_at: str,
    max_iterations: int,
) -> ForgeState:
    """Compile + invoke the graph from ``start_at`` with ``initial_state``.

    Shared core for both a fresh run and a snapshot resume.
    """
    graph = build_graph(
        agents, home=home, ask_fn=ask_fn, progress_fn=progress_fn,
        start_at=start_at,
    )
    compiled = graph.compile()
    pname = initial_state.get("project_name", "")
    # Headroom for the bounded builder<->critic_results refine loop
    # (~6 nodes per extra iteration on top of the ~12-node linear path).
    recursion_limit = 30 + max_iterations * 8
    try:
        final_state = compiled.invoke(
            initial_state, {"recursion_limit": recursion_limit}
        )
    except CostCapExceeded as e:
        log.warning("Pipeline stopped: %s", e)
        return ForgeState(
            project_name=pname, error=str(e), current_stage="error",
            cost_so_far=initial_state.get("cost_so_far", 0.0),
        )

    log.info("Completed %s — cost: $%.4f", pname, final_state.get("cost_so_far", 0))
    return to_state(final_state)


def run_project(
    folder: Path,
    atlas: Atlas,
    model_config: ModelConfig,
    lightspeed: bool = False,
    research_question: str = "",
    ask_fn=None,
    home: Path | None = None,
    progress_fn=None,
    max_iterations: int = 3,
) -> ForgeState:
    """Run the full Forge pipeline on a single folder."""
    home = home or HELIX_HOME
    project_name = folder.stem

    agents = Agents(model_config=model_config, atlas=atlas, raw_root=home / "raw")
    initial_state: GraphState = {
        "project_name": project_name,
        "research_question": research_question,
        "input_folder": str(folder.resolve()),
        "autonomy": make_autonomy(lightspeed),
        "source_content": [],
        "candidate_approaches": [],
        "chosen_approach_id": None,
        "chosen_approach": {},
        "project_plan": {},
        "code_artifacts": [],
        "experiment_results": [],
        "sanity_check_flags": None,
        "critiques": [],
        "next_action": "",
        "verdict": "",
        "build_iterations": 0,
        "max_iterations": max_iterations,
        "cost_so_far": 0.0,
        "cost_cap": 5.0,
        "call_cap": model_config.call_cap(),
        "current_stage": "start",
        "completed_stages": [],
        "error": None,
    }

    log.info("Starting Forge pipeline for: %s", project_name)
    return _execute(
        agents=agents, home=home, ask_fn=ask_fn, progress_fn=progress_fn,
        initial_state=initial_state, start_at="scout",
        max_iterations=max_iterations,
    )


def resume_project(
    project_name: str,
    atlas: Atlas,
    model_config: ModelConfig,
    *,
    snapshot_state: dict,
    start_at: str,
    lightspeed: bool = False,
    ask_fn=None,
    home: Path | None = None,
    progress_fn=None,
    max_iterations: int = 3,
) -> ForgeState:
    """Resume a project from a saved snapshot, re-entering the graph at
    ``start_at`` (any pipeline node) with the snapshot's full ForgeState.

    Cost/history carry forward (like git); the run controls (autonomy,
    max_iterations, call_cap) are refreshed for this resumed run.
    """
    home = home or HELIX_HOME
    if start_at not in GRAPH_NODES:
        raise ValueError(
            f"Unknown resume stage '{start_at}'. One of: {', '.join(GRAPH_NODES)}"
        )

    agents = Agents(model_config=model_config, atlas=atlas, raw_root=home / "raw")
    initial_state: GraphState = dict(snapshot_state)
    initial_state["project_name"] = project_name
    initial_state["autonomy"] = make_autonomy(lightspeed)
    initial_state["max_iterations"] = max_iterations
    initial_state["call_cap"] = model_config.call_cap()
    initial_state["error"] = None
    initial_state["current_stage"] = start_at

    log.info("Resuming %s at '%s' from snapshot", project_name, start_at)
    return _execute(
        agents=agents, home=home, ask_fn=ask_fn, progress_fn=progress_fn,
        initial_state=initial_state, start_at=start_at,
        max_iterations=max_iterations,
    )


async def run_parallel(
    folders: list[Path],
    atlas: Atlas,
    model_config: ModelConfig,
    lightspeed: bool = False,
    research_question: str = "",
    home: Path | None = None,
    progress_fn=None,
    max_iterations: int = 3,
) -> list[ForgeState]:
    """Run multiple Forge pipelines in parallel, sharing one Atlas."""
    loop = asyncio.get_event_loop()
    home = home or HELIX_HOME

    async def _run(folder: Path) -> ForgeState:
        return await loop.run_in_executor(
            None,
            lambda: run_project(
                folder, atlas, model_config,
                lightspeed=lightspeed,
                research_question=research_question,
                home=home,
                progress_fn=progress_fn,
                max_iterations=max_iterations,
            ),
        )

    tasks = [_run(f) for f in folders]
    return await asyncio.gather(*tasks)
