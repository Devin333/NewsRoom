# Publication Gates

Use this reference when editing `asset_gate.py`, compile orchestration, status transitions, reviewer logic, or API publication behavior.

## Status Rules

- `GET document` reads existing artifacts only. It must not compile on demand.
- Only `status == "compiled"` returns article-body blocks to the formal reader.
- `queued`, `compiling`, `needs_review`, `compile_failed`, and `review_failed` must not expose pseudo-body content.
- Manual compile and worker compile must use the same application service path.

## Asset Gate Hard Errors

Block publication when any of these occur:

- referenced asset is missing from manifest,
- image file is missing or outside the paper directory,
- checksum mismatch,
- invalid width/height,
- excessive blankness,
- missing source bbox,
- missing label/caption for figure/table,
- figure/table block missing `assetId`,
- equation block has `assetId`,
- equation block has missing or paragraph-like text,
- repeated figure/table labels indicate over-segmentation.

## AI Review Rules

- Review runs after deterministic Gate success.
- Review cannot override Gate hard errors.
- Review unavailable or non-pass verdict blocks publication.
- Review diagnostics are auxiliary metadata, not body blocks.

## Real Data Rule

Implementation paths must use real paper/PDF data. Tests may use synthetic PDFs to cover edge cases cheaply.
