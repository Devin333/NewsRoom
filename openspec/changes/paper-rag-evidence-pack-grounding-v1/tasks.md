# Tasks

- [x] 1.1 Extend `EvidenceQAPair` with evidence-group and equivalent gold fields.
- [x] 1.2 Generate deterministic evidence groups for formula, figure, table, citation, and result QA.
- [x] 2.1 Report strict and equivalent retrieval coverage in benchmark/evidence reports.
- [x] 2.2 Pass equivalent gold ids into answer evaluation metadata.
- [x] 2.3 Add answer metrics for strict/equivalent context and citation coverage.
- [x] 3.1 Add focused tests for evidence-group generation and serialization.
- [x] 3.2 Add focused tests for equivalent answer grounding and failure reason behavior.
- [x] 3.3 Run focused/full RAG tests, OpenSpec validation, compile, and a real benchmark smoke.
- [x] 4.1 Hydrate answer-generation retrieval context from evidence packs after a same-group hit.
- [x] 4.2 Export evidence-pack expansion metadata in answer samples and context relationships.
- [x] 4.3 Add tests proving pack hydration does not inject gold evidence without a same-group hit.
- [x] 5.1 Add deterministic claim extraction and in-memory claim search for paper chunks.
- [x] 5.2 Connect claim-level search into citation retrieval without replacing strict chunk metrics.
- [x] 5.3 Export claim hit metadata and add claim index/retriever tests.
- [x] 6.1 Add Paper RAG answer diagnostics for true missing gold, equivalent support, primary/interpretation context gaps, and claim support.
- [x] 6.2 Add claim-support metrics to evidence reports, answer samples, scorecards, and promotion checklist.
- [x] 6.3 Add a multi-dataset benchmark matrix runner for held-out regression sets.
