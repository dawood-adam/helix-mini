"""Configuration: repo-local paths and helix.toml limits.

All path resolution lives here so the rest of the codebase never hardcodes a
location. Defaults are repo-local: the Atlas and the ``.helix`` control
directory live in the project folder unless overridden.

Sampling-only: there is no provider/API-key/model machinery here anymore.
The MCP client picks the model and holds the credentials. ``ModelConfig`` is
a vestigial stub kept only so the loop/agent signatures stay stable.
"""

from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager
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


# A run binds its own root (the resolved source folder) here, so the whole
# pipeline — atlas, .helix/snapshots, runs, hot, decisions — is self-contained
# under that folder and immune to the server process's launch cwd. This
# mirrors ``helix.io.use``: per-run state threaded via a contextvar, never a
# global. Unbound (every non-run tool, and resume without a folder) falls back
# to HELIX_HOME / cwd, so prior behaviour is unchanged where it was already
# correct.
_RUN_ROOT: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "helix_run_root", default=None
)


@contextmanager
def use_root(path: str | Path | None):
    """Bind the project root for the duration of a run. Empty / ``None`` is a
    no-op (keeps the HELIX_HOME / cwd fallback) so callers can wrap
    unconditionally."""
    if not path:
        yield
        return
    token = _RUN_ROOT.set(Path(path).expanduser().resolve())
    try:
        yield
    finally:
        _RUN_ROOT.reset(token)


def project_root() -> Path:
    """The helix *project* (run) directory — per-project operational state
    (snapshots / runs / pending) lives here. A run binds it to its source
    folder (:func:`use_root`); otherwise ``HELIX_HOME`` overrides the
    process cwd. Distinct from :func:`workspace_root` (the shared,
    cross-project Atlas root)."""
    bound = _RUN_ROOT.get()
    if bound is not None:
        return bound
    return Path(os.environ.get("HELIX_HOME", Path.cwd())).resolve()


def _has_workspace_marker(d: Path) -> bool:
    """A directory is a Helix workspace if it carries either a
    ``.helix-workspace`` file (git-style) or a ``helix.toml`` with a
    ``[workspace]`` section."""
    if (d / ".helix-workspace").exists():
        return True
    toml = d / "helix.toml"
    if not toml.exists():
        return False
    try:
        with open(toml, "rb") as f:
            data = tomllib.load(f)
    except (OSError, ValueError):
        return False
    return "workspace" in data


def workspace_root() -> Path:
    """The shared *workspace* root — the cross-project knowledge base
    (Atlas + Constitution) lives here. Resolution order:

    1. explicit ``HELIX_ATLAS`` env, or absolute ``[atlas].path`` in the
       project's ``helix.toml`` → that path's parent is the workspace.
    2. nearest ancestor of :func:`project_root` carrying a workspace
       marker (``helix.toml [workspace]`` or ``.helix-workspace``).
    3. ``HELIX_HOME``.
    4. :func:`project_root` (back-compat: when there is no workspace, the
       project IS the workspace — the pre-Phase-1 model).
    """
    # 1. explicit atlas path → its parent
    explicit = os.environ.get("HELIX_ATLAS")
    if explicit:
        ap = Path(explicit).expanduser().resolve()
        return ap.parent if ap.name == "atlas" else ap
    cfg_path = load_helix_toml().get("atlas", {}).get("path")
    if cfg_path:
        p = Path(cfg_path).expanduser()
        if p.is_absolute():
            p = p.resolve()
            return p.parent if p.name == "atlas" else p
    # 2. ancestor walk-up for a workspace marker
    cur = project_root()
    while True:
        if _has_workspace_marker(cur):
            return cur
        parent = cur.parent
        if parent == cur:  # filesystem root
            break
        cur = parent
    # 3. HELIX_HOME fallback
    env = os.environ.get("HELIX_HOME")
    if env:
        return Path(env).expanduser().resolve()
    # 4. back-compat: project is the workspace
    return project_root()


def helix_dir() -> Path:
    """``.helix/`` — per-project operational state (snapshots, objects,
    refs, env). Resolves against the *project* root (under
    :func:`use_root` when a run is active), NOT the workspace root, so the
    self-rooting safety holds. Created on demand."""
    d = project_root() / ".helix"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_env() -> None:
    # Probe paths without materialising .helix/: this runs at import, before
    # any run binds a root, so calling helix_dir() here would scatter an
    # empty .helix into whatever cwd the server happened to launch in.
    root = project_root()
    for env in (root / ".helix" / ".env", root / ".env"):
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
    """Atlas root — *workspace-rooted*, not project-rooted. The Atlas is the
    cross-project knowledge base; per-project operational state lives under
    :func:`helix_dir`. Resolution: ``HELIX_ATLAS`` env, or ``[atlas].path``
    from ``helix.toml`` (absolute or workspace-relative), or default
    ``workspace_root()/atlas``."""
    cfg = load_helix_toml().get("atlas", {})
    raw = os.environ.get("HELIX_ATLAS") or cfg.get("path") or "atlas"
    p = Path(raw).expanduser()
    return p.resolve() if p.is_absolute() else workspace_root() / p


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
