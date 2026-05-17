# Getting Started

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| **Python** | >= 3.11 | `tomllib` is in stdlib from 3.11 |
| **pip** | any recent | For editable install |
| **Git** | any | To clone the repo |
| **Docker** | any | Optional — only for `--sandbox` mode |
| **Ollama** | any | Optional — only for `--local` / `--local-recommended` modes |
| **Claude CLI** | any | Optional — `claude` on PATH for `--cli claude` / subscription auth |
| **claude-agent-sdk** | >=0.2,<0.3 | Optional — only for `helix-mini agent` (`pip install '.[agent]'`) |

## Installation

```bash
git clone <repo-url>
cd helix-mini

# Install with dev dependencies (pytest)
pip install -e ".[dev]"

# Optional: PDF text extraction
pip install -e ".[pdf]"

# Optional: drive helix-mini via the Claude Agent SDK (`helix-mini agent`)
pip install -e ".[agent]"
```

## Environment Variables

| Variable | Purpose | Default | Required? |
|----------|---------|---------|-----------|
| `HELIX_MINI_HOME` | Override the data directory | `~/.helix-mini` | No |
| `ANTHROPIC_API_KEY` | Anthropic API authentication | — | Yes, if using the Anthropic API |
| `OPENAI_API_KEY` | OpenAI API authentication | — | Yes, if using OpenAI |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude **subscription** auth for `--cli claude` / `helix-mini agent` (mint with `claude setup-token`). Not an API key. **OAuth wins**: when set, takes precedence over `ANTHROPIC_API_KEY` for Claude runs. | — | No |

**helix-mini reads every credential from one file: `~/.helix-mini/.env`** (a
`.env` in the current directory overrides it). Keep it private — `chmod 600`.
There is no other place to configure auth; once it's set, every command just
works with no `export`, no wrapper, and no quotes.

## First-Run Setup — pick one

### A. Claude subscription (recommended — no API key)

```bash
claude setup-token                                   # mint a token (one-time)
mkdir -p ~/.helix-mini && chmod 700 ~/.helix-mini
"${EDITOR:-nano}" ~/.helix-mini/.env                 # add one line:
                                                     #   CLAUDE_CODE_OAUTH_TOKEN=<paste token>
chmod 600 ~/.helix-mini/.env
```

Use an **editor** (not `echo`/`export`) so the token never lands in shell
history or another process's environment, and `chmod 600` so only you can read
it. That's the whole secure setup — `helix-mini run ./my-folder --lightspeed`
now runs on your Claude plan. **OAuth wins:** a stray `ANTHROPIC_API_KEY` will
not silently switch you to paid API billing.

### B. API key (Anthropic / OpenAI)

```bash
helix-mini setup        # wizard: pick provider, paste key, validates, writes ~/.helix-mini/.env
```

### C. Local, fully offline (no account)

```bash
ollama pull qwen3:8b
helix-mini run ./my-folder --local --lightspeed
```

## Verify Installation

### 1. Check CLI is available

```bash
helix-mini --help
```

Expected output:
```
Usage: helix-mini [OPTIONS] COMMAND [ARGS]...

  Helix Mini — research pipelines with a persistent LLM wiki.

Options:
  -v, --verbose  Enable verbose logging
  --help         Show this message and exit.

Commands:
  agent   Drive helix-mini conversationally via a Claude agent.
  atlas   Atlas wiki commands.
  init    Create a new project folder ready for research.
  log     Print decision log for a project.
  run     Run Forge pipeline on one or more folders.
  setup   Interactive setup — pick provider, enter API key, validate.
  status  Show Atlas status and recent projects.
```

### 2. Run the test suite

```bash
pytest
```

Expected output:
```
126 passed, 1 skipped in ~3s
```

(The 1 skipped is a live Claude-CLI integration test, opt-in via `HELIX_CLI_IT=1`.)

### 3. Create a test project

```bash
helix-mini init my-research
```

Expected output:
```
Created: my-research/
  1. Edit my-research/question.md with your research question
  2. Add source files to my-research/
  3. Run: helix-mini run ./my-research --lightspeed
```

This creates `my-research/question.md` with a template. Add your source files (PDFs, papers, code, data) to the folder, then run the pipeline.

## Troubleshooting

| Error Message | Cause | Solution |
|---------------|-------|----------|
| `No Claude OAuth token or API key found.` | No `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, or `OPENAI_API_KEY` set | Run `claude setup-token` (subscription), `helix-mini setup` (API key), or use `--local` |
| `--local-recommended needs an API key for critical stages.` | `--local-recommended` requires a cloud API key | Set an API key or use `--local` instead |
| `The Claude Agent SDK is not installed.` | `helix-mini agent` without the optional extra | `pip install 'helix-mini[agent]'` |
| `Claude CLI not found on PATH — reinstall Claude Code.` | `--cli claude` (or OAuth default) but `claude` not installed | Install Claude Code so the `claude` binary is on PATH |
| `CLI engine '<x>' is not on PATH` / `Unknown CLI engine '<x>'` | `--cli <x>` with a missing binary or undefined engine | Install the binary, or add a `[cli.<x>]` block to `config.toml` |
| `Cannot find helix-mini project root (pyproject.toml).` | Docker sandbox can't find project root | Run from the cloned repo directory |
| `[PDF file — install pymupdf to extract text: ...]` | pymupdf not installed | `pip install "helix-mini[pdf]"` |
| `Folder not found: <path>` | Input folder doesn't exist | Verify the folder path |
| `No Atlas found. Run 'helix-mini run <folder>' first.` | Running `status` or `atlas search` before any pipeline run | Run a pipeline first to create the Atlas |
