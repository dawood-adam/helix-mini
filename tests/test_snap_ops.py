"""4a: snapshot git-ops — branch / freeze (tag) / fork (bundle)."""

from __future__ import annotations

import tarfile

from helix import config
from helix.core.snapshots import (
    fork, freeze, list_refs, make_branch, mint_snapshot,
)
from helix.core.state import PipelineState


def _two_snaps():
    st = PipelineState(project_name="p")
    mint_snapshot(st, "p", stage="scout")
    mint_snapshot(st, "p", stage="planner", parent="1")


def test_branch_and_freeze_refs(project):
    _two_snaps()
    assert make_branch("p", "1", "alt") is True
    assert freeze("p", "2", "v1") is True
    assert make_branch("p", "99", "nope") is False   # no such snapshot
    refs = list_refs("p")
    assert refs["branches"]["alt"] == "1"
    assert refs["tags"]["v1"] == "2"


def test_fork_exports_reproducible_bundle(project):
    _two_snaps()
    freeze("p", "2", "v1")
    dest = fork("p", "smartphone-bp-v1")
    assert dest == config.project_root() / "forks" / "smartphone-bp-v1.tar.gz"
    assert dest.exists() and dest.stat().st_size > 0
    with tarfile.open(dest) as tar:
        names = tar.getnames()
    # bundle carries the full history: snaps + index + refs
    assert "p/1.json" in names and "p/2.json" in names
    assert "p/index.json" in names and "p/refs.json" in names
