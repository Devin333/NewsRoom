## 1. Alignment Metadata

- [x] 1.1 Add chunker helpers that normalize visual-region and caption-region metadata for figures and tables.
- [x] 1.2 Add explicit metadata fields for caption text, caption locator, caption match strategy, match confidence, and nearby context provenance.

## 2. Body Reference Linking

- [x] 2.1 Detect deterministic paragraph references such as `Figure 1`, `Fig. 1`, and `Table 2`.
- [x] 2.2 Attach `referenced_by_chunks` metadata to matching figure/table chunks without changing their source locators.

## 3. Tests

- [x] 3.1 Add unit coverage for cross-page figure references so body references do not overwrite figure location.
- [x] 3.2 Add unit coverage for table chunks preserving rows, caption metadata, and row-group linkage.

## 4. Verification

- [x] 4.1 Run focused chunker and visual chunk tests.
- [x] 4.2 Validate the OpenSpec change with `openspec validate paper-figure-table-alignment --strict`.
- [x] 4.3 Re-run a real paper parse/chunk sample and inspect figure/table metadata.
