"""Facade — run the pipeline. Used by the CLI, the agent helpers, and tests.

One orchestrator (the plain loop). The MCP server is the drive surface;
this stays as the thin in-process entry point the loop runs behind.
"""

from __future__ import annotations

from pathlib import Path

from .config import ModelConfig, atlas_path
from .core.atlas import Atlas
from .core.plan import Plan
from .core.state import PipelineState
from .orchestrator import loop


def run(
    folder: Path,
    *,
    model_config: ModelConfig | None = None,
    autonomy_until: str = "",
    plan: Plan | None = None,
    research_question: str = "",
    project_name: str = "",
    ask=None,
    interactive: bool | None = None,
    progress_fn=None,
) -> PipelineState:
    atlas = Atlas(atlas_path())
    return loop.run_project(
        folder, atlas, model_config,
        autonomy_until=autonomy_until, plan=plan,
        research_question=research_question, project_name=project_name,
        ask=ask, interactive=interactive, progress_fn=progress_fn,
    )


def resume(
    project: str,
    snapshot_id: str | int,
    *,
    model_config: ModelConfig | None = None,
    start_at: str | None = None,
    autonomy_until: str = "",
    plan: Plan | None = None,
    branch: str = "main",
    ask=None,
    interactive: bool | None = None,
    progress_fn=None,
) -> PipelineState:
    atlas = Atlas(atlas_path())
    return loop.resume_project(
        project, snapshot_id, atlas, model_config,
        start_at=start_at, autonomy_until=autonomy_until, plan=plan,
        branch=branch,
        ask=ask, interactive=interactive, progress_fn=progress_fn,
    )
