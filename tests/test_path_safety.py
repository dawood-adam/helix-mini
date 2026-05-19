"""Security regression: model-controlled project/name cannot traverse out
of the snapshot, runs, or hot path roots (security-review finding)."""

from __future__ import annotations

import pytest

from helix import runs
from helix.core import hot, snapshots
from helix.core.state import PipelineState
from helix.sandbox import SandboxError, validate_project_name

_BAD = ["../evil", "..", "a/b", "a\\b", ".hidden", "-x", "", "a..b",
        "x/../../y", "/abs", "a" * 129]
_GOOD = ["src-papers", "demo-proj", "p", "d2", "smartphone_bp", "My Papers"]


@pytest.mark.parametrize("name", _BAD)
def test_validator_rejects_unsafe(name):
    with pytest.raises(SandboxError):
        validate_project_name(name)


@pytest.mark.parametrize("name", _GOOD)
def test_validator_accepts_safe(name):
    assert validate_project_name(name) == name.strip()


def test_snapshots_root_blocks_traversal(project):
    with pytest.raises(SandboxError):
        snapshots._root("../../../../tmp/evil")
    # the legitimate path still works
    snapshots.mint_snapshot(PipelineState(project_name="ok"), "ok", stage="scout")
    assert snapshots.list_snapshots("ok")


def test_fork_blocks_traversal_in_name_and_project(project):
    snapshots.mint_snapshot(PipelineState(project_name="ok"), "ok", stage="scout")
    with pytest.raises(SandboxError):           # malicious bundle name
        snapshots.fork("ok", "../../../../tmp/escape")
    with pytest.raises(SandboxError):           # malicious source project
        snapshots.fork("../../../../etc", "bundle")
    dest = snapshots.fork("ok", "bundle")       # safe path still works
    assert dest.name == "bundle.tar.gz"


def test_freeze_and_branch_block_traversal(project):
    snapshots.mint_snapshot(PipelineState(project_name="ok"), "ok", stage="scout")
    with pytest.raises(SandboxError):
        snapshots.freeze("../../etc", "1", "v1")
    with pytest.raises(SandboxError):
        snapshots.make_branch("../../etc", "1", "alt")


def test_runs_registry_blocks_traversal(project):
    with pytest.raises(SandboxError):
        runs.start_run("../../../../tmp/x", __import__(
            "helix.core.plan", fromlist=["Plan"]).Plan())
    with pytest.raises(SandboxError):
        runs.get_record(project="../../../../etc/passwd")


def test_hot_cache_blocks_traversal(project):
    with pytest.raises(SandboxError):
        hot.read_hot("../../../../tmp/x")
    assert "no hot cache" in hot.read_hot("ghost")  # safe miss still works
