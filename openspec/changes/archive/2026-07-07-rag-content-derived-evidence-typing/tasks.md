## 1. Framework Resolver

- [x] 1.1 Add `EvidenceTypeResolver` and `MetadataKeyEvidenceTypeResolver` under `framework/harness/rag`.
- [x] 1.2 Update `KernelRAGRetrieverHarnessAdapter` to resolve evidence type per retrieved item and annotate `evidence_type_source`.
- [x] 1.3 Export resolver symbols from `framework/harness/rag/__init__.py`.

## 2. Research Mapping

- [x] 2.1 Add Research-owned evidence type mapping and resolver builder under `business/research/rag`.
- [x] 2.2 Wire `PaperChunkRetrievalPort` to pass the Research resolver into the Harness kernel adapter.

## 3. Tests

- [x] 3.1 Add framework tests for metadata-key resolver behavior and adapter provenance states.
- [x] 3.2 Add Research tests for Paper evidence type mapping and preserved structural metadata.
- [x] 3.3 Add Paper retrieval port coverage proving request labels no longer override content-derived types.

## 4. Validation

- [x] 4.1 Run targeted framework and Research RAG tests.
- [x] 4.2 Run compile and strict OpenSpec validation.
- [x] 4.3 Commit the completed T1 slice.
