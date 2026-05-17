"""Shared test fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from helix_mini.atlas import Atlas


@pytest.fixture
def tmp_atlas(tmp_path: Path) -> Atlas:
    """Create a temporary Atlas instance."""
    atlas_root = tmp_path / "atlas"
    return Atlas(atlas_root)


@pytest.fixture
def tmp_home(tmp_path: Path) -> Path:
    """Create a temporary helix-mini home directory."""
    home = tmp_path / ".helix-mini"
    home.mkdir()
    return home


@pytest.fixture
def sample_folder(tmp_path: Path) -> Path:
    """Create a sample input folder with test files."""
    folder = tmp_path / "test-project"
    folder.mkdir()
    (folder / "paper1.md").write_text(
        "# Cardiac Modeling Study\n\n"
        "This paper explores computational fluid dynamics for cardiac simulation.\n"
        "Methods: finite element analysis, Navier-Stokes equations.\n"
        "Results show improved accuracy in ventricular flow prediction."
    )
    (folder / "paper2.txt").write_text(
        "Title: Neural Network Approaches to Heart Modeling\n\n"
        "We propose using physics-informed neural networks (PINNs) for\n"
        "cardiac electrophysiology simulation. Compared to traditional FEM,\n"
        "PINNs offer faster inference with comparable accuracy."
    )
    (folder / "data.json").write_text(
        json.dumps({"experiment": "cardiac-sim", "metrics": {"accuracy": 0.92}})
    )
    return folder


def make_fake_llm_response(response_data: dict):
    """Create a mock for call_llm_json that returns the given data."""
    def fake_call_llm_json(**kwargs) -> tuple[dict, float]:
        return response_data, 0.001
    return fake_call_llm_json
