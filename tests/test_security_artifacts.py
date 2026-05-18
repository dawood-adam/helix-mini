"""Regression: builder artifact names cannot traverse out of the project.

Covers the path-traversal / arbitrary-file-write fix:
1. Root cause — `_map_builder` persists only sanitized names, so a malicious
   name never reaches a snapshot.
2. Defense in depth — `restore_artifacts` re-validates names, so even a
   hand-crafted / legacy snapshot cannot escape `dest`.
"""

from __future__ import annotations

from helix.core.agents import AgentCtx, _map_builder
from helix.core.atlas import Atlas
from helix.core.snapshots import mint_snapshot, restore_artifacts
from helix.core.state import PipelineState


def test_map_builder_drops_traversal_names(tmp_path):
    ctx = AgentCtx(
        atlas=Atlas(tmp_path / "atlas"),
        model_config=None,
        raw_root=tmp_path / "raw",
        project_dir=tmp_path,
    )
    state = PipelineState(project_name="p")
    resp = {
        "artifacts": [
            {"name": "../../../../PWNED.txt", "type": "code",
             "content": "PWNED", "description": "traversal"},
            {"name": str(tmp_path / "ABS_PWNED.txt"), "type": "code",
             "content": "PWNED", "description": "absolute"},
            {"name": "src/ok.py", "type": "code",
             "content": "print(1)\n", "description": "good"},
        ],
        "results": [],
    }

    out = _map_builder(resp, state, ctx)

    # Only the safe artifact survives, with a safe relative name.
    assert [a["name"] for a in out["code_artifacts"]] == ["src/ok.py"]
    assert out["artifact_files"] == ["src/ok.py"]
    # Nothing escaped the artifacts directory.
    assert not list(tmp_path.glob("**/PWNED.txt"))
    assert not (tmp_path / "ABS_PWNED.txt").exists()
    artifacts_dir = ctx.artifacts_dir("p")
    assert (artifacts_dir / "src" / "ok.py").read_text() == "print(1)\n"


def test_restore_artifacts_refuses_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIX_HOME", str(tmp_path))
    # Simulate a hand-crafted / legacy snapshot whose state still carries an
    # unsafe name (mint stores names verbatim; restore must refuse them).
    s = PipelineState(project_name="dx", code_artifacts=[
        {"name": "../../../../ABS_ESCAPE.txt", "type": "code",
         "content": "PWNED", "description": "bad"},
        {"name": "safe/keep.py", "type": "code",
         "content": "ok", "description": "good"},
    ])
    mint_snapshot(s, "dx", stage="builder")

    dest = tmp_path / "restore_dest"
    written = restore_artifacts("dx", 1, dest)

    assert written == ["safe/keep.py"]
    assert (dest / "safe" / "keep.py").read_text() == "ok"
    assert not list(tmp_path.glob("**/ABS_ESCAPE.txt"))
