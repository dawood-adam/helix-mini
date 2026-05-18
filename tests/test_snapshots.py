"""Snapshot helpers, git-style CLI, resume-from-snapshot, and agent tools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from helix_mini.pipeline.snapshots import (
    _snap_num,
    diff_snapshots,
    find_snapshot,
    list_snapshots,
    load_snapshot,
    mint_snapshot,
    snapshot_gitgraph,
    snapshot_summary,
)
from helix_mini.pipeline.state import ForgeState


def _mint(pdir: Path, **kw) -> Path:
    return mint_snapshot(ForgeState(**kw), pdir)


class TestSnapshotHelpers:
    def test_numeric_ordering_and_find(self, tmp_path: Path):
        for i in range(1, 12):  # 1..11 — lexical sort would put 10,11 before 2
            _mint(tmp_path, current_stage=f"s{i}", project_name="p")
        snaps = list_snapshots(tmp_path)
        assert [_snap_num(p) for p in snaps] == list(range(1, 12))
        assert find_snapshot(tmp_path, 11) is not None
        assert find_snapshot(tmp_path, 99) is None

    def test_summary(self, tmp_path: Path):
        p = _mint(tmp_path, current_stage="builder", verdict="iterate",
                  build_iterations=2, cost_so_far=0.5,
                  code_artifacts=[{"name": "a"}], candidate_approaches=[{}, {}])
        s = snapshot_summary(load_snapshot(p))
        assert s["stage"] == "builder" and s["verdict"] == "iterate"
        assert s["build_iterations"] == 2 and s["cost"] == 0.5
        assert s["artifacts"] == 1 and s["approaches"] == 2

    def test_diff_scalar_and_list(self, tmp_path: Path):
        a = load_snapshot(_mint(tmp_path, current_stage="planner",
                                build_iterations=0, code_artifacts=[]))
        b = load_snapshot(_mint(tmp_path, current_stage="builder",
                                build_iterations=1,
                                code_artifacts=[{"name": "x"}]))
        d = diff_snapshots(a, b)
        assert d["current_stage"] == ("planner", "builder")
        assert d["build_iterations"] == (0, 1)
        assert d["code_artifacts"] == ("0 items", "1 items")

    def test_diff_no_changes(self, tmp_path: Path):
        a = load_snapshot(_mint(tmp_path, current_stage="scout"))
        b = load_snapshot(_mint(tmp_path, current_stage="scout"))
        assert diff_snapshots(a, b) == {}

    def test_gitgraph_is_standard_mermaid(self, tmp_path: Path):
        _mint(tmp_path, current_stage="scout", cost_so_far=0.01)
        _mint(tmp_path, current_stage="builder", cost_so_far=0.05,
              verdict="iterate")
        g = snapshot_gitgraph([load_snapshot(p) for p in list_snapshots(tmp_path)])
        assert g.startswith("```mermaid\ngitGraph")
        assert g.count("commit id:") == 2
        assert "[iterate]" in g
        assert g.strip().endswith("```")

    def test_gitgraph_empty(self):
        g = snapshot_gitgraph([])
        assert "gitGraph" in g and "no snapshots yet" in g


# --- resume_project end-to-end (fake LLM) -------------------------------------

SCOUT = {"source_summaries": [], "approaches": [{"id": "approach-1"}],
         "atlas_writes": []}
CRITIC_M = {"critiques": [], "recommended_id": "approach-1", "atlas_writes": []}
PLAN = {"plan": {"title": "P", "steps": [{"step": 1}], "validation_bands": {}},
        "atlas_writes": []}
BUILD = {"artifacts": [{"name": "src/a.py", "content": "# x"}], "results": [],
         "atlas_writes": []}
CRITIC_R = {"recommendations": ["ok"], "verdict": "ship", "atlas_writes": []}


def _fake(**kw):
    s = kw.get("system", "")
    if "research scout" in s:
        return SCOUT, 0.0
    if "methods critic" in s:
        return CRITIC_M, 0.0
    if "research planner" in s:
        return PLAN, 0.0
    if "research builder" in s:
        return BUILD, 0.0
    if "results critic" in s:
        return CRITIC_R, 0.0
    raise AssertionError("unexpected prompt")


class TestResume:
    def test_resume_reenters_at_chosen_stage(self, tmp_path: Path):
        from helix_mini.atlas import Atlas
        from helix_mini.config import ModelConfig
        from helix_mini.pipeline.runner import resume_project

        # A snapshot's full state, as if captured mid-run after planning.
        snap_state = ForgeState(
            project_name="Proj", input_folder=str(tmp_path),
            project_plan={"title": "P", "validation_bands": {}},
            chosen_approach={"id": "approach-1"}, current_stage="planner",
        ).__dict__

        with patch("helix_mini.pipeline.agents.call_llm_json", side_effect=_fake):
            r = resume_project(
                "Proj", Atlas(tmp_path / "atlas"),
                ModelConfig(model="fake/model"),
                snapshot_state=dict(snap_state), start_at="builder",
                lightspeed=True, home=tmp_path,
            )
        assert r.current_stage == "done"
        assert "builder" in r.completed_stages
        assert "scout" not in r.completed_stages  # did NOT restart from scratch

    def test_resume_rejects_unknown_stage(self, tmp_path: Path):
        from helix_mini.atlas import Atlas
        from helix_mini.config import ModelConfig
        from helix_mini.pipeline.runner import resume_project

        with pytest.raises(ValueError, match="Unknown resume stage"):
            resume_project(
                "Proj", Atlas(tmp_path / "atlas"),
                ModelConfig(model="fake/model"),
                snapshot_state=ForgeState(project_name="Proj").__dict__,
                start_at="not_a_node", home=tmp_path,
            )


class TestSnapshotsCli:
    def _seed(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr("helix_mini.cli.HELIX_HOME", tmp_path)
        pdir = tmp_path / "atlas" / "projects" / "Proj"
        _mint(pdir, current_stage="scout", cost_so_far=0.01, project_name="Proj")
        _mint(pdir, current_stage="builder", cost_so_far=0.05,
              verdict="iterate", project_name="Proj")
        return pdir

    def test_list_and_diagram(self, monkeypatch, tmp_path: Path):
        from click.testing import CliRunner

        from helix_mini.cli import cli

        pdir = self._seed(monkeypatch, tmp_path)
        out = CliRunner().invoke(cli, ["snapshots", "list", "Proj"])
        assert out.exit_code == 0
        assert "snap-1" in out.output and "snap-2" in out.output

        d = CliRunner().invoke(cli, ["snapshots", "diagram", "Proj"])
        assert d.exit_code == 0
        assert "gitGraph" in d.output
        assert (pdir / "timeline.md").exists()

    def test_diff_and_show(self, monkeypatch, tmp_path: Path):
        from click.testing import CliRunner

        from helix_mini.cli import cli

        self._seed(monkeypatch, tmp_path)
        diff = CliRunner().invoke(cli, ["snapshots", "diff", "Proj", "1", "2"])
        assert diff.exit_code == 0 and "current_stage" in diff.output
        show = CliRunner().invoke(cli, ["snapshots", "show", "Proj", "2"])
        assert show.exit_code == 0 and "builder" in show.output

    def test_missing_snapshot_errors(self, monkeypatch, tmp_path: Path):
        from click.testing import CliRunner

        from helix_mini.cli import cli

        self._seed(monkeypatch, tmp_path)
        r = CliRunner().invoke(cli, ["snapshots", "show", "Proj", "99"])
        assert r.exit_code != 0


class TestAgentSnapshotTools:
    def test_resume_is_gated_reads_are_not(self):
        from helix_mini.agent_sdk import _GATED_TOOLS, run_permission_decision

        assert "resume_pipeline" in _GATED_TOOLS
        ok, _ = run_permission_decision(
            "mcp__helix__snapshot_list", interactive=False)
        assert ok is True
        ok, reason = run_permission_decision(
            "mcp__helix__resume_pipeline", interactive=False)
        assert ok is False and "non-interactive" in reason
        ok, _ = run_permission_decision(
            "mcp__helix__resume_pipeline", interactive=True,
            approver=lambda: True)
        assert ok is True

    def test_snapshot_text_helpers(self, tmp_path: Path):
        from helix_mini.agent_sdk import (
            snapshot_list_text, snapshot_timeline_text,
        )

        assert "No snapshots" in snapshot_list_text("Proj", home=tmp_path)
        _mint(tmp_path / "atlas" / "projects" / "Proj",
              current_stage="scout", project_name="Proj")
        assert "snap-1" in snapshot_list_text("Proj", home=tmp_path)
        assert "gitGraph" in snapshot_timeline_text("Proj", home=tmp_path)
