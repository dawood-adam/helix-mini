---
name: validator
order: 5
kind: deterministic
model_stage: validator
atlas_write: false
snapshot: after
---
Deterministic stage — no LLM, no cost. Checks each experiment result against
the plan's `validation_bands`: a numeric value outside its band raises a
`HARD:` flag; a non-numeric value raises a `SOFT:` flag. Hard flags route the
pipeline back to the builder (with the flags fed in as contextualized
feedback). Implemented by the registered `validator` function, not a prompt;
this file documents the stage and keeps the pipeline uniform.
