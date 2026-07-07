## Why

`run_evidence_eval --live-answer-eval` currently imports `interfaces.services.paper_rag_service` from `business/research`, violating the business-to-interface dependency boundary guarded by architecture tests. This blocks CI smoke and risks normalizing interface dependencies inside business-owned evaluation tooling.

## What Changes

- Remove direct `interfaces` imports from `business/research/rag/cli/run_evidence_eval.py`.
- Keep live answer evaluation capable of converting gated Harness answer payloads into `EvidenceAnswerSample` rows.
- Build fixture-backed live answer evaluation from business-owned RAG session components when `--papers-dir` supplies chunks.
- Fail clearly when live answer evaluation is requested without fixture chunks or an injected ask callable.
- Add regression coverage so boundary tests and live-answer eval tests protect the dependency direction.

## Capabilities

### New Capabilities

### Modified Capabilities
- `architecture-boundary-governance`: Business-owned RAG evidence evaluation must not depend on `interfaces` when assembling live answer evaluation.

## Impact

- Affects `business/research/rag/cli/run_evidence_eval.py` and its unit tests.
- Preserves CLI flags and report output contracts for deterministic and fixture-backed live answer eval.
- Does not add workflow scheduling, docs restoration, tenant filter pushdown, transcript persistence, or supplemental budget changes in this P0 slice.
