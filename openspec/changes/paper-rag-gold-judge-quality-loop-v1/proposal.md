# Paper RAG Gold Judge Quality Loop V1

## Why

The Paper RAG held-out benchmark matrix passes promotion, but blind semantic datasets still emit `blind_semantic_without_gold_judge`. Deterministic gold evidence is useful, yet promotion needs a gold-quality audit layer so benchmark trust does not depend only on generated structure.

## What Changes

- Add matrix-level gold judge and answer judge configuration passthrough.
- Stratify gold judge samples by QA type and prioritize high-risk gold audit items.
- Add structured human spot-check annotation summaries.
- Add gold quality checks to the policy promotion checklist.
- Write judge warning/failure fix artifacts for later gold repair.

## Out Of Scope

- Replacing deterministic gates with LLM judges.
- Training a judge model.
- Automatically changing gold evidence from judge output.
- Requiring full human annotation before benchmark execution.
