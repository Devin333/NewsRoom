## Why

Research Reader should present a faithful paper, not a quality-gate artifact. The current visual compiler still treats AI review as a publication gate after deterministic asset validation. That conflicts with the intended flow: fetch real metadata/source content, let AI/layout tooling improve the reading layout, compare the compiled reader document with the native paper/source, and continuously learn from those comparisons.

## What Changes

- Add a deterministic source-comparison stage after visual compilation and asset validation.
- Publish only when the compiled `PaperDocument` is traceable to the native paper/source and has no hard content or visual asset failures.
- Keep AI review as auxiliary diagnostics. AI review may warn, but it SHALL NOT block publication.
- Persist a source comparison report artifact and expose it through compile status/document diagnostics.
- Convert source-comparison findings into memory evidence, decisions, and events so repeated layout/content failures become reusable learning signals.
- Add a reusable reader-source-comparison skill document that captures the operating rules for future compiler improvements.

## Capabilities

### Modified Capabilities
- `paper-visual-compiler-runtime`: publication is controlled by deterministic source comparison and asset integrity rather than AI review.

### New Capabilities
- `paper-reader-source-compare-evolution`: source/native comparison reports, memory ingestion, and reusable learned practices for Research Reader fidelity.

## Impact

- Visual compiler service and repository under `interfaces/services` and `business/boards/paper_radar/visual_compiler`.
- Paper Reader compiler tests and reader feedback/memory tests.
- Stored visual compiler artifacts now include `source-comparison-report.json`.
- No public route shape changes; existing document, compile-status, asset, and source-preview APIs continue to work.
