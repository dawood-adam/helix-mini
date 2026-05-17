# Lightspeed Single-Folder Run

## Goal

Run the full 6-agent research pipeline on a single folder of source material with no human interaction. This is the fastest way to use helix-mini.

## Prerequisites

- helix-mini installed (`pip install -e .`)
- Auth configured once (see [Getting Started](../getting-started.md#first-run-setup--pick-one)): a Claude subscription token in `~/.helix-mini/.env`, an API key via `helix-mini setup`, or Ollama for `--local`

## Steps

### 1. Create a project folder

```bash
helix-mini init cardiac-research
```

Output:
```
Created: cardiac-research/
  1. Edit cardiac-research/question.md with your research question
  2. Add source files to cardiac-research/
  3. Run: helix-mini run ./cardiac-research --lightspeed
```

### 2. Add source material

Place your papers, code, data, or notes into the folder:

```bash
cp ~/papers/cardiac-cfd.pdf cardiac-research/
cp ~/papers/pinn-electro.md cardiac-research/
```

Supported file types: `.md`, `.txt`, `.py`, `.json`, `.csv`, `.toml`, `.yaml`, `.yml`, `.rst`, `.pdf` (requires `pip install "helix-mini[pdf]"`).

### 3. Edit the research question

```bash
# Edit cardiac-research/question.md with your question
echo "How can we combine CFD with PINNs for cardiac flow modeling?" > cardiac-research/question.md
```

### 4. Run the pipeline

```bash
helix-mini run ./cardiac-research --lightspeed -q "How to combine CFD with PINNs for cardiac flow?"
```

The `-q` flag passes the research question directly (alternative to editing `question.md`). The `--lightspeed` flag:
- Uses the cheaper model (Claude Haiku)
- Auto-approves all gates (no pausing for review)

### 5. View progress

As the pipeline runs, you'll see stage-by-stage progress:

```
Helix Mini — 1 folder(s), mode=lightspeed
  -> cardiac-research
  [cardiac-research] scout ($0.0012)
  [cardiac-research] critic-methods ($0.0025)
  [cardiac-research] planner ($0.0031)
  [cardiac-research] builder ($0.0056)
  [cardiac-research] critic-results ($0.0070)

--- Results ---
  cardiac-research: done (stages: 7, cost: $0.0070)
```

### 6. Explore results

After the run completes, your results are at `~/.helix-mini/`:

```bash
# See what's in the Atlas
helix-mini status

# Search for findings
helix-mini atlas search "cardiac"

# View the decision log
helix-mini log cardiac-research
```

The Atlas wiki at `~/.helix-mini/atlas/` contains:
- `sources/` — Summaries of your input files
- `concepts/` — Key concepts identified
- `projects/cardiac-research/` — Project-specific findings, decision log, and state snapshots

## Variations

- **Without `--lightspeed`**: Uses the default model (Claude Sonnet, more capable but more expensive). Without `--lightspeed`, gates are set to `always_ask` mode, but currently auto-proceed since interactive gate prompts are not yet implemented.
- **Engine selection**: With no engine flag, helix-mini resolves the engine by **OAuth-wins** precedence — a `CLAUDE_CODE_OAUTH_TOKEN` runs this on your Claude subscription (no API key), else the API path. Add `--cli claude` to force the subscription engine, or `--local` for Qwen. See [Claude Subscription / CLI Engine](claude-cli-engine.md).
- **With `-v` (verbose)**: Enables DEBUG logging for troubleshooting: `helix-mini -v run ./cardiac-research --lightspeed`
- **Budget caps**: The default budget is $5.00 per run (not configurable via CLI). For CLI engines that don't report cost, a per-run call-count cap (24 LLM nodes) is armed instead.
