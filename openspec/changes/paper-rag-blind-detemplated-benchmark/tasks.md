## 1. Benchmark Protocol

- [x] 1.1 Add a `blind_detemplated` question profile to Paper RAG golden-set generation.
- [x] 1.2 Ensure de-templated questions avoid direct table/figure/equation labels and long caption/claim copy.
- [x] 1.3 Preserve original template questions in metadata for auditability.

## 2. CLI and Reports

- [x] 2.1 Expose question profile selection in `run_benchmark_suite`.
- [x] 2.2 Write question-profile metadata into benchmark reports and generated golden sets.
- [x] 2.3 Keep existing template benchmark behavior unchanged by default.

## 3. Verification

- [x] 3.1 Add unit tests for de-templated question generation and report protocol output.
- [x] 3.2 Run targeted Paper RAG tests.
- [x] 3.3 Run a real benchmark with `blind_detemplated` profile.
