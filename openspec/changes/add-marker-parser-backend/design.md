## Context

PRD 16 selected a parser cascade of MinerU first, Marker fallback, and PyMuPDF text fallback. The repository already has Docker-backed MinerU parsing and Docker helper utilities, while Marker exists only as a `ParseSource` literal and as a historical bake-off label.

Marker's CLI can emit JSON/Markdown artifacts and image files into an output directory. The NewsRoom ingestion path needs a normalized `ResearchDocument`, not raw Marker artifacts, so this change adds an adapter that translates common Marker block/page shapes into the same domain objects used by MinerU and Nougat.

## Goals / Non-Goals

**Goals:**

- Make `marker` selectable anywhere `nougat` and `mineru` are selectable for PDF parsing.
- Reuse the existing Docker parser staging and locator utilities.
- Convert common Marker section/text, equation, image/figure, and table blocks into `ResearchDocument`.
- Preserve parser artifacts and parser warnings in document metadata for bake-off analysis.

**Non-Goals:**

- Do not implement parser cascade selection in this change.
- Do not tune Marker quality thresholds or choose Marker as the default parser.
- Do not require real Marker Docker execution in unit tests.

## Decisions

- **Docker-only host integration:** Use a configurable Docker image (`NEWSROOM_MARKER_DOCKER_IMAGE`, default `marker:latest`) and run `marker_single /input/input.pdf --output_format json --output_dir /output`. This matches MinerU's isolation model and avoids adding heavy host dependencies.
- **Tolerant artifact discovery:** Locate JSON from known names and recursive `*.json`, and use Markdown only as a fallback when JSON is unavailable. Marker versions can vary their file names, so the adapter should fail only when no parse artifact exists.
- **Common block normalization:** Parse a broad set of page/block keys (`type`, `block_type`, `block_type`, `html`, `markdown`, `children`, `bbox`, `polygon`, `page_id`, `page_idx`) rather than binding to one internal Marker version.
- **Image preservation:** Copy image/table assets referenced by Marker into the per-paper artifact directory, following MinerU's layout under `.newsroom/papers/<paper_id>/`.

## Risks / Trade-offs

- **Marker JSON schema drift** -> The parser accepts several common shapes and stores compact raw block metadata in `marker_block` for diagnosis.
- **Large JSON files** -> The parser extracts text and metadata in one pass and copies only referenced assets.
- **Locator mismatch** -> Bounding boxes are converted through the shared Docker PDF utilities and page rects, with missing bbox still producing page-level locators.
