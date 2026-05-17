"""App wiring — facade that ties Atlas + config + runner together."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable

from .atlas import Atlas
from .config import HELIX_HOME, ModelConfig, ensure_config
from .pipeline.runner import run_parallel, run_project
from .pipeline.state import ForgeState

log = logging.getLogger(__name__)


class HelixMini:
    def __init__(self, home: Path | None = None):
        self.home = home or HELIX_HOME
        self.home.mkdir(parents=True, exist_ok=True)
        self.atlas_root = self.home / "atlas"
        self.atlas = Atlas(self.atlas_root)
        ensure_config(self.home)

    def run(
        self,
        folders: list[Path],
        lightspeed: bool = False,
        research_question: str = "",
        progress_fn: Callable[[str, str, float], None] | None = None,
        model_config: ModelConfig | None = None,
    ) -> list[ForgeState]:
        """Run Forge pipelines on one or more folders."""
        if model_config is None:
            model_config = ModelConfig.default(lightspeed=lightspeed) or ModelConfig.load(
                lightspeed=lightspeed
            )
        mode = "lightspeed" if lightspeed else "normal"
        log.info(
            "Helix Mini — %d folder(s), mode=%s, model=%s",
            len(folders), mode, model_config.model,
        )

        for f in folders:
            if not f.is_dir():
                raise FileNotFoundError(f"Folder not found: {f}")

        if len(folders) == 1:
            result = run_project(
                folders[0],
                self.atlas,
                model_config,
                lightspeed=lightspeed,
                research_question=research_question,
                home=self.home,
                progress_fn=progress_fn,
            )
            return [result]

        return asyncio.run(
            run_parallel(
                folders,
                self.atlas,
                model_config,
                lightspeed=lightspeed,
                research_question=research_question,
                home=self.home,
                progress_fn=progress_fn,
            )
        )
