"""Builder artifact-writing sandbox + the bounded builder⇄critic_results loop."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from helix_mini.atlas import Atlas
from helix_mini.config import ModelConfig
from helix_mini.pipeline.router import iterate_decision
from helix_mini.pipeline.state import ForgeState
from helix_mini.sandbox import SandboxError, _validate_artifact_name, sanitize_code_artifacts


class TestArtifactSandbox:
    def test_valid_nested_artifact(self, tmp_path: Path):
        out = sanitize_code_artifacts(
            [{"name": "src/sim.py", "content": "print(1)"}], tmp_path
        )
        assert len(out) == 1
        path, content = out[0]
        assert path == (tmp_path / "src/sim.py").resolve()
        assert path.resolve().is_relative_to(tmp_path.resolve())
        assert content == "print(1)"

    def test_absolute_path_blocked(self, tmp_path: Path):
        for bad in ("/etc/passwd", "\\\\evil", "C:\\x"):
            try:
                _validate_artifact_name(bad, tmp_path)
                assert False, f"{bad} should be blocked"
            except SandboxError:
                pass

    def test_traversal_blocked(self, tmp_path: Path):
        for bad in ("../escape.py", "a/../../b.py", "..", "foo/../../etc/x"):
            try:
                _validate_artifact_name(bad, tmp_path)
                assert False, f"{bad} should be blocked"
            except SandboxError:
                pass

    def test_traversal_artifact_skipped_not_raised(self, tmp_path: Path):
        # sanitize_* skips bad entries (logs) rather than raising.
        out = sanitize_code_artifacts(
            [
                {"name": "../evil.sh", "content": "rm -rf ~"},
                {"name": "ok.py", "content": "ok"},
            ],
            tmp_path,
        )
        assert [p.name for p, _ in out] == ["ok.py"]

    def test_oversize_content_truncated(self, tmp_path: Path):
        big = "x" * 600_000
        out = sanitize_code_artifacts([{"name": "big.txt", "content": big}], tmp_path)
        assert len(out[0][1]) < len(big)
        assert "truncated by sandbox" in out[0][1]

    def test_missing_or_nondict_skipped(self, tmp_path: Path):
        out = sanitize_code_artifacts(
            ["nope", {"name": "x"}, {"content": "y"}, {"name": "k.py", "content": "v"}],
            tmp_path,
        )
        assert [p.name for p, _ in out] == ["k.py"]


class TestIterateDecision:
    def _s(self, **kw):
        return ForgeState(**kw)

    def test_iterate_under_cap(self):
        assert iterate_decision(
            self._s(verdict="iterate", build_iterations=1, max_iterations=3)
        ) == "iterate"

    def test_iterate_at_cap_stops(self):
        assert iterate_decision(
            self._s(verdict="iterate", build_iterations=3, max_iterations=3)
        ) == "stop"

    def test_ship_and_abandon_stop(self):
        assert iterate_decision(self._s(verdict="ship")) == "stop"
        assert iterate_decision(self._s(verdict="abandon")) == "stop"
        assert iterate_decision(self._s(verdict="")) == "stop"


SCOUT = {"source_summaries": [], "approaches": [{"id": "approach-1", "title": "A"}],
         "atlas_writes": []}
CRITIC_M = {"critiques": [], "recommended_id": "approach-1", "atlas_writes": []}
PLAN = {"plan": {"title": "P", "steps": [{"step": 1}], "validation_bands": {}},
        "atlas_writes": []}
BUILD = {"artifacts": [{"name": "src/sim.py", "type": "code",
                         "content": "# gen", "description": "d"}],
         "results": [], "atlas_writes": []}


def _run(tmp_path, critic_seq, max_iterations):
    """Drive the full pipeline; critic_seq is the verdict per critic_results."""
    folder = tmp_path / "Proj"
    folder.mkdir()
    (folder / "a.md").write_text("# source")
    calls = {"critic": 0}

    def fake(**kw):
        sysmsg = kw.get("system", "")
        if "research scout" in sysmsg:
            return SCOUT, 0.001
        if "methods critic" in sysmsg:
            return CRITIC_M, 0.001
        if "research planner" in sysmsg:
            return PLAN, 0.001
        if "research builder" in sysmsg:
            return BUILD, 0.001
        if "results critic" in sysmsg:
            i = calls["critic"]
            calls["critic"] += 1
            verdict = critic_seq[min(i, len(critic_seq) - 1)]
            return {"assessment": "x", "recommendations": ["fix it"],
                    "verdict": verdict, "atlas_writes": []}, 0.001
        raise AssertionError("unexpected system prompt")

    from helix_mini.pipeline.runner import run_project

    with patch("helix_mini.pipeline.agents.call_llm_json", side_effect=fake):
        result = run_project(
            folder, Atlas(tmp_path / "atlas"), ModelConfig(model="fake/model"),
            lightspeed=True, home=tmp_path, max_iterations=max_iterations,
        )
    return result, folder


class TestRefineLoopEndToEnd:
    def test_ship_first_pass_no_loop(self, tmp_path: Path):
        result, _ = _run(tmp_path, ["ship"], max_iterations=3)
        assert result.current_stage == "done"
        assert result.completed_stages.count("builder") == 1
        # artifact written to the sandboxed project dir
        art = tmp_path / "atlas/projects/Proj/artifacts/src/sim.py"
        assert art.read_text() == "# gen"

    def test_iterate_then_ship(self, tmp_path: Path):
        result, _ = _run(tmp_path, ["iterate", "iterate", "ship"], max_iterations=5)
        # builder ran: initial + 2 refine loops = 3
        assert result.completed_stages.count("builder") == 3
        assert result.build_iterations == 2
        assert result.current_stage == "done"

    def test_loop_is_bounded_by_max_iterations(self, tmp_path: Path):
        # critic always says iterate; cap must stop it.
        result, _ = _run(tmp_path, ["iterate"], max_iterations=2)
        assert result.build_iterations == 2
        assert result.completed_stages.count("builder") == 3  # initial + 2
        assert result.current_stage == "done"
