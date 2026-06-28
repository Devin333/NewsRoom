## Why

The PRD calls for `framework/rag/retrieval/expansion.py`, but Research still owns the standard expansion metadata keys inline. The concrete expansion rules for tables, formulas, page visuals, and parent context are Paper-specific, but the metadata convention for describing an expansion edge is reusable across RAG adapters.

## What Changes

- Add `framework/rag/retrieval/expansion.py`.
- Introduce `ExpansionMetadata` and `expansion_metadata()` for standard expansion provenance fields.
- Rewire Research `_with_expansion_metadata()` to use the kernel helper while preserving the existing metadata key names.
- Keep Paper-specific expansion rules in Research.
- Add framework unit tests for expansion metadata serialization and validation.

## Capabilities

### New Capabilities

- `rag-kernel-expansion-metadata`: domain-neutral expansion provenance metadata contract.

### Modified Capabilities

- `paper-rag-expansion-metadata-migration`: Paper expansion metadata uses the kernel contract while keeping Paper expansion logic in Research.

## Impact

Affected code is limited to `framework/rag/retrieval`, one Research metadata helper, tests, and this OpenSpec change. Existing table/formula/visual/parent expansion behavior and output keys remain compatible.
