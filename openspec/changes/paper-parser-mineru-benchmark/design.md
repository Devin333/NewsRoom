# Design

## Approach

Add `MinerUPdfDocumentParser` as a `ResearchDocument` producer for raw PDF
bytes. It writes the PDF to `.newsroom/parser-runs/mineru/<paper_id>/input`,
runs a MinerU Docker command with GPU enabled, then converts MinerU JSON output
into the existing domain model.

PyMuPDF remains the source of page size normalization and PDF-point
`source_locator` values. The parser writes artifacts under the repository's
`.newsroom` directory by default so runtime files stay on the F drive workspace.

## Runtime

Default Docker image: `mineru:latest`

Default command shape:

```powershell
docker run --rm --gpus all `
  -v <input_dir>:/input `
  -v <output_dir>:/output `
  mineru:latest `
  mineru -p /input/input.pdf -o /output -b pipeline
```

Environment overrides:

- `NEWSROOM_MINERU_DOCKER_IMAGE`
- `NEWSROOM_MINERU_DOCKER_ARGS`
- `NEWSROOM_MINERU_TIMEOUT_SECONDS`
- `NEWSROOM_PARSER_RUN_ROOT`

## Conversion

- `content_list.json` is the primary MinerU source.
- `text` blocks become sections, using `text_level` for hierarchy.
- `equation` blocks become equations.
- `image` / `chart` blocks become figures.
- `table` blocks become tables.
- `page_idx` is converted from zero-based to one-based page numbers.
- bbox values are converted from MinerU normalized/1000 coordinates to PDF
  points and embedded in `source_locator`.
