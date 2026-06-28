## 1. Kernel Stable IDs

- [x] 1.1 Add `framework/rag/core/ids.py`
- [x] 1.2 Add stable RAG id generation
- [x] 1.3 Add normalized semantic text and content fingerprint helpers
- [x] 1.4 Add chunk semantic key helper with explicit parts
- [x] 1.5 Export id helpers from `framework/rag/core`

## 2. Research Wiring

- [x] 2.1 Rewire Research chunker stable chunk ids and semantic keys to use kernel helpers
- [x] 2.2 Rewire chunk manifest fallback ids and semantic-key generation to use kernel helpers
- [x] 2.3 Rewire page visual chunk ids and fixed-window baseline ids to use kernel helpers
- [x] 2.4 Keep Paper-specific manifest storage, remapping, metadata, and source locator choices in Research

## 3. Verification

- [x] 3.1 Run `openspec validate rag-kernel-stable-ids-migration --strict`
- [x] 3.2 Run framework id tests and Research chunking/RAG tests
- [x] 3.3 Run full RAG tests, compile, and boundary scans
