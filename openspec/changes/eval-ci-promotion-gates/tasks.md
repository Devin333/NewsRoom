## 1. CI Eval Gate

- [x] 1.1 Add a Paper RAG CI eval gate module that generates deterministic parsed-paper fixtures.
- [x] 1.2 Run the existing live retrieval evidence evaluator from the gate and enforce default retrieval thresholds.
- [x] 1.3 Write promotion gate JSON and Markdown artifacts, and include promotion failures in the exit status.

## 2. Command And CI Wiring

- [x] 2.1 Add a CLI entry point for the Paper RAG CI eval gate.
- [x] 2.2 Expose the gate as `python -m scripts.dev test-rag-eval-gate`.
- [x] 2.3 Add the RAG eval promotion gate step to `.github/workflows/ci.yml`.

## 3. Tests And Validation

- [x] 3.1 Add tests for gate success artifacts and threshold failure behavior.
- [x] 3.2 Add tests for developer command registration and CI workflow wiring.
- [x] 3.3 Run targeted tests, compile, strict OpenSpec validation, smoke, full tests, and strict all-change validation.
