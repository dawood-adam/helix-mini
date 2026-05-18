# Pipeline and agents

The pipeline is six stages run in order. Each stage is an agent defined by a
markdown file. A gate runs after every stage so you stay in control. Five
stages call an LLM; the Validator is deterministic and calls none.

## The stages

| Stage | Reads | Produces | LLM? |
|---|---|---|---|
| Scout | the source folder + the existing Atlas index | candidate approaches, source pages | yes |
| Methods Critic | Atlas context + the candidate approaches | a critique and a chosen approach | yes |
| Planner | Atlas context + the chosen approach | a validation plan with numeric bands | yes |
| Builder | the plan, approach, prior artifacts + feedback | artifact files and result metrics | yes |
| Validator | the plan's bands + the Builder's metrics | pass, or `HARD:`/`SOFT:` flags | no |
| Results Critic | the results, plan, artifacts, flags | a verdict: ship / iterate / abandon | yes |

**Scout** ingests every file in the project folder (text and PDF), copies the
originals to `raw/`, and reads the existing Atlas index so earlier projects
inform this one. It summarizes each source, proposes two or three candidate
approaches, and writes one Atlas source page per file.

**Methods Critic** evaluates each candidate approach for feasibility, novelty,
and risk, assigns a severity, and recommends one. That choice carries through
the rest of the run.

**Planner** designs a concrete validation plan: steps, success criteria, and
`validation_bands` — a map of metric to `{min, max}`. Those bands are the
contract the Validator checks later, so the plan defines what "correct" means
before any code is written. It writes a plan page to the Atlas.

**Builder** implements the plan. On a re-run it also receives the prior
artifacts, the reviewer feedback, the Validator flags, and any human feedback
aimed at it, and revises in place. It emits artifact files and result metrics.
Every artifact path is sandbox-validated before it is written *or* stored, so
a malformed or traversal path can never reach disk or a snapshot.

**Validator** is deterministic: no LLM, no cost. It walks the Builder's
reported metrics and, for each metric named in the plan's `validation_bands`,
coerces the value to a float and checks it falls within `[min, max]`. Out of
range raises a `HARD:` flag; a non-numeric value raises a `SOFT:` flag. That
is the whole job — a numeric bounds check against the contract the Planner
declared. It deliberately does **not** judge whether the results are *good*;
that is the Results Critic. The point of a non-LLM stage here is to have a
free, mechanical tripwire that catches gross numeric failures and routes back
to the Builder before an LLM call is spent on the Results Critic. A `HARD:`
flag is an automatic send-back to the Builder (carrying the flags as
feedback) when running unattended, or it surfaces in the gate report when you
are reviewing.

**Results Critic** reads the results, plan, artifact descriptions, and
Validator flags, then returns an assessment and a verdict: ship, iterate, or
abandon. It writes the project's overview page. `iterate` is a send-back to
the Builder; `ship` and `abandon` end the run.

## Gates, review, and autonomy

A gate runs after every stage. The decision is always one of three:

- **proceed** to the next stage,
- **go back to any earlier stage** with a note (the note is stored in
  `state.human_feedback` and injected into that stage's prompt on re-run),
- **stop**.

There is no iteration cap; you can send a run around the loop as many times
as you want. `autonomy_until` controls how much of this is automatic: empty
means ask at every gate, a stage name auto-proceeds the gates before it, and
`END` runs fully unattended. It is chosen per run and can change on a resume.

Cycling is unbounded by design; the only limit is the cost and call ceiling
in `helix.toml [limits]`. Reaching it never crashes the run or loses work —
interactively you are asked to continue or stop, unattended it snapshots and
stops with a resume command.

For the day-to-day experience of driving these gates, see
[usage.md](usage.md).

## Agents are markdown files

Each stage has one file. Defaults ship in `helix/builtin_agents/`. To change a
stage's behavior, edit its prompt — no code change, no restart.

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
stage's response mapper expects (`_MAP` in `helix/core/agents.py`).

**Override a stage for one project:**

```bash
mkdir -p my-research/agents
python -c "import helix, os; print(os.path.dirname(helix.__file__))"
# copy builtin_agents/planner.md from that path into my-research/agents/,
# edit it; Helix uses the project copy automatically for that project only
```

**What stays in code, and why.** The markdown owns what you tune: the role,
the prompt, the output contract, and whether the stage writes to the Atlas.
Two things stay in Python in `helix/core/agents.py`, keyed by stage: context
assembly (which Atlas query to run and which state fields to format) and
response mapping (turning the JSON reply into state updates). These are
data-dependent logic; making them declarative would add complexity, not
remove it.

**Deterministic stages.** A stage with `kind: deterministic` (the Validator)
calls no LLM and costs nothing. Its markdown documents the stage; execution
dispatches to a function registered in `_DETERMINISTIC`. Use this for pure
computation rather than forcing it through a model.

**Feedback on re-runs.** When a gate sends the run back to a stage, your note
is added to `state.human_feedback`. Every agent's context builder injects the
notes aimed at its stage under a "Human feedback" heading, so a re-run sees
exactly what you asked for. Custom agents get this automatically.
