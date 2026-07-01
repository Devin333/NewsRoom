# Paper RAG Answer Faithfulness Calibration V1

## Why

Paper RAG already reports deterministic answer success and gold evidence quality, but answer-level trust still needs finer diagnostics. A promoted benchmark should show whether generated claims are supported, whether citations point to the right evidence, and whether LLM judge outcomes agree with human spot checks.

## What Changes

- Add structured claim-level answer judge output.
- Add citation grounding diagnostics for generated answer claims.
- Extend human spot-check annotation summaries with answer, faithfulness, citation, retrieval, and context quality fields.
- Add judge-human calibration metrics and conflict artifacts.
- Write answer judge failure artifacts and an answer fix manifest.
- Surface the new metrics in suite and matrix reports.

## Out Of Scope

- Training a new judge model.
- Word-level hallucination labeling.
- Automatic repair of answers, gold evidence, or retrieval policy.
- A frontend annotation workflow.
