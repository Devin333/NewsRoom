## Why

Real-corpus live answer evaluation consumes parsed `research_document.json` artifacts from `.newsroom/papers`. `ChunkPaperPipeline` currently writes that artifact only when visual descriptions are enabled, so ordinary corpus ingestion can index chunks successfully while leaving the live answer eval without parsed document artifacts.

## What Changes

- Persist `research_document.json` for every successful `ChunkPaperPipeline.run`.
- Keep visual-description enrichment in the persisted document when a visual describer is configured.
- Expose the persisted document path in `ChunkPipelineResult`.
- Add regression coverage for the non-visual ingestion path.

## Impact

- Affected code: `business/research/application/chunk_paper_pipeline.py`.
- Affected tests: `tests/business/research/application/test_chunk_paper_pipeline.py`.
