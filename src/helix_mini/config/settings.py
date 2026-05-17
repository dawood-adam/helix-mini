"""Helix Mini settings and environment."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


HELIX_HOME = Path(os.environ.get("HELIX_MINI_HOME", Path.home() / ".helix-mini"))

# Load .env files: home-level first, then project-level overrides
_home_env = HELIX_HOME / ".env"
if _home_env.exists():
    load_dotenv(_home_env, override=False)
load_dotenv(override=True)  # .env in cwd

DEFAULT_CONFIG = {
    "default": {"model": "anthropic/claude-sonnet-4-20250514"},
    "lightspeed": {"model": "anthropic/claude-haiku-4-5-20251001"},
}


def ensure_config(home: Path | None = None) -> Path:
    """Create default config.toml if it doesn't exist. Returns path."""
    home = home or HELIX_HOME
    home.mkdir(parents=True, exist_ok=True)
    config_path = home / "config.toml"

    if not config_path.exists():
        config_path.write_text(
            '[default]\nmodel = "anthropic/claude-sonnet-4-20250514"\n\n'
            '[lightspeed]\nmodel = "anthropic/claude-haiku-4-5-20251001"\n'
        )

    return config_path
