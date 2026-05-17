"""Lightweight snapshot store for ForgeState."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .state import ForgeState


def mint_snapshot(state: ForgeState, project_dir: Path) -> Path:
    """Save a snapshot of the current state. Returns the snapshot path."""
    snap_dir = project_dir / ".snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(snap_dir.glob("snap-*.json"))
    next_num = len(existing) + 1

    snap_path = snap_dir / f"snap-{next_num}.json"
    snap_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": state.current_stage,
        "state": asdict(state),
    }
    snap_path.write_text(json.dumps(snap_data, indent=2, default=str))
    return snap_path


def load_snapshot(snap_path: Path) -> dict:
    """Load a snapshot from disk."""
    return json.loads(snap_path.read_text())


def list_snapshots(project_dir: Path) -> list[Path]:
    """List all snapshots for a project."""
    snap_dir = project_dir / ".snapshots"
    if not snap_dir.exists():
        return []
    return sorted(snap_dir.glob("snap-*.json"))
