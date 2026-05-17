"""Tests for the Forge workflow pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from helix_mini.atlas import Atlas
from helix_mini.config import ModelConfig
from helix_mini.pipeline.router import gate_decision, make_autonomy, sanity_route
from helix_mini.pipeline.state import ForgeState
from helix_mini.pipeline.decisions import append_decision, render_decisions_md
from helix_mini.pipeline.snapshots import mint_snapshot, list_snapshots


class TestRouter:
    def test_auto_gate_proceeds(self):
        state = ForgeState(autonomy={"gate_scope": "auto"}, critiques=[])
        assert gate_decision(state, "gate_scope") == "proceed"

    def test_blocking_critique_forces_revise(self):
        state = ForgeState(
            autonomy={"gate_scope": "auto"},
            critiques=[{"severity": "blocking", "message": "fatal flaw"}],
        )
        assert gate_decision(state, "gate_scope") == "revise"

    def test_non_blocking_auto_proceeds(self):
        state = ForgeState(
            autonomy={"gate_scope": "auto"},
            critiques=[{"severity": "warning", "message": "minor issue"}],
        )
        assert gate_decision(state, "gate_scope") == "proceed"

    def test_always_ask_with_no_fn_proceeds(self):
        state = ForgeState(autonomy={"gate_scope": "always_ask"}, critiques=[])
        assert gate_decision(state, "gate_scope") == "proceed"

    def test_make_autonomy_lightspeed(self):
        auto = make_autonomy(lightspeed=True)
        assert all(v == "auto" for v in auto.values())

    def test_make_autonomy_normal(self):
        auto = make_autonomy(lightspeed=False)
        assert all(v == "always_ask" for v in auto.values())


class TestSanityRoute:
    def test_no_flags_passes(self):
        state = ForgeState(sanity_check_flags=None)
        assert sanity_route(state) == "pass"

    def test_empty_flags_passes(self):
        state = ForgeState(sanity_check_flags=[])
        assert sanity_route(state) == "pass"

    def test_hard_flag_fails(self):
        state = ForgeState(sanity_check_flags=["HARD: accuracy=0.1 outside [0.5, 1.0]"])
        assert sanity_route(state) == "fail"

    def test_soft_flag_passes(self):
        state = ForgeState(sanity_check_flags=["SOFT: metric has non-numeric value"])
        assert sanity_route(state) == "pass"


class TestDecisions:
    def test_append_and_render(self, tmp_path: Path):
        dp = tmp_path / "decisions.json"
        append_decision(dp, "scout", "found 3 approaches", "analyzed sources")
        append_decision(dp, "gate_scope", "proceed", "auto-approved")

        md = render_decisions_md(dp)
        assert "scout" in md
        assert "found 3 approaches" in md
        assert "gate_scope" in md

    def test_render_missing_file(self, tmp_path: Path):
        md = render_decisions_md(tmp_path / "nonexistent.json")
        assert "No decisions" in md


class TestSnapshots:
    def test_mint_and_list(self, tmp_path: Path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        state = ForgeState(project_name="test", current_stage="scout")

        snap1 = mint_snapshot(state, project_dir)
        assert snap1.exists()

        state.current_stage = "planner"
        snap2 = mint_snapshot(state, project_dir)

        snaps = list_snapshots(project_dir)
        assert len(snaps) == 2


class TestForgeState:
    def test_defaults(self):
        s = ForgeState()
        assert s.project_name == ""
        assert s.cost_so_far == 0.0
        assert s.candidate_approaches == []
        assert s.current_stage == "start"

    def test_custom_values(self):
        s = ForgeState(project_name="cardiac", cost_cap=10.0)
        assert s.project_name == "cardiac"
        assert s.cost_cap == 10.0
