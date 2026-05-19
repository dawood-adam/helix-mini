# The MCP surface

Helix is an MCP server (`helix/mcp/server.py`, built on FastMCP). The client
launches it over stdio via the project's `.mcp.json`. There is no network
service and no credential configuration.

## Connection

`helix init` writes a server pinned to the interpreter Helix is installed
in (`sys.executable` of the process running `helix init`):

```json
{ "mcpServers": { "helix": {
  "command": "/abs/path/to/python",
  "args": ["-m", "helix.mcp.server"]
} } }
```

This is deliberate: the client resolves a bare `command` against its own
`PATH`, which need not include the environment's `bin/`. The absolute
interpreter + `-m helix.mcp.server` is PATH-independent and portable.
`helix-mcp` (console entry point `helix.mcp.server:main`) and `helix mcp`
run the same server by hand for debugging.

## The model, and elicitation

Helix has no model of its own and stores no credentials. **The client agent
is the model.** A model-needing stage does not sample: `hx_step` returns the
stage's prompt as its tool output, the agent answers in its own turn, and
`hx_submit` feeds that answer back in. See
[agent-driven-pipeline.md](agent-driven-pipeline.md).

The one remaining server→client callback, through the single seam in
`helix/io.py`, is **elicitation** — structured questions to the user
mid-tool: the `hx_start` wizard, every HITL gate, and confirmation before
promoting a page to a published tier. Schemas are flat (string / enum /
boolean / array), built by the `ask_*` helpers. A client without
elicitation cannot run gated tools, and fails fast with a clear message
before any run starts.

## Tools

Twenty-six tools. Read tools are side-effect-free; the rest change project
state and the client confirms them before running.

### Pipeline

The pipeline is agent-driven: `hx_step` returns a stage's prompt, the agent
answers, `hx_submit` advances. `run_pipeline` and `hx_start` are
initializers that return the *first* `hx_step`.

| Tool | Purpose |
|---|---|
| `hx_step` | Advance to the next stage that needs the model; returns its SYSTEM + USER prompt for the agent to answer (or the final summary). Deterministic stages run server-side. First call initializes the run. |
| `hx_submit` | Submit the agent's JSON answer for the pending stage; maps it, writes the Atlas, snapshots, runs the gate, and returns the next prompt. Guarded by `pending_token`. |
| `hx_start` | Guided setup wizard; creates the source folder if missing, then starts the run and returns the first stage's prompt. |
| `run_pipeline` | Start a run on a folder and return the first stage's prompt. `autonomy_until` (`''`, a stage, or `END`) auto-proceeds gates. |
| `resume_pipeline` | Rebuild a snapshot and re-enter at any stage/branch; `folder` self-roots it. |
| `hx_run_status` | The latest run's status (survives a restart). |
| `hx_run_events` | The run's transition events since a sequence number. |
| `hx_run_plan_set` | Steer the live run's Plan (effective at the next gate). |

### Atlas

| Tool | Purpose |
|---|---|
| `hx_atlas_ingest` | Process `atlas/inbox/` (idempotent, sha256 manifest). |
| `hx_atlas_recall` | Auto-routing search; returns references only. |
| `hx_atlas_get` | Fetch one page body (capped). |
| `hx_atlas_neighbors` | k-hop neighbours over the link graph. |
| `hx_atlas_lint` | Six-kind hygiene report with fixes. |
| `hx_atlas_put` | Create/update a page (merges on the same path). |
| `hx_atlas_save` | File a synthesis/comparison answer as a page. |
| `hx_atlas_promote` | Bump tier; confirms at canonical/published. |
| `atlas_status` | Page count and known projects. |
| `decision_log` | A project's stage-by-stage decision log. |

### Snapshots

| Tool | Purpose |
|---|---|
| `snapshot_list` / `snapshot_show` / `snapshot_diff` | Inspect history. |
| `snapshot_timeline` | Mermaid `gitGraph` of the DAG. |
| `snapshot_revert` | Restore a snapshot's artifacts to disk. |
| `hx_snap_branch` | Name a branch ref at a snapshot. |
| `hx_snap_freeze` | Tag a snapshot immutable for publication. |
| `hx_snap_fork` | Export the full history as a portable bundle. |

`recall` deliberately returns references (id, title, tier, ~120-char
summary, score), never bodies; `hx_atlas_get` is the separate fetch. This
split keeps a search from flooding the model's context.

## Resources

Read-only, addressed by URI:

| Template | Contents |
|---|---|
| `atlas://{path}` | A page, with its frontmatter, by repo-relative path. |
| `snapshot://{project}/{snap_id}` | A snapshot's metadata as JSON. |
| `hot://{project}` | The project's hot-cache working state. |

## Prompts

Canonical workflows the user invokes by name:

| Prompt | Walks through |
|---|---|
| `helix_ingest` | Dropping files and ingesting the inbox. |
| `helix_run` | Driving the agent-driven run loop (you are the model). |
| `helix_lint` | An Atlas hygiene sweep and acting on each issue. |
| `helix_freeze` | The freeze-and-fork publication checklist. |
| `helix_resume` | Recovering context with the hot cache and history. |

## Safety posture

The tool set is curated and fixed — there is no general code-execution tool.
State-changing tools are confirmed by the client (the host's consent model)
before they run; promotion to a published tier additionally elicits an
explicit confirmation. All model-generated page and artifact content passes
the sandbox (`sanitize_atlas_writes`, `sanitize_code_artifacts`) before it
reaches disk, and model-controlled project / run / bundle names are confined
by `validate_project_name` at every filesystem path root (no separators,
no `..`).
