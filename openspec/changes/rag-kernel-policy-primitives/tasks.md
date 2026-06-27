## 1. Kernel Policy Primitives

- [x] 1.1 Add `framework/rag/core/policy.py`
- [x] 1.2 Add intent allow-list helper
- [x] 1.3 Add section-distance position decay helper
- [x] 1.4 Add intent budget helper
- [x] 1.5 Export policy helpers from `framework/rag/core`

## 2. Research Wiring

- [x] 2.1 Rewire `RetrievalPolicy.position_weight()` to use kernel position decay
- [x] 2.2 Rewire `RetrievalPolicy.parent_budget_for()` to use kernel budget clamping
- [x] 2.3 Rewire reranker intent gates to use kernel allow-list helper
- [x] 2.4 Keep Paper-specific policy fields and named policy construction in Research

## 3. Verification

- [x] 3.1 Run `openspec validate rag-kernel-policy-primitives --strict`
- [x] 3.2 Run framework policy tests and Research retriever policy tests
- [x] 3.3 Run full RAG tests, compile, and boundary scans
