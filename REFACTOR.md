# Refactor: MCP-native HELIX-v3

A re-architecture around the Model Context Protocol, simplifying the system
while implementing the HELIX-v3 design (Forge, Atlas, Snapshots). A clean
break: no migration of old data or snapshots.

> **Historical record.** This documents the v3 refactor. One decision below
> was later reversed: the **"Sampling-only"** model. Claude Code does not
> implement MCP sampling, so Helix is now **agent-driven** — the client
> agent answers each stage through the `hx_step` / `hx_submit` tool loop and
> the sampling path was removed. Read
> [docs/agent-driven-pipeline.md](docs/agent-driven-pipeline.md) for the
> current model; treat the sampling references below as superseded.

## What changed

**One drive surface.** The CLI, the LangGraph orchestrator, and the
Claude-Agent-SDK path are gone. A single stdio MCP server (`helix/mcp/`) is
the only way to drive Helix. The CLI is reduced to `helix init` (scaffold)
and `helix mcp` (launch the server).

**Sampling-only.** Helix holds no model credentials. Every model call is
delegated to the MCP client via `sampling/createMessage`; the client picks
the model and pays. The litellm/CLI-subprocess/local-model stack, the
provider/auth machinery, and `helix setup` were deleted.

**One orchestrator.** The plain loop is the only runner. The LangGraph
mirror, the `helix[sdk]` extra, and the dual-runner conformance test were
removed; routing still lives solely in `core.transitions.next_stage`.

**Forge.** A single `DecisionCard` is every agent's structured output (and
the snapshot digest). A run-scoped `Plan` replaces the `autonomy_until`
string and the gate callback plumbing (`autonomy_until` survives as a
constructor). A bounded run registry under `.helix/runs/` adds
status/events/plan-set without changing the synchronous HITL model. The
`hx_start` wizard runs setup through elicitation. The spend ceiling is
token/call based (sampling reports no cost).

**Atlas.** Pages carry typed YAML frontmatter (id/type/tier/aliases/
bi-temporal/provenance/links/embeddings), backward-tolerant so minimal
writes still work. Added `atlas/inbox/` + `.manifest.json` idempotent
ingest, a rebuildable SQLite link graph, optional `fastembed` embeddings,
auto-routing recall (lexical/semantic/graph/community) with a refs/fetch
split, label-propagation communities, a six-kind lint, tier promotion, and
a per-run hot cache.

**Snapshots.** The content-addressed DAG gained git-ops: branch, freeze,
and fork (a portable `forks/<name>.tar.gz` bundle). `checkout` is folded
into `resume_pipeline` / `snapshot_revert`.

**The client-IO seam.** `helix/io.py` is the single, standardized channel
for everything sent back to the client — sampling and elicitation — used
uniformly by model calls, HITL gates, the setup wizard, and tier promotion.

## What was removed

- LangGraph, litellm, the CLI-subprocess/local engines, and the
  Claude-Agent-SDK driver, with their extras and the conformance test.
- The provider/API-key/model-selection machinery and `helix setup`.
- The `autonomy_until` per-run field (now a run-scoped `Plan`).
- The USD cost ceiling (replaced by a token/call estimate).

## Hardening

Model-controlled strings that become filesystem paths (project / run /
bundle names) are confined by `sandbox.validate_project_name` at every path
root, alongside the existing content sandbox — closing a path-traversal
class found in security review.

## Why it is simpler

The system is materially smaller everywhere except the Atlas, where
complexity was deliberately concentrated. There is one orchestrator, no
model credentials, no heavy ML/orchestration dependencies in the core, and
one canonical page scan. `mcp` is the only mandatory runtime addition;
`fastembed` and `pymupdf` are optional extras. The test suite is run
end-to-end against a real in-memory MCP client.
