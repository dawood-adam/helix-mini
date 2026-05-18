"""Facade — pick an orchestrator and run. Used by the CLI and the agent."""

from __future__ import annotations

from pathlib import Path

from .config import ModelConfig, atlas_path
from .core.atlas import Atlas
from .core.state import PipelineState


def get_runner(engine: str = "loop"):
    """Return the orchestrator module: ``loop`` (default) or ``sdk``."""
    if engine == "sdk":
        from .orchestrator import langgraph_runner

        return langgraph_runner
    from .orchestrator import loop

    return loop


def run(
    folder: Path,
    *,
    model_config: ModelConfig | None = None,
    autonomy_until: str = "",
    research_question: str = "",
    ask=None,
    interactive: bool | None = None,
    progress_fn=None,
    engine: str = "loop",
) -> PipelineState:
    atlas = Atlas(atlas_path())
    return get_runner(engine).run_project(
        folder, atlas, model_config,
        autonomy_until=autonomy_until,
        research_question=research_question,
        ask=ask, interactive=interactive, progress_fn=progress_fn,
    )


def resume(
    project: str,
    snapshot_id: str | int,
    *,
    model_config: ModelConfig | None = None,
    start_at: str | None = None,
    autonomy_until: str = "",
    branch: str = "main",
    ask=None,
    interactive: bool | None = None,
    progress_fn=None,
    engine: str = "loop",
) -> PipelineState:
    atlas = Atlas(atlas_path())
    return get_runner(engine).resume_project(
        project, snapshot_id, atlas, model_config,
        start_at=start_at, autonomy_until=autonomy_until, branch=branch,
        ask=ask, interactive=interactive, progress_fn=progress_fn,
    )
