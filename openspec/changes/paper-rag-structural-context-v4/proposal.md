# Paper RAG Structural Context V4

## Why

Paper RAG already expands some figure/table/formula references during retrieval, but answer generation still receives a flat list of chunks. This makes it hard to tell which chunk is the primary evidence, which chunks explain or interpret it, and which locator/image metadata should be used by the reader or answer evaluator.

## What Changes

- Add explicit answer-context roles for `primary_evidence` and `interpretation_context`.
- Add `locator_context` metadata for selected context chunks, including `source_locator`, `caption_source_locator`, `image_ref`, page, and bbox fields when available.
- Render expanded field texts such as `table_rows`, `table_columns`, `visual_description`, and `referenced_text` into generation contexts.
- Preserve existing retrieval expansion behavior and default retrieval policy.
- Add focused tests for figure/table/formula context assembly.

## Out Of Scope

- Changing the default retrieval policy.
- Adding a new reranker or tuning reranker weights.
- Replacing the benchmark answer evaluator.
