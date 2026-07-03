## Why

The enterprise RAG review identified missing proof for two safety-critical regressions: content-derived evidence typing must prevent method-only evidence from satisfying an experiment requirement, and golden/gated evaluation must explicitly cover expected abstention. These are mostly validation gaps, but they protect the production RAG loop from returning truthful-looking answers on the wrong evidence type.

## What Changes

- Add a business integration regression that routes Paper chunks through `PaperChunkRetrievalPort`, the kernel adapter, content-derived evidence typing, and the bounded Harness RAG controller.
- Prove that `required_evidence_types=["experiment"]` with only method content returns `INSUFFICIENT_EVIDENCE`.
- Add a golden-set compatibility regression proving legacy golden rows load with `expected_behavior="answer"`.
- Add a gated paper RAG service regression that drives an `expected_behavior="abstain"` golden case through the service contract and verifies an abstained payload with no answer text.

## Capabilities

### New Capabilities
- `evidence-convergence-regression-tests`: Regression coverage for evidence-type convergence and expected-abstention golden/gated behavior.

### Modified Capabilities

## Impact

- Affected tests: business research integration, paper RAG service, and evidence eval golden loading.
- Affected fixtures: small test-only golden cases; no production runtime behavior change is intended.
