## 1. Report Context Wiring

- [x] 1.1 Add optional report context provider support to `BoardOutputPipeline`.
- [x] 1.2 Resolve report topic/run metadata and call the provider with a bounded request.
- [x] 1.3 Project retrieved context into report metadata and a report evidence section.
- [x] 1.4 Degrade safely when no provider exists or provider recall fails.

## 2. Tests And Validation

- [x] 2.1 Add output layer tests for successful context projection and failure diagnostics.
- [x] 2.2 Run targeted tests, OpenSpec strict validation, compile, smoke, all OpenSpec strict validation, and diff checks.
