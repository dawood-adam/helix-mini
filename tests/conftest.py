"""Shared fixtures: an isolated repo-local project + a fake LLM."""

from __future__ import annotations

import pytest


@pytest.fixture
def project(tmp_path, monkeypatch):
    """An isolated project whose source folder *is* its workspace root.

    A run self-roots at its source folder (config.use_root), so the folder
    and HELIX_HOME are the same directory here — the intended
    one-folder-per-workspace model, and what keeps read-back tools
    (resolved via HELIX_HOME) consistent with what the run wrote."""
    src = tmp_path / "src-papers"
    src.mkdir()
    monkeypatch.setenv("HELIX_HOME", str(src))
    (src / "paper.md").write_text("# Paper\nCFD cardiac simulation findings.")
    (src / "helix.toml").write_text(
        '[atlas]\npath = "atlas"\n\n[limits]\ntoken_cap = 0\ncall_cap = 0\n'
    )
    return src


FAKE = {
    "scout": ({
        "source_summaries": [{"file": "paper.md", "summary": "cfd"}],
        "approaches": [
            {"id": "approach-1", "title": "A1", "description": "d", "feasibility": "high"},
            {"id": "approach-2", "title": "A2", "description": "d", "feasibility": "low"},
        ],
        "atlas_writes": [
            {"path": "sources/paper.md", "title": "Paper", "content": "c", "summary": "s"}
        ],
    }, 0.01),
    "methods critic": ({
        "critiques": [{"approach_id": "approach-1", "strengths": "x",
                       "weaknesses": "y", "severity": "info", "recommendation": "go"}],
        "recommended_id": "approach-1", "atlas_writes": [],
    }, 0.02),
    "research planner": ({
        "plan": {"title": "Plan", "objective": "o",
                 "steps": [{"step": 1, "action": "a", "expected_output": "e"}],
                 "success_criteria": ["c"],
                 "validation_bands": {"acc": {"min": 0.0, "max": 1.0}}},
        "atlas_writes": [{"path": "projects/src-papers/plan.md", "title": "Plan",
                          "content": "c", "summary": "s"}],
    }, 0.03),
    "research builder": ({
        "artifacts": [{"name": "src/sim.py", "type": "code",
                       "content": "print('ok')\n", "description": "sim"}],
        "results": [{"metric": "acc", "value": 0.9, "notes": "ok"}],
        "atlas_writes": [],
    }, 0.04),
    "results critic": ({
        "assessment": "good", "strengths": ["s"], "weaknesses": [],
        "recommendations": ["r"], "verdict": "ship",
        "atlas_writes": [{"path": "projects/src-papers/overview.md",
                          "title": "O", "content": "c", "summary": "s"}],
    }, 0.05),
}


@pytest.fixture
def fake_llm(monkeypatch):
    """Patch the LLM chokepoint; route by agent system-prompt keyword."""
    calls = {"n": 0}

    def fake(*, model, system, user, **kw):
        calls["n"] += 1
        for key, resp in FAKE.items():
            if key in system:
                return resp
        return ({"raw": "?"}, 0.0)

    monkeypatch.setattr("helix.core.agents.call_llm_json", fake)
    return calls
