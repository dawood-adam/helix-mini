# Multi-Folder Parallel Run

## Goal

Run the pipeline on multiple folders simultaneously, with all projects sharing a single Atlas wiki. Knowledge from earlier-finishing projects is available to later-finishing ones.

## Prerequisites

- helix-mini installed with an API key configured
- Two or more input folders with source material

## Steps

### 1. Prepare multiple folders

```bash
helix-mini init cardiac-sim
helix-mini init protein-fold
# Add source files to each folder
```

### 2. Run in parallel

```bash
helix-mini run ./cardiac-sim ./protein-fold --lightspeed
```

Output:
```
Helix Mini — 2 folder(s), mode=lightspeed
  -> cardiac-sim
  -> protein-fold
  [cardiac-sim] scout ($0.0012)
  [protein-fold] scout ($0.0015)
  [cardiac-sim] critic-methods ($0.0025)
  ...

--- Results ---
  cardiac-sim: done (stages: 7, cost: $0.0068)
  protein-fold: done (stages: 7, cost: $0.0072)
```

### 3. Explore the shared Atlas

```bash
helix-mini status
```

Both projects' findings are in the same Atlas. Searching will return results from all projects:

```bash
helix-mini atlas search "simulation"
```

## How It Works

- Multiple folders are run via `asyncio.gather()` in a thread pool executor.
- All pipelines share one `Atlas` instance. The `Atlas.write()` method uses a `threading.Lock` to ensure writes are atomic.
- Each project gets its own decision log and snapshots under `~/.helix-mini/atlas/projects/<name>/`.
- The cost cap ($5.00) applies per project, not globally.

## Variations

- **Different research questions**: The `-q` flag applies to all folders. For per-folder questions, run them separately.
- **Mixed with lightspeed**: `--lightspeed` applies to all folders uniformly.
