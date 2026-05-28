# Open Reader Rendering

Use this reference when editing `frontend/src/components/papers/open-reader/`, `frontend/src/lib/paper-reader/`, or BFF document/asset routes.

## Body Source

The body source is `PaperDocument.blocks` from a compiled backend artifact. Do not use AI summaries, legacy reader sections, method signals, experiment signals, or related paper payloads as body substitutes.

## Full-Screen Reader

The formal reader should feel like the previous Open Reader:

- no outer Research/Header bar,
- dense reading layout,
- outline/navigation inside the reader,
- AI panel auxiliary, not the main article,
- source preview available from block/asset source bbox.

## Visual Rendering

- Figure/table cards render from manifest asset URLs.
- Table images may use full available width.
- Figure images should use intrinsic aspect ratio and max dimensions.
- Equation blocks render through KaTeX via `EquationRenderer`.
- Equation fallback is plain text, not an image.

## Status Rendering

For non-compiled states:

- show compile status and diagnostics,
- show manual/background actions if available,
- do not show legacy `sections[]` as article body,
- do not show generated summaries as article body.

## Interaction Targets

Reader events must include typed targets:

- `paragraph`: block id and source bbox,
- `figure`: block id, asset id, source bbox,
- `table`: block id, asset id, source bbox,
- `equation`: block id and source bbox.
