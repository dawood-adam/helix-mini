"""Configuration: repo-local paths and helix.toml limits.

All path resolution lives here so the rest of the codebase never hardcodes a
location. Defaults are repo-local: the Atlas and the ``.helix`` control
directory live in the project folder unless overridden.

Sampling-only: there is no provider/API-key/model machinery here anymore.
The MCP client picks the model and holds the credentials. ``ModelConfig`` is
a vestigial stub kept only so the loop/agent signatures stay stable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

try:
    import tomllib
except ImportError:  # pragma: no cover - py311 has tomllib
    import tomli as tomllib  # type: ignore[no-redef]

# --- Guardrail defaults (the only real bound on unbounded cycling) ----------
# Sampling never reports cost/tokens to the server, so the budget is an
# estimate (≈ chars/4) of prompt+response text the server itself sees.
TOKEN_CAP_DEFAULT = 200_000
CALL_CAP_DEFAULT = 60

# --- Paths ------------------------------------------------------------------


def project_root() -> Path:
    """The helix project directory. ``HELIX_HOME`` overrides the cwd."""
    return Path(os.environ.get("HELIX_HOME", Path.cwd())).resolve()


def helix_dir() -> Path:
    """``.helix/`` — snapshots, objects, refs, env. Created on demand."""
    d = project_root() / ".helix"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_env() -> None:
    for env in (helix_dir() / ".env", project_root() / ".env"):
        if env.exists():
            load_dotenv(env, override=False)
    load_dotenv(override=False)


def load_helix_toml() -> dict:
    """Parse ``<project>/helix.toml``; {} if absent or unreadable."""
    path = project_root() / "helix.toml"
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, ValueError):
        return {}


def atlas_path() -> Path:
    """Atlas root. ``helix.toml [atlas].path`` or repo-local ``./atlas``."""
    cfg = load_helix_toml().get("atlas", {})
    raw = os.environ.get("HELIX_ATLAS") or cfg.get("path") or "atlas"
    p = Path(raw)
    return p if p.is_absolute() else project_root() / p


def token_cap() -> int:
    return int(load_helix_toml().get("limits", {}).get("token_cap", TOKEN_CAP_DEFAULT))


def call_cap_default() -> int:
    return int(load_helix_toml().get("limits", {}).get("call_cap", CALL_CAP_DEFAULT))


_load_env()


# --- Model selection (sampling-only stub) -----------------------------------


@dataclass
class ModelConfig:
    """Vestigial. The MCP client picks the model under sampling; this only
    keeps the loop/agent signatures stable."""

    model: str = "sampling"

    def model_for_stage(self, stage: str) -> str:
        return self.model

    def call_cap(self) -> int:
        return call_cap_default()

    @classmethod
    def cli(cls, *args, **kwargs) -> ModelConfig:
        return cls()

    @classmethod
    def default(cls, *args, **kwargs) -> ModelConfig:
        return cls()
