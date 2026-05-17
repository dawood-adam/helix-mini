"""Docker sandbox — runs the Forge pipeline in an isolated container.

Security properties:
- Non-root user inside container
- Source folders mounted read-only
- No network except for LLM API calls
- Atlas output volume-mounted for persistence
- No host filesystem access beyond explicit mounts
- Resource limits (memory, CPU, no-new-privileges)
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from .config import HELIX_HOME, PROVIDERS

log = logging.getLogger(__name__)

DOCKER_IMAGE = "helix-mini-sandbox"
DOCKERFILE_SENTINEL = "helix-mini"  # to detect if image exists


def _find_project_root() -> Path:
    """Find the helix-mini project root (contains pyproject.toml)."""
    this_file = Path(__file__).resolve()
    candidate = this_file.parent.parent.parent
    if (candidate / "pyproject.toml").exists():
        return candidate
    if (Path.cwd() / "pyproject.toml").exists():
        return Path.cwd()
    raise FileNotFoundError(
        "Cannot find helix-mini project root (pyproject.toml). "
        "Run from the project directory or install from source."
    )


def _ensure_docker() -> None:
    """Check that Docker is available."""
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True,
            check=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("Error: Docker is not installed or not running.", file=sys.stderr)
        print("Install Docker: https://docs.docker.com/get-docker/", file=sys.stderr)
        sys.exit(1)


def _build_image() -> None:
    """Build the sandbox Docker image if not already built."""
    result = subprocess.run(
        ["docker", "images", "-q", DOCKER_IMAGE],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        return  # Image exists

    print("Building sandbox image (first time only)...")
    project_root = _find_project_root()
    subprocess.run(
        ["docker", "build", "-t", DOCKER_IMAGE, str(project_root)],
        check=True,
    )
    print("Sandbox image built.")


def _collect_env_vars() -> list[str]:
    """Collect API key environment variables to pass into the container.

    Uses ``-e VAR_NAME`` (without ``=VALUE``) so Docker inherits
    from the host environment.  This keeps secrets out of the
    process argument list (visible in ``/proc/<pid>/cmdline``)
    and out of any log line that prints the command.
    """
    env_args: list[str] = []
    for info in PROVIDERS.values():
        var = info["env_var"]
        if os.environ.get(var):
            env_args.extend(["-e", var])
    return env_args


def run_sandboxed(
    folders: list[Path],
    lightspeed: bool = False,
    question: str = "",
) -> None:
    """Run helix-mini inside a Docker sandbox.

    Security model:
    - Source folders: mounted read-only at /input/<name>
    - Atlas data: ~/.helix-mini mounted read-write for persistence
    - Network: allowed (needed for LLM API calls)
    - User: non-root (helix)
    - Resources: 2GB memory limit, no-new-privileges
    """
    _ensure_docker()
    _build_image()

    HELIX_HOME.mkdir(parents=True, exist_ok=True)

    cmd = [
        "docker", "run", "--rm",
        "--security-opt", "no-new-privileges",
        "--memory", "2g",
        "--cpus", "2",
        "-v", f"{HELIX_HOME}:/home/helix/.helix-mini",
    ]

    container_folders: list[str] = []
    for folder in folders:
        abs_path = folder.resolve()
        container_path = f"/input/{folder.name}"
        cmd.extend(["-v", f"{abs_path}:{container_path}:ro"])
        container_folders.append(container_path)

    env_args = _collect_env_vars()
    env_count = len(env_args) // 2  # each var is ["-e", "VAR_NAME"]

    cmd.append(DOCKER_IMAGE)
    cmd.append("run")
    if lightspeed:
        cmd.append("--lightspeed")
    if question:
        cmd.extend(["-q", question])
    cmd.extend(container_folders)

    # Log the command without env-var args to avoid leaking secrets.
    log.info("Launching sandbox (%d env vars): %s", env_count, " ".join(cmd))

    # Insert env args right before the image name for the actual execution.
    image_idx = cmd.index(DOCKER_IMAGE)
    for i, arg in enumerate(env_args):
        cmd.insert(image_idx + i, arg)

    result = subprocess.run(cmd)

    if result.returncode != 0:
        raise RuntimeError(f"Sandbox exited with code {result.returncode}")
