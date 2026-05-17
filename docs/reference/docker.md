# helix_mini.docker

Docker sandbox — runs the pipeline in an isolated container with security hardening.

---

## `run_sandboxed`

```python
def run_sandboxed(
    folders: list[Path],
    lightspeed: bool = False,
    question: str = "",
) -> None
```

**Parameters:**
- `folders` (`list[Path]`) — Input directories. Each is mounted read-only at `/input/<name>` inside the container.
- `lightspeed` (`bool`, default: `False`) — Passed to the `helix-mini run` command inside the container.
- `question` (`str`, default: `""`) — Research question passed via `-q` flag.

**Raises:**
- `RuntimeError` — If the container exits with a non-zero code.

**Behavior:**
1. Verifies Docker is installed and running.
2. Builds the `helix-mini-sandbox` image from the project `Dockerfile` if it doesn't exist.
3. Runs the container with the following security properties:

| Property | Value |
|----------|-------|
| User | `helix` (non-root) |
| Source mounts | Read-only (`:ro`) |
| Atlas mount | `~/.helix-mini` read-write (for persistence) |
| Privileges | `--security-opt no-new-privileges` |
| Memory | 2 GB limit |
| CPUs | 2 |
| API keys | Passed via `-e VAR_NAME` (Docker inherits from host; values never appear in process args or logs) |

**Example:**
```python
from pathlib import Path
from helix_mini.docker import run_sandboxed

run_sandboxed([Path("./my-data")], lightspeed=True, question="How to model cardiac flow?")
```
