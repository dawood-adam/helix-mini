# Authoring agents

Each pipeline stage is a markdown file: YAML frontmatter + a system-prompt
body. Builtins ship in `helix/builtin_agents/`. A project overrides any stage
by adding `<project>/agents/<stage>.md` — **no code change, no restart**.

## Format

```markdown
---
name: scout
order: 1            # pipeline position (stage order is derived from this)
kind: llm           # llm | deterministic
model_stage: scout  # key passed to ModelConfig.model_for_stage
atlas_write: true   # may this stage write Atlas pages?
snapshot: after
---
You are a research scout. ...
Respond with JSON:
{ "source_summaries": [...], "approaches": [...], "atlas_writes": [...] }
```

The body is the system prompt. The JSON shape you ask for must match what the
stage's response mapper expects (see `helix/core/agents.py` — `_MAP`).

## What stays in code, and why

Per-stage **context assembly** (which Atlas query, which state fields, how to
format them) and **response mapping** (JSON → state) are data-dependent Python
in `core/agents.py`, table-keyed by stage. The markdown owns the role, the
prompt, the output contract, and the Atlas-write policy — the parts you
actually tune. This is deliberate: making context assembly "declarative" would
be more complex, not less.

## Deterministic stages

`kind: deterministic` agents (e.g. `validator`) never call an LLM and cost
nothing. The markdown documents the stage; execution dispatches to a function
registered in `core/agents.py` (`_DETERMINISTIC`). Use this for pure
computation — don't force it through a model.

## Feedback

When a gate sends the run back to a stage, the human's note is added to
`state.human_feedback` and every agent's context builder injects the notes
targeting its stage under a "Human feedback — address this" heading. Custom
agents get this automatically via `_feedback_block`.

## Override example

```bash
mkdir -p my-research/agents
cp $(python -c "import helix,os;print(os.path.dirname(helix.__file__))")/builtin_agents/planner.md \
   my-research/agents/planner.md
# edit my-research/agents/planner.md — used automatically for that project
```
