---
name: paper-reader-source-comparison
version: "1.0.0"
description: >-
  Validate Research Reader compiled paper output against native paper/source
  evidence before publishing to readers, and record reusable lessons for future
  layout improvements.
category: quality
tags:
  - research-reader
  - paper
  - source-comparison
  - visual-assets
  - memory
allowed_tools:
  - source_fetcher
  - pdf_parser
  - llm
  - memory
risk_level: high
owner: paper-radar
quality_gates:
  - source_traceable
  - visual_assets_complete
  - memory_lesson_recorded
---

# Paper Reader Source Comparison

## Purpose

Ensure the Research Reader shows a faithful paper: real paper metadata, source/native paper content, complete figures/tables, and no reader-visible content fabricated from summaries or review text.

## When to Use

Use after a paper has been fetched from its source site and compiled into a reader document, and before publishing that compiled document to readers.

## Inputs

Use the real paper metadata, source PDF URL, native source package when available, compiled `PaperDocument`, `PaperAssetManifest`, `PaperCompileInfo`, and deterministic asset gate output.

## Method

Prefer source-package parsing when available. Use AI or layout models only to improve layout detection, crop selection, equation recovery, or reader structure. Treat the native PDF/source package as the authority for content, source coordinates, figure/table assets, and page references.

Compare the compiled output against native-source invariants:

- Every reader body block has a valid source region.
- Every figure/table block references an existing manifest asset of the same kind.
- Every figure/table asset appears in a reader block.
- Reader text is grounded in native PDF/source text, with coverage metrics recorded.
- The native source PDF is stored and page assets exist for source previews.
- The compiled document, manifest, and compile info share paper id and source hash.
- AI review findings are diagnostic only; they do not block publication when source comparison passes.

## Outputs

Produce a source comparison report with metrics, hard errors, warnings, and lessons. Publish only when hard errors are empty. Store lessons as memory evidence, publication decisions, and engineering-practice events. When the central memory backend is unavailable, keep a local replayable memory journal beside the comparison report.

## Failure Modes

Block publication when body content is empty, reader text is not grounded in the native paper, source coordinates are invalid, source PDF references are missing, figure/table assets are missing or unbound, or document/manifest/source hashes disagree.

Do not block publication solely because AI review is unavailable or returns a non-approval verdict; keep that result as a warning for later improvement.
