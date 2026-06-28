## 1. Kernel Nearby Context

- [x] 1.1 Add `framework/rag/context/nearby_context.py`
- [x] 1.2 Add direct metadata edge collection
- [x] 1.3 Add parent id and optional plain reference collection
- [x] 1.4 Add referenced-by list edge collection
- [x] 1.5 Export nearby context helpers from `framework/rag/context`

## 2. Research Wiring

- [x] 2.1 Rewire `AnswerContextAssembler` related context id extraction to use kernel helper
- [x] 2.2 Keep Paper-specific context selection ordering and chunk lookup in Research

## 3. Verification

- [x] 3.1 Run `openspec validate rag-kernel-nearby-context --strict`
- [x] 3.2 Run framework nearby context tests and Research generator tests
- [x] 3.3 Run full RAG tests, compile, and boundary scans
