# CLI Reference

The `helix-mini` CLI is the primary interface. Installed via `pip install -e .` and registered as the `helix-mini` command.

---

## Global Options

```
helix-mini [OPTIONS] COMMAND [ARGS]...
```

| Option | Description |
|--------|-------------|
| `-v`, `--verbose` | Enable DEBUG-level logging |

---

## `helix-mini run`

Run the Forge pipeline on one or more folders.

```
helix-mini run [OPTIONS] FOLDERS...
```

**Arguments:**
- `FOLDERS` (required, multiple) — Paths to input directories.

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--lightspeed` | flag | off | Auto-gates + cheapest model |
| `-q`, `--question` | text | `""` | Research question to guide analysis |
| `--sandbox` | flag | off | Run inside Docker container |
| `--local` | flag | off | All stages use local Qwen via Ollama |
| `--local-recommended` | flag | off | Simple stages local, critical stages cloud |
| `--model-size` | choice | `None` | Qwen model size: `small`, `medium`, `large` |
| `--cli` | text | `None` | Pilot the pipeline through an LLM CLI engine (e.g. `claude`) |
| `--cli-model` | text | `None` | Engine-native model for `--cli` (e.g. `haiku`, `opus`) |

**Engine resolution:** Explicit `--cli` / `--local` / `--local-recommended` win. With no engine flag, `ModelConfig.default()` decides with **OAuth-wins** precedence: if `CLAUDE_CODE_OAUTH_TOKEN` is set, `run` uses `cli/claude` on your Claude subscription (no API key, even if one is set); else the litellm API path; else a friendly error pointing at `claude setup-token`, `helix-mini setup`, or `--local`. `--cli claude` needs only the `claude` binary on PATH. `--local`/`--local-recommended` require Ollama; `--local-recommended` also needs an API key for cloud stages.

**Output:**
```
Helix Mini — 1 folder(s), mode=lightspeed
  -> my-folder
  [my-folder] scout ($0.0012)
  [my-folder] critic-methods ($0.0025)
  ...
--- Results ---
  my-folder: done (stages: 7, cost: $0.0089)
```

---

## `helix-mini agent`

Drive helix-mini conversationally via the **Claude Agent SDK**.

```
helix-mini agent [OPTIONS] [PROMPT]...
```

**Arguments:**
- `PROMPT...` (optional, variadic) — Your request as plain words, **no quotes
  needed**: `helix-mini agent search the atlas for cardiac modeling`. All
  words are joined into one prompt. Omit entirely for an interactive session.
  (Avoid unquoted shell globs like `?`/`*`; phrase without them or quote.)

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--max-turns` | int | `30` | Max agent turns before the session stops |

helix-mini ops are exposed as in-process MCP tools: `atlas_search`,
`atlas_status`, `decision_log` (auto-approved, read-only) and `run_pipeline`
(expensive — gated by a terminal confirmation; denied non-interactively). The
command clears the nested-session guard so it works inside Claude Code, and
prefers subscription auth when `CLAUDE_CODE_OAUTH_TOKEN` is set. Requires the
optional extra: `pip install 'helix-mini[agent]'` (a clear error is shown if
the SDK is missing). See [agent_sdk](agent_sdk.md).

---

## `helix-mini setup`

Interactive first-time setup wizard.

```
helix-mini setup
```

**Flow:**
1. Lists available providers (Anthropic, OpenAI).
2. Prompts for API key (hidden input).
3. Validates the key with a minimal LLM call.
4. Saves to `~/.helix-mini/.env`.
5. Creates `~/.helix-mini/config.toml` if absent.

---

## `helix-mini init`

Create a new project folder with a template.

```
helix-mini init [NAME]
```

**Arguments:**
- `NAME` (default: `"my-research"`) — Folder name to create.

**Creates:** `<NAME>/question.md` with a research question template.

---

## `helix-mini status`

Show Atlas summary and recent projects.

```
helix-mini status
```

**Output:**
```
Atlas: /Users/you/.helix-mini/atlas
Pages: 12
Projects: cardiac-sim, protein-fold
```

---

## `helix-mini log`

Print the decision log for a project.

```
helix-mini log PROJECT
```

**Arguments:**
- `PROJECT` (required) — Project name (matches folder name under `atlas/projects/`).

---

## `helix-mini atlas search`

Search the Atlas wiki by keyword.

```
helix-mini atlas search QUERY
```

**Arguments:**
- `QUERY` (required) — Space-separated search keywords.

**Output:** Matching pages with title, path, and a 500-character content preview.
