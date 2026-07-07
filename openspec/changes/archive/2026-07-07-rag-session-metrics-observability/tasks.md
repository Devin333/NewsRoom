## 1. Framework Metrics

- [x] 1.1 Add `RAGSessionMetrics` and a deterministic builder.
- [x] 1.2 Attach metrics to `RAGSessionResult` and its serialization.
- [x] 1.3 Export metrics types from RAG harness packages.

## 2. Service Exposure

- [x] 2.1 Include bounded session metrics in gated paper RAG service responses.
- [x] 2.2 Preserve existing response metric keys for callers.

## 3. Tests And Validation

- [x] 3.1 Add framework tests for answered and abstained/supplemental metrics.
- [x] 3.2 Add service payload coverage for gated metrics.
- [x] 3.3 Run targeted tests, compile, and strict OpenSpec validation.
