## Context

The live answer pipeline normalizes generated context-absence text into Harness abstentions before answer gates return payloads. The answer evaluator independently detects abstention phrases for expected-abstain scoring. These marker sets must stay aligned; otherwise a semantically correct refusal can appear as `abstention_wrong`, or runtime may return a negative-QA refusal as a normal answer candidate.

Recent real-corpus live eval output showed two unrecognized variants:

- "The provided context does not state ..."
- "The provided context contains no mention ..."

Both are context-absence abstentions and should be handled consistently.

## Goals / Non-Goals

**Goals:**
- Treat common "does not state" and "contains no mention" context-absence phrases as abstentions.
- Keep runtime normalization and evaluator scoring aligned.
- Preserve existing answer gate strictness and negative QA behavior.

**Non-Goals:**
- Do not change retrieval ranking, generation prompts, or answer gate thresholds.
- Do not classify arbitrary "no" answers as abstentions unless they match explicit context-absence language.
- Do not tune live eval thresholds.

## Decisions

- Add the new markers to both runtime and evaluation marker lists. This keeps `PaperAnswerWorker` and answer metrics from disagreeing about the same generated text.
- Add tests at both layers: adapter tests prove the production candidate becomes a Harness abstention; evaluator tests prove negative QA scoring treats those phrases as correct abstentions.

## Risks / Trade-offs

- Marker expansion can hide substantive negative answers -> Mitigated by requiring explicit context-absence wording such as "provided context" plus absence verbs or "contains no mention".
- Duplicated marker lists may drift again -> Mitigated by unit tests covering the newly observed variants at both runtime and evaluation layers.
