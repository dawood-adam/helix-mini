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

**Mutually exclusive modes:** `--local` and `--local-recommended` cannot be combined. Both require Ollama. `--local-recommended` also requires an API key for cloud stages.

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
