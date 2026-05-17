# Docker Sandbox Mode

## Goal

Run the pipeline in an isolated Docker container for enhanced security. This is recommended when processing untrusted input files.

## Prerequisites

- helix-mini installed
- [Docker](https://docs.docker.com/get-docker/) installed and running
- An API key or `CLAUDE_CODE_OAUTH_TOKEN` configured (both are forwarded into the container)

## Steps

### 1. Run with the sandbox flag

```bash
helix-mini run ./my-folder --sandbox --lightspeed
```

On the first run, helix-mini automatically builds the Docker image:

```
Building sandbox image (first time only)...
Sandbox image built.
Helix Mini (sandbox) — 1 folder(s), mode=lightspeed
```

### 2. Subsequent runs

The image is cached. Subsequent runs skip the build step.

```bash
helix-mini run ./my-folder --sandbox --lightspeed -q "How to model cardiac flow?"
```

## Security Properties

| Property | Detail |
|----------|--------|
| **User** | `helix` (non-root) inside container |
| **Source files** | Mounted read-only at `/input/<folder-name>` |
| **Atlas data** | `~/.helix-mini` mounted read-write for persistence |
| **Memory** | 2 GB limit |
| **CPUs** | 2 cores |
| **Privileges** | `--security-opt no-new-privileges` |
| **Auth env** | API keys **and** `CLAUDE_CODE_OAUTH_TOKEN` passed via `-e VAR_NAME` — Docker inherits from host. Values never appear in process arguments or logs. |

## How It Works

1. `helix-mini` builds a Docker image (`helix-mini-sandbox`) from the project's `Dockerfile` using `python:3.13-slim`.
2. Your input folders are mounted read-only inside the container.
3. `~/.helix-mini` is mounted read-write so Atlas data persists after the container exits.
4. API keys **and** `CLAUDE_CODE_OAUTH_TOKEN` are inherited from your host environment — values are never written to the Docker command line. (The `--cli claude` engine additionally needs the `claude` binary present in the image.)
5. The pipeline runs inside the container as user `helix`, and the container is removed (`--rm`) after completion.

## Variations

- **Rebuild the image**: If you update helix-mini source code, delete the old image and it will be rebuilt: `docker rmi helix-mini-sandbox`
- **Combined with local mode**: `--sandbox` runs the CLI inside the container. `--local` would require Ollama to be accessible from within the container (not configured by default).
