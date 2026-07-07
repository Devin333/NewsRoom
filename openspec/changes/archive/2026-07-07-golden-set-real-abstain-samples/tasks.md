## 1. Specification

- [x] 1.1 Validate the OpenSpec change artifacts.

## 2. Golden Set Data

- [x] 2.1 Add explicit `expected_behavior` labels to repository answer rows.
- [x] 2.2 Add at least 10 curated repository `abstain` samples across existing domains.

## 3. Build Entry Point

- [x] 3.1 Update `data/eval/build_golden_set.py` to use the current evidence golden set builder and serializer.

## 4. Tests

- [x] 4.1 Update repository golden set regressions to require answer and abstain behavior counts.
- [x] 4.2 Add coverage for the repaired build script import/argument path.
