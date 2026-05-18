"""Markdown-defined agents.

Each stage is a markdown file (YAML frontmatter + system-prompt body) in
``helix/builtin_agents/``; a project may override any of them with
``<project>/agents/<stage>.md`` (no code change — Risk B/F).

Per-stage *context assembly* and *response mapping* stay in Python because
they are genuinely data-dependent; the markdown owns the role, the prompt, the
output contract, and the Atlas-write policy. ``kind: deterministic`` agents
(validator) dispatch to a registered function and never call an LLM (Risk H).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml

from ..llm import call_llm_json
from ..sandbox import sanitize_atlas_writes, sanitize_code_artifacts
from .atlas import Atlas, Page
from .ingest import ingest_folder
from .state import PipelineState


class AgentInputError(Exception):
    """Stage cannot run on the current state (becomes state.error)."""


@dataclass
class Agent:
    name: str
    order: int
    kind: str  # "llm" | "deterministic"
    model_stage: str
    atlas_write: bool
    snapshot: str
    system: str


@dataclass
class AgentCtx:
    atlas: Atlas
    model_config: object  # ModelConfig (duck-typed: .model_for_stage)
    raw_root: Path
    project_dir: Path  # where per-project agent overrides + artifacts live

    def artifacts_dir(self, project_name: str) -> Path:
        return self.atlas.root / "projects" / project_name / "artifacts"


def _parse_md(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        return yaml.safe_load(fm) or {}, body.strip()
    return {}, text.strip()


def _builtin_text(stage: str) -> str | None:
    try:
        return (resources.files("helix.builtin_agents") / f"{stage}.md").read_text()
    except (FileNotFoundError, ModuleNotFoundError):
        return None


def load_agent(stage: str, project_dir: Path | None = None) -> Agent:
    """Load ``stage``'s agent. A project override wins over the builtin."""
    text = None
    if project_dir is not None:
        override = project_dir / "agents" / f"{stage}.md"
        if override.exists():
            text = override.read_text()
    if text is None:
        text = _builtin_text(stage)
    if text is None:
        raise AgentInputError(f"No agent definition for stage '{stage}'")
    fm, body = _parse_md(text)
    return Agent(
        name=fm.get("name", stage),
        order=int(fm.get("order", 0)),
        kind=fm.get("kind", "llm"),
        model_stage=fm.get("model_stage", stage),
        atlas_write=bool(fm.get("atlas_write", True)),
        snapshot=fm.get("snapshot", "after"),
        system=body,
    )


def _all_builtin_agents() -> list[Agent]:
    out = []
    for entry in resources.files("helix.builtin_agents").iterdir():
        if entry.name.endswith(".md"):
            fm, body = _parse_md(entry.read_text())
            out.append(load_agent(fm.get("name", entry.name[:-3])))
    return sorted(out, key=lambda a: a.order)


def stage_order() -> list[str]:
    """Pipeline stage order, derived from agent frontmatter (Risk F)."""
    return [a.name for a in _all_builtin_agents()]


def llm_stages() -> set[str]:
    return {a.name for a in _all_builtin_agents() if a.kind == "llm"}


# --- Prompt-context formatting ---------------------------------------------


def _format_sources(pages: list[Page]) -> str:
    return "\n\n".join(
        f"### {p.title}\n```\n{p.content[:8000]}\n```" for p in pages
    )


def _format_pages(pages: list[Page]) -> str:
    return "\n\n".join(f"### {p.title}\n{p.content}" for p in pages)


def _feedback_block(state: PipelineState, stage: str) -> str:
    notes = state.feedback_for(stage)
    if not notes:
        return ""
    return "\n\n## Human feedback — address this on this pass\n" + "\n".join(
        f"- {n}" for n in notes
    )


# --- Per-stage context builders (state -> user prompt) ----------------------


def _ctx_scout(s: PipelineState, c: AgentCtx) -> str:
    sources = ingest_folder(Path(s.input_folder), c.raw_root)
    if not sources:
        raise AgentInputError("No readable files found in input folder")
    return (
        f"## Existing Atlas Knowledge\n{c.atlas.read_all_summaries()}\n\n"
        f"## New Sources ({len(sources)} files)\n{_format_sources(sources)}\n\n"
        f"Research question: {s.research_question or 'General analysis of these sources'}"
        + _feedback_block(s, "scout")
    )


def _ctx_critic_methods(s: PipelineState, c: AgentCtx) -> str:
    return (
        f"## Atlas Context\n{_format_pages(c.atlas.read(s.project_name))}\n\n"
        f"## Candidate Approaches\n{json.dumps(s.candidate_approaches, indent=2)}"
        + _feedback_block(s, "critic_methods")
    )


def _ctx_planner(s: PipelineState, c: AgentCtx) -> str:
    q = f"{s.project_name} {s.chosen_approach.get('title', '')}"
    return (
        f"## Atlas Context\n{_format_pages(c.atlas.read(q))}\n\n"
        f"## Chosen Approach\n{json.dumps(s.chosen_approach, indent=2)}\n\n"
        f"## Project: {s.project_name}\n"
        f"Research question: {s.research_question or 'General analysis'}"
        + _feedback_block(s, "planner")
    )


def _ctx_builder(s: PipelineState, c: AgentCtx) -> str:
    user = (
        f"## Atlas Context\n{_format_pages(c.atlas.read(f'implementation {s.project_name}'))}\n\n"
        f"## Plan\n{json.dumps(s.project_plan, indent=2)}\n\n"
        f"## Approach\n{json.dumps(s.chosen_approach, indent=2)}"
    )
    if s.build_iterations > 0 or s.code_artifacts:
        prior = [
            {"name": a.get("name"), "description": a.get("description"),
             "content": (a.get("content") or "")[:4000]}
            for a in s.code_artifacts
        ]
        user += (
            f"\n\n## REVISION pass {s.build_iterations} — improve these artifacts\n"
            f"### Prior artifacts\n{json.dumps(prior, indent=2)}\n"
            f"### Reviewer feedback\n{json.dumps(s.critiques, indent=2)}\n"
            f"### Validator flags\n{s.sanity_check_flags or 'None'}"
        )
    return user + _feedback_block(s, "builder")


def _ctx_critic_results(s: PipelineState, c: AgentCtx) -> str:
    return (
        f"## Atlas Context\n{_format_pages(c.atlas.read(f'results {s.project_name}'))}\n\n"
        f"## Approach\n{json.dumps(s.chosen_approach, indent=2)}\n\n"
        f"## Plan\n{json.dumps(s.project_plan, indent=2)}\n\n"
        f"## Results\n{json.dumps(s.experiment_results, indent=2)}\n\n"
        f"## Artifacts\n{json.dumps([a.get('description', '') for a in s.code_artifacts], indent=2)}\n\n"
        f"## Sanity Flags\n{s.sanity_check_flags or 'None'}"
        + _feedback_block(s, "critic_results")
    )


# --- Per-stage response mappers (LLM JSON -> state updates) ------------------


def _map_scout(r: dict, s: PipelineState, c: AgentCtx) -> dict:
    return {
        "source_content": r.get("source_summaries", []),
        "candidate_approaches": r.get("approaches", []),
    }


def _map_critic_methods(r: dict, s: PipelineState, c: AgentCtx) -> dict:
    chosen = r.get("recommended_id") or (
        s.candidate_approaches[0]["id"] if s.candidate_approaches else None
    )
    return {
        "critiques": r.get("critiques", []),
        "chosen_approach_id": chosen,
        "chosen_approach": next(
            (a for a in s.candidate_approaches if a.get("id") == chosen),
            s.candidate_approaches[0] if s.candidate_approaches else {},
        ),
    }


def _map_planner(r: dict, s: PipelineState, c: AgentCtx) -> dict:
    return {"project_plan": r.get("plan", {})}


def _map_builder(r: dict, s: PipelineState, c: AgentCtx) -> dict:
    root = c.artifacts_dir(s.project_name)
    written: list[str] = []
    clean: list[dict] = []
    # Sanitize once; state stores ONLY validated names so a traversal name can
    # never be persisted into a snapshot and replayed by restore/resume.
    for a in sanitize_code_artifacts(r.get("artifacts", []), root):
        a["path"].parent.mkdir(parents=True, exist_ok=True)
        a["path"].write_text(a["content"])
        written.append(a["name"])
        clean.append({
            "name": a["name"], "type": a["type"],
            "description": a["description"], "content": a["content"],
        })
    return {
        "code_artifacts": clean,
        "experiment_results": r.get("results", []),
        "artifact_files": written,
    }


def _map_critic_results(r: dict, s: PipelineState, c: AgentCtx) -> dict:
    return {
        "critiques": r.get("recommendations", []),
        "verdict": r.get("verdict", "ship"),
    }


def _deterministic_validator(s: PipelineState, c: AgentCtx) -> dict:
    bands = s.project_plan.get("validation_bands", {})
    flags: list[str] = []
    for result in s.experiment_results:
        metric, value = result.get("metric", ""), result.get("value")
        if metric in bands and value is not None:
            band = bands[metric]
            try:
                val = float(value)
                lo = float(band.get("min", float("-inf")))
                hi = float(band.get("max", float("inf")))
                if val < lo or val > hi:
                    flags.append(f"HARD: {metric}={val} outside band [{lo}, {hi}]")
            except (TypeError, ValueError):
                flags.append(f"SOFT: {metric} has non-numeric value: {value}")
    return {"sanity_check_flags": flags or None}


_CONTEXT = {
    "scout": _ctx_scout,
    "critic_methods": _ctx_critic_methods,
    "planner": _ctx_planner,
    "builder": _ctx_builder,
    "critic_results": _ctx_critic_results,
}
_MAP = {
    "scout": _map_scout,
    "critic_methods": _map_critic_methods,
    "planner": _map_planner,
    "builder": _map_builder,
    "critic_results": _map_critic_results,
}
_DETERMINISTIC = {"validator": _deterministic_validator}


def run_agent(stage: str, state: PipelineState, ctx: AgentCtx) -> tuple[dict, float]:
    """Run one stage's agent. Returns ``(state_updates, cost)``.

    Deterministic agents cost 0.0 and never touch the LLM.
    """
    agent = load_agent(stage, ctx.project_dir)
    if agent.kind == "deterministic":
        fn = _DETERMINISTIC.get(stage)
        if fn is None:
            raise AgentInputError(f"No deterministic impl registered for '{stage}'")
        return fn(state, ctx), 0.0

    try:
        user = _CONTEXT[stage](state, ctx)
    except AgentInputError as e:
        return {"error": str(e)}, 0.0

    model = ctx.model_config.model_for_stage(agent.model_stage)
    resp, cost = call_llm_json(model=model, system=agent.system, user=user)
    if agent.atlas_write:
        writes = sanitize_atlas_writes(resp.get("atlas_writes", []), ctx.atlas.root)
        if writes:
            ctx.atlas.write(writes, f"{stage} | {state.project_name}")
    return _MAP[stage](resp, state, ctx), cost
