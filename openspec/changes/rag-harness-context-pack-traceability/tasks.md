## 1. Traceability Contracts

- [x] 1.1 Add `artifact_refs` to `EvidenceCandidate`
- [x] 1.2 Add `artifact_refs` and `evidence_trace` to `RAGContextPack`
- [x] 1.3 Preserve artifact refs through `EvidenceCandidate.to_evidence_pack()`

## 2. Assembly and Session Wiring

- [x] 2.1 Project artifact refs from kernel `RAGEvidence` metadata
- [x] 2.2 Preserve retrieval request artifact refs on evidence candidates
- [x] 2.3 Include pack-level evidence trace and artifact refs in context envelope metadata
- [x] 2.4 Keep existing Harness routing and gates unchanged

## 3. Verification

- [x] 3.1 Run `openspec validate rag-harness-context-pack-traceability --strict`
- [x] 3.2 Run focused Harness RAG traceability tests
- [x] 3.3 Run full RAG pytest coverage, compile, and boundary scans
