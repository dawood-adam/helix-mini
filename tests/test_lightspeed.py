"""Tests for lightspeed mode — full pipeline with fake LLM."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from helix_mini.pipeline.agents import Agents
from helix_mini.atlas import Atlas
from helix_mini.config import ModelConfig
from helix_mini.pipeline.state import ForgeState
from helix_mini.pipeline.router import make_autonomy


FAKE_SCOUT_RESPONSE = {
    "source_summaries": [
        {"file": "paper1.md", "summary": "Cardiac modeling with CFD"},
        {"file": "paper2.txt", "summary": "PINNs for cardiac electrophysiology"},
    ],
    "approaches": [
        {
            "id": "approach-1",
            "title": "CFD-based cardiac simulation",
            "description": "Use finite element methods for flow simulation",
            "feasibility": "high",
        },
        {
            "id": "approach-2",
            "title": "PINN hybrid approach",
            "description": "Combine PINNs with traditional FEM",
            "feasibility": "medium",
        },
    ],
    "atlas_writes": [
        {
            "path": "sources/paper1.md",
            "title": "Cardiac Modeling Study",
            "content": "CFD-based cardiac simulation paper.",
            "summary": "Cardiac modeling with computational fluid dynamics",
        },
    ],
}

FAKE_CRITIC_RESPONSE = {
    "critiques": [
        {
            "approach_id": "approach-1",
            "strengths": "Well-established methodology",
            "weaknesses": "Computationally expensive",
            "severity": "info",
            "recommendation": "Proceed with optimization",
        },
    ],
    "recommended_id": "approach-1",
    "atlas_writes": [],
}

FAKE_PLANNER_RESPONSE = {
    "plan": {
        "title": "CFD Cardiac Validation",
        "objective": "Validate CFD approach for cardiac flow",
        "steps": [
            {"step": 1, "action": "Set up mesh", "expected_output": "3D mesh"},
            {"step": 2, "action": "Run simulation", "expected_output": "Flow field"},
        ],
        "success_criteria": ["accuracy > 0.85"],
        "validation_bands": {"accuracy": {"min": 0.8, "max": 1.0}},
    },
    "atlas_writes": [],
}

FAKE_BUILDER_RESPONSE = {
    "artifacts": [
        {
            "name": "simulation.py",
            "type": "code",
            "content": "# CFD simulation code",
            "description": "Main simulation script",
        },
    ],
    "results": [
        {"metric": "accuracy", "value": 0.91, "notes": "Good convergence"},
    ],
    "atlas_writes": [],
}

FAKE_CRITIC_RESULTS_RESPONSE = {
    "assessment": "Strong results with CFD approach",
    "strengths": ["High accuracy", "Good convergence"],
    "weaknesses": ["Limited to simple geometries"],
    "recommendations": ["Extend to complex geometries"],
    "verdict": "ship",
    "atlas_writes": [
        {
            "path": "projects/test-project/overview.md",
            "title": "Test Project Overview",
            "content": "CFD cardiac simulation — shipped with 0.91 accuracy.",
            "summary": "Cardiac CFD project — completed successfully",
        },
    ],
}

# Sequence of responses for the pipeline
FAKE_RESPONSES = [
    FAKE_SCOUT_RESPONSE,
    FAKE_CRITIC_RESPONSE,
    FAKE_PLANNER_RESPONSE,
    FAKE_BUILDER_RESPONSE,
    FAKE_CRITIC_RESULTS_RESPONSE,
]


class TestAgentsWithFakeLLM:
    """Test individual agents with mocked LLM calls."""

    def _make_agents(self, tmp_path: Path) -> tuple[Agents, Atlas]:
        atlas = Atlas(tmp_path / "atlas")
        raw_root = tmp_path / "raw"
        mc = ModelConfig(model="fake/model")
        return Agents(model_config=mc, atlas=atlas, raw_root=raw_root), atlas

    @patch("helix_mini.pipeline.agents.call_llm_json")
    def test_scout(self, mock_llm, tmp_path: Path, sample_folder: Path):
        mock_llm.return_value = (FAKE_SCOUT_RESPONSE, 0.001)
        agents, atlas = self._make_agents(tmp_path)
        state = ForgeState(
            project_name="test",
            input_folder=str(sample_folder),
            research_question="How to model cardiac flow?",
        )

        result = agents.scout(state)
        assert len(result["candidate_approaches"]) == 2
        assert len(result["source_content"]) == 2

        # Check Atlas was written
        index = atlas.read_all_summaries()
        assert "Cardiac Modeling Study" in index

    @patch("helix_mini.pipeline.agents.call_llm_json")
    def test_critic_methods(self, mock_llm, tmp_path: Path):
        mock_llm.return_value = (FAKE_CRITIC_RESPONSE, 0.001)
        agents, _ = self._make_agents(tmp_path)
        state = ForgeState(
            project_name="test",
            candidate_approaches=FAKE_SCOUT_RESPONSE["approaches"],
        )

        result = agents.critic_methods(state)
        assert result["chosen_approach_id"] == "approach-1"
        assert len(result["critiques"]) == 1

    @patch("helix_mini.pipeline.agents.call_llm_json")
    def test_validator_pass(self, mock_llm, tmp_path: Path):
        agents, _ = self._make_agents(tmp_path)
        state = ForgeState(
            project_plan={
                "validation_bands": {"accuracy": {"min": 0.8, "max": 1.0}},
            },
            experiment_results=[
                {"metric": "accuracy", "value": 0.91},
            ],
        )

        result = agents.validator(state)
        assert result["sanity_check_flags"] is None

    @patch("helix_mini.pipeline.agents.call_llm_json")
    def test_validator_fail(self, mock_llm, tmp_path: Path):
        agents, _ = self._make_agents(tmp_path)
        state = ForgeState(
            project_plan={
                "validation_bands": {"accuracy": {"min": 0.8, "max": 1.0}},
            },
            experiment_results=[
                {"metric": "accuracy", "value": 0.3},
            ],
        )

        result = agents.validator(state)
        assert result["sanity_check_flags"] is not None
        assert any("HARD" in f for f in result["sanity_check_flags"])


class TestFullPipeline:
    """Test the full pipeline with fake LLM — simulates lightspeed mode."""

    @patch("helix_mini.pipeline.agents.call_llm_json")
    def test_lightspeed_pipeline(self, mock_llm, tmp_path: Path, sample_folder: Path):
        # Return different responses for each agent call
        mock_llm.side_effect = [(resp, 0.001) for resp in FAKE_RESPONSES]

        from helix_mini.pipeline.runner import run_project

        atlas = Atlas(tmp_path / "atlas")
        model_config = ModelConfig(model="fake/model")

        result = run_project(
            sample_folder,
            atlas,
            model_config,
            lightspeed=True,
            research_question="How to model cardiac flow?",
            home=tmp_path,
        )

        assert result.current_stage == "done"
        assert result.project_name == "test-project"
        assert len(result.completed_stages) > 0
        assert result.cost_so_far > 0

        # Check Atlas has content
        index = atlas.read_all_summaries()
        assert len(index) > len("# Atlas Index\n")
