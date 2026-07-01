# Design

## Approach

Add `MarkerPdfDocumentParser` as a `ResearchDocument` producer for raw PDF
bytes. It writes the PDF to `.newsroom/parser-runs/marker/<paper_id>/input`,
runs a project-local Marker Docker image with GPU enabled, then converts Marker
JSON output into the existing domain model.

PyMuPDF remains the source of page size normalization and PDF-point
`source_locator` values. Runtime files stay under the repository `.newsroom`
tree by default so parser artifacts are placed on the F drive workspace.

## Runtime

Default Docker image: `newsroom-marker:latest`

Default command shape:

```powershell
docker run --rm --gpus all `
  -e TORCH_DEVICE=cuda `
  -v <input_dir>:/input `
  -v <output_dir>:/output `
  newsroom-marker:latest `
  marker_single /input/input.pdf --output_format json --output_dir /output --paginate_output --debug
```

Environment overrides:

- `NEWSROOM_MARKER_DOCKER_IMAGE`
- `NEWSROOM_MARKER_DOCKER_ARGS`
- `NEWSROOM_MARKER_TIMEOUT_SECONDS`
- `NEWSROOM_PARSER_RUN_ROOT`

## Conversion

- Marker JSON is the primary source.
- `SectionHeader` blocks define section boundaries.
- `Text` / `TextInlineMath` blocks become paragraph text in sections.
- `Equation` blocks become equations.
- `Figure` / `FigureGroup` / `Picture` / `PictureGroup` blocks become figures.
- `Table` / `TableGroup` blocks become tables.
- `page` and `polygon` values become one-based page and PDF-point `pdf_rect`.
