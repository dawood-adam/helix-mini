"""Pipeline execution — single project and parallel runners."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..atlas import Atlas
from ..config import HELIX_HOME, ModelConfig
from .agents import Agents
from .graph import CostCapExceeded, build_graph
from .router import make_autonomy
from .state import ForgeState, GraphState, to_state

log = logging.getLogger(__name__)


def run_project(
    folder: Path,
    atlas: Atlas,
    model_config: ModelConfig,
    lightspeed: bool = False,
    research_question: str = "",
    ask_fn=None,
    home: Path | None = None,
    progress_fn=None,
) -> ForgeState:
    """Run the full Forge pipeline on a single folder."""
    home = home or HELIX_HOME
    project_name = folder.stem
    raw_root = home / "raw"

    agents = Agents(model_config=model_config, atlas=atlas, raw_root=raw_root)
    graph = build_graph(agents, home=home, ask_fn=ask_fn, progress_fn=progress_fn)
    compiled = graph.compile()

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
        "cost_so_far": 0.0,
        "cost_cap": 5.0,
        "call_cap": model_config.call_cap(),
        "current_stage": "start",
        "completed_stages": [],
        "error": None,
    }

    log.info("Starting Forge pipeline for: %s", project_name)
    try:
        final_state = compiled.invoke(initial_state)
    except CostCapExceeded as e:
        log.warning("Pipeline stopped: %s", e)
        return ForgeState(
            project_name=project_name,
            error=str(e),
            current_stage="error",
            cost_so_far=initial_state["cost_so_far"],
        )

    log.info(
        "Completed %s — cost: $%.4f",
        project_name,
        final_state.get("cost_so_far", 0),
    )

    return to_state(final_state)


async def run_parallel(
    folders: list[Path],
    atlas: Atlas,
    model_config: ModelConfig,
    lightspeed: bool = False,
    research_question: str = "",
    home: Path | None = None,
    progress_fn=None,
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
            ),
        )

    tasks = [_run(f) for f in folders]
    return await asyncio.gather(*tasks)
