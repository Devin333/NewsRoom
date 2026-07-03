## 1. Taxonomy

- [x] 1.1 Update Paper RAG answer failure classification to emit `abstained_over_conservative` for answerable abstentions.
- [x] 1.2 Preserve `abstention_wrong` for expected-abstain samples that produce an answer.

## 2. Reporting

- [x] 2.1 Ensure benchmark reason counts and fix manifests retain `abstained_over_conservative`.
- [x] 2.2 Add focused regression tests for both abstention failure directions.

## 3. Verification

- [x] 3.1 Validate the OpenSpec change.
- [x] 3.2 Run targeted RAG evaluation tests and compile checks.
