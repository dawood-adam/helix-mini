"""LLM-backed agent bodies — each reads from Atlas, calls LLM, writes to Atlas."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..atlas import Atlas, Page, ingest_folder
from ..config import ModelConfig
from ..llm import call_llm_json
from ..sandbox import sanitize_atlas_writes, sanitize_code_artifacts
from .state import ForgeState

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def _format_sources(pages: list[Page]) -> str:
    parts = []
    for p in pages:
        content = p.content[:8000] if len(p.content) > 8000 else p.content
        parts.append(f"### {p.title}\n```\n{content}\n```")
    return "\n\n".join(parts)


def _format_pages(pages: list[Page]) -> str:
    return "\n\n".join(f"### {p.title}\n{p.content}" for p in pages)


# --- System prompts (extracted for readability) ---

SCOUT_PROMPT = (
    "You are a research scout. Analyze the provided source files and "
    "existing knowledge base. Your job:\n"
    "1. Summarize each source file\n"
    "2. Identify 2-3 candidate research approaches\n"
    "3. Identify key concepts and entities that emerge\n\n"
    "Respond with JSON:\n"
    "{\n"
    '  "source_summaries": [{"file": "...", "summary": "..."}],\n'
    '  "approaches": [\n'
    '    {"id": "approach-1", "title": "...", "description": "...", '
    '"feasibility": "high|medium|low"}\n'
    "  ],\n"
    '  "atlas_writes": [\n'
    '    {"path": "sources/filename.md", "title": "...", '
    '"content": "...", "summary": "one-line"}\n'
    "  ]\n"
    "}"
)

CRITIC_METHODS_PROMPT = (
    "You are a methods critic. Evaluate the candidate research approaches "
    "for feasibility, novelty, and potential issues.\n\n"
    "Respond with JSON:\n"
    "{\n"
    '  "critiques": [\n'
    '    {"approach_id": "...", "strengths": "...", "weaknesses": "...", '
    '"severity": "info|warning|blocking", "recommendation": "..."}\n'
    "  ],\n"
    '  "recommended_id": "approach-N",\n'
    '  "atlas_writes": []\n'
    "}"
)

PLANNER_PROMPT = (
    "You are a research planner. Design a concrete validation plan for "
    "the chosen approach. Include specific steps, expected outputs, and "
    "success criteria.\n\n"
    "Respond with JSON:\n"
    "{\n"
    '  "plan": {\n'
    '    "title": "...",\n'
    '    "objective": "...",\n'
    '    "steps": [{"step": 1, "action": "...", "expected_output": "..."}],\n'
    '    "success_criteria": ["..."],\n'
    '    "validation_bands": {"metric": {"min": 0, "max": 1}}\n'
    "  },\n"
    '  "atlas_writes": [\n'
    '    {"path": "projects/PROJECT/plan.md", "title": "...", '
    '"content": "...", "summary": "..."}\n'
    "  ]\n"
    "}"
)

BUILDER_PROMPT = (
    "You are a research builder. Implement the validation plan by "
    "writing real, runnable code / analysis scripts / structured outputs. "
    "Each artifact's `name` is a relative file path (e.g. `src/sim.py`, "
    "`analysis/eval.py`) written into the project's artifacts/ directory — "
    "no absolute paths, no `..`. Put the full file contents in `content`.\n"
    "If prior artifacts and reviewer feedback are provided below, you are "
    "ITERATING: return improved versions of the same files that address the "
    "feedback (reuse the same `name`s), not a fresh from-scratch design.\n\n"
    "Respond with JSON:\n"
    "{\n"
    '  "artifacts": [\n'
    '    {"name": "src/example.py", "type": "code|analysis|data", '
    '"content": "...", "description": "..."}\n'
    "  ],\n"
    '  "results": [\n'
    '    {"metric": "...", "value": ..., "notes": "..."}\n'
    "  ],\n"
    '  "atlas_writes": []\n'
    "}"
)

CRITIC_RESULTS_PROMPT = (
    "You are a results critic. Evaluate the experiment results, "
    "identify strengths and weaknesses, and summarize findings.\n\n"
    "Respond with JSON:\n"
    "{\n"
    '  "assessment": "...",\n'
    '  "strengths": ["..."],\n'
    '  "weaknesses": ["..."],\n'
    '  "recommendations": ["..."],\n'
    '  "verdict": "ship|iterate|abandon",\n'
    '  "atlas_writes": [\n'
    '    {"path": "projects/PROJECT/overview.md", "title": "...", '
    '"content": "...", "summary": "..."}\n'
    "  ]\n"
    "}"
)


class Agents:
    def __init__(self, model_config: ModelConfig, atlas: Atlas, raw_root: Path):
        self.model_config = model_config
        self.atlas = atlas
        self.raw_root = raw_root

    def _model(self, stage: str) -> str:
        """Get the model for a given pipeline stage."""
        return self.model_config.model_for_stage(stage)

    def _call_and_write(
        self, stage: str, system: str, user: str, project_name: str,
    ) -> tuple[dict, float]:
        """Common pattern: call LLM, validate and write Atlas pages."""
        resp, cost = call_llm_json(model=self._model(stage), system=system, user=user)
        writes = sanitize_atlas_writes(resp.get("atlas_writes", []), self.atlas.root)
        if writes:
            self.atlas.write(writes, f"{stage} | {project_name}")
        return resp, cost

    def scout(self, state: ForgeState) -> dict:
        """Ingest folder, identify approaches, write source pages to Atlas."""
        sources = ingest_folder(Path(state.input_folder), self.raw_root)
        if not sources:
            return {"error": "No readable files found in input folder"}

        existing = self.atlas.read_all_summaries()
        resp, cost = self._call_and_write(
            "scout",
            SCOUT_PROMPT,
            (
                f"## Existing Atlas Knowledge\n{existing}\n\n"
                f"## New Sources ({len(sources)} files)\n"
                f"{_format_sources(sources)}\n\n"
                f"Research question: {state.research_question or 'General analysis of these sources'}"
            ),
            state.project_name,
        )

        return {
            "source_content": resp.get("source_summaries", []),
            "candidate_approaches": resp.get("approaches", []),
            "cost": cost,
        }

    def critic_methods(self, state: ForgeState) -> dict:
        """Evaluate candidate approaches for feasibility."""
        context = self.atlas.read(state.project_name)
        resp, cost = self._call_and_write(
            "critic_methods",
            CRITIC_METHODS_PROMPT,
            (
                f"## Atlas Context\n{_format_pages(context)}\n\n"
                f"## Candidate Approaches\n{json.dumps(state.candidate_approaches, indent=2)}"
            ),
            state.project_name,
        )

        critiques = resp.get("critiques", [])
        recommended = resp.get("recommended_id")
        chosen = recommended or (
            state.candidate_approaches[0]["id"]
            if state.candidate_approaches
            else None
        )

        return {
            "critiques": critiques,
            "chosen_approach_id": chosen,
            "chosen_approach": next(
                (a for a in state.candidate_approaches if a.get("id") == chosen),
                state.candidate_approaches[0] if state.candidate_approaches else {},
            ),
            "cost": cost,
        }

    def planner(self, state: ForgeState) -> dict:
        """Design a validation plan for the chosen approach."""
        context = self.atlas.read(
            f"{state.project_name} {state.chosen_approach.get('title', '')}"
        )
        resp, cost = self._call_and_write(
            "planner",
            PLANNER_PROMPT,
            (
                f"## Atlas Context\n{_format_pages(context)}\n\n"
                f"## Chosen Approach\n{json.dumps(state.chosen_approach, indent=2)}\n\n"
                f"## Project: {state.project_name}\n"
                f"Research question: {state.research_question or 'General analysis'}"
            ),
            state.project_name,
        )

        return {"project_plan": resp.get("plan", {}), "cost": cost}

    def _artifacts_dir(self, project_name: str) -> Path:
        return self.atlas.root / "projects" / project_name / "artifacts"

    def builder(self, state: ForgeState) -> dict:
        """Build code artifacts, write them (sandboxed) to the project dir.

        On a refine iteration (build_iterations > 0) the prior artifacts and
        reviewer feedback are fed back so the model improves the code in place.
        """
        context = self.atlas.read(f"implementation {state.project_name}")
        user = (
            f"## Atlas Context\n{_format_pages(context)}\n\n"
            f"## Plan\n{json.dumps(state.project_plan, indent=2)}\n\n"
            f"## Approach\n{json.dumps(state.chosen_approach, indent=2)}"
        )
        if state.build_iterations > 0:
            prior = [
                {"name": a.get("name"), "description": a.get("description"),
                 "content": (a.get("content") or "")[:4000]}
                for a in state.code_artifacts
            ]
            user += (
                f"\n\n## REVISION pass {state.build_iterations}/"
                f"{state.max_iterations} — improve these artifacts\n"
                f"### Prior artifacts\n{json.dumps(prior, indent=2)}\n"
                f"### Reviewer feedback\n{json.dumps(state.critiques, indent=2)}\n"
                f"### Validator flags\n{state.sanity_check_flags or 'None'}"
            )

        resp, cost = self._call_and_write(
            "builder", BUILDER_PROMPT, user, state.project_name,
        )

        artifacts = resp.get("artifacts", [])
        written: list[str] = []
        if artifacts:
            root = self._artifacts_dir(state.project_name)
            for abs_path, content in sanitize_code_artifacts(artifacts, root):
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                abs_path.write_text(content)
                written.append(str(abs_path.relative_to(root)))
            if written:
                log.info(
                    "[%s] builder wrote %d file(s) to %s",
                    state.project_name, len(written), root,
                )

        return {
            "code_artifacts": artifacts,
            "experiment_results": resp.get("results", []),
            "artifact_files": written,
            "cost": cost,
        }

    def validator(self, state: ForgeState) -> dict:
        """Deterministic: check results against plan validation bands."""
        bands = state.project_plan.get("validation_bands", {})
        flags: list[str] = []

        for result in state.experiment_results:
            metric = result.get("metric", "")
            value = result.get("value")
            if metric in bands and value is not None:
                band = bands[metric]
                try:
                    val = float(value)
                    lo = float(band.get("min", float("-inf")))
                    hi = float(band.get("max", float("inf")))
                    if val < lo or val > hi:
                        flags.append(
                            f"HARD: {metric}={val} outside band [{lo}, {hi}]"
                        )
                except (TypeError, ValueError):
                    flags.append(f"SOFT: {metric} has non-numeric value: {value}")

        return {"sanity_check_flags": flags if flags else None, "cost": 0.0}

    def critic_results(self, state: ForgeState) -> dict:
        """Final critique of results and overall findings."""
        context = self.atlas.read(f"results {state.project_name}")
        resp, cost = self._call_and_write(
            "critic_results",
            CRITIC_RESULTS_PROMPT,
            (
                f"## Atlas Context\n{_format_pages(context)}\n\n"
                f"## Approach\n{json.dumps(state.chosen_approach, indent=2)}\n\n"
                f"## Plan\n{json.dumps(state.project_plan, indent=2)}\n\n"
                f"## Results\n{json.dumps(state.experiment_results, indent=2)}\n\n"
                f"## Artifacts\n{json.dumps([a.get('description', '') for a in state.code_artifacts], indent=2)}\n\n"
                f"## Sanity Flags\n{state.sanity_check_flags or 'None'}"
            ),
            state.project_name,
        )

        return {
            "critiques": resp.get("recommendations", []),
            "verdict": resp.get("verdict", "ship"),
            "cost": cost,
        }
