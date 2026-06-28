## 1. Kernel Generation Contracts

- [x] 1.1 Add `framework/rag/generation/contracts.py`
- [x] 1.2 Add `GeneratedRAGAnswer` and `RAGGenerationContext`
- [x] 1.3 Add `framework/rag/generation/grounding.py`
- [x] 1.4 Add numbered context prompt builder
- [x] 1.5 Add bracket citation index parser
- [x] 1.6 Export generation helpers from `framework/rag/generation`

## 2. Research Wiring

- [x] 2.1 Rewire `AnswerGenerator._build_prompt()` to use kernel prompt builder
- [x] 2.2 Add kernel answer projection for Research `GeneratedAnswer`
- [x] 2.3 Keep Paper-specific context selection and LLM call orchestration in Research

## 3. Verification

- [x] 3.1 Run `openspec validate rag-kernel-generation-contracts --strict`
- [x] 3.2 Run framework generation tests and Research generator tests
- [x] 3.3 Run full RAG tests, compile, and boundary scans
