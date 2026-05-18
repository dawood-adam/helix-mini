# Agents

An agent is a markdown file. Each pipeline stage has one: YAML frontmatter
plus a system prompt. The defaults ship in `helix/builtin_agents/`. To change
a stage's behavior, edit its prompt — no code change, no restart.

## Format

```markdown
---
name: scout
order: 1            # position in the pipeline; stage order derives from this
kind: llm           # llm or deterministic
model_stage: scout  # the key passed to ModelConfig.model_for_stage
atlas_write: true   # may this stage write Atlas pages?
snapshot: after
---
You are a research scout. ...
Respond with JSON:
{ "source_summaries": [...], "approaches": [...], "atlas_writes": [...] }
```

The body is the system prompt. The JSON you ask for must match what the
stage's response mapper expects (see `_MAP` in `helix/core/agents.py`).

## Override a stage for one project

```bash
mkdir -p my-research/agents
python -c "import helix, os; print(os.path.dirname(helix.__file__))"
# copy builtin_agents/planner.md from that path into my-research/agents/
# edit it; Helix uses the project copy automatically for that project only
```

## What lives in code, and why

The markdown owns the parts you tune: the role, the prompt, the output
contract, and whether the stage writes to the Atlas.

Two things stay in Python, in `helix/core/agents.py`, keyed by stage:

- **Context assembly** — which Atlas query to run and which state fields to
  format into the prompt.
- **Response mapping** — turning the JSON reply into state updates.

These are genuinely data-dependent logic. Making them "declarative" would add
complexity, not remove it, so they stay as small, table-keyed functions.

## Deterministic stages

A stage with `kind: deterministic` (the Validator) calls no LLM and costs
nothing. Its markdown documents the stage; execution dispatches to a function
registered in `_DETERMINISTIC` in `helix/core/agents.py`. Use this for pure
computation rather than forcing it through a model.

## Feedback on re-runs

When a gate sends the run back to a stage, your note is added to
`state.human_feedback`. Every agent's context builder injects the notes aimed
at its stage under a "Human feedback" heading, so a re-run sees exactly what
you asked for. Custom agents get this automatically.
