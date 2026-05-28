---
name: paper-visual-compiler-guardrails
description: Guardrails for NewsRoom Paper Visual Compiler and model-assisted academic PDF parsing. Use when changing or reviewing PDF-to-PaperDocument compilation, model layout prompts, figure/table extraction, equation generation, Asset Gate rules, source previews, or Open Reader paper-body rendering.
---

# Paper Visual Compiler Guardrails

## Core Contract

Use this skill before touching any paper PDF parsing, visual compiler, or Open Reader body rendering code.

The formal reader body is a source reconstruction, not an AI article. Every body block must be traceable to the PDF source or to a model-transcribed equation region. AI summary, method signals, benchmark signals, recommendations, and review diagnostics must stay outside the body stream.

## Non-Negotiables

- Never render legacy `sections[]` as the formal paper body.
- Never put AI summary or derived signals into `PaperDocument.blocks`.
- Never publish non-`compiled` documents as readable article body.
- Never use screenshot assets for equations. Equations must be generated text or LaTeX with source bbox metadata.
- Never publish figure/table blocks without a manifest asset, source bbox, dimensions, checksum, label, and caption.
- Never allow the same Figure/Table label to create many tiny cards. Group multi-panel images under one visual block unless the paper explicitly has separate labels.
- Never crop surrounding prose into figure/table assets when real image blocks or model regions identify the visual body.
- Never trust model output alone. Deterministic Asset Gate must remain the publication authority before review.
- Never treat a model failure, timeout, or malformed JSON as publishable. Record diagnostics and block or fall back deterministically.

## Workflow

1. Read the relevant implementation:
   - `business/boards/paper_radar/visual_compiler/`
   - `interfaces/services/paper_visual_compiler_service.py`
   - `interfaces/api/routers/papers.py`
   - `frontend/src/lib/paper-reader/`
   - `frontend/src/components/papers/open-reader/`

2. Classify the work:
   - Provider/prompt change: read `references/model-output-contract.md`.
   - Gate/review/publication change: read `references/publication-gates.md`.
   - Frontend reader change: read `references/open-reader-rendering.md`.

3. Preserve the artifact boundary:
   - PDF compiler produces `PaperDocument`, `PaperAssetManifest`, `PaperCompileInfo`, diagnostics.
   - Asset Gate validates deterministic integrity.
   - AI review assesses readability after Gate success.
   - Reader renders only published `PaperDocument.blocks`.

4. Add or update tests for the failure mode being fixed. Prefer synthetic PDFs for deterministic backend tests and component tests for reader rendering.

5. Validate a real compiled artifact when possible:

```powershell
python .codex\skills\paper-visual-compiler-guardrails\scripts\validate_paper_document.py .newsroom\papers\visual-compiler\<paper_id>
```

## Model Prompt Rules

When asking a model to parse PDF page images:

- Ask for JSON only.
- Ask it to locate visual regions, not summarize or rewrite.
- Require PDF-point bboxes using top-left origin.
- Require one complete region for a multi-panel Figure/Table.
- Require captions copied from the paper when visible.
- Require `equationText` as LaTeX/plain math for equations.
- Tell it equations are not image assets.
- Tell it to exclude surrounding prose and exclude caption from crops when the visual body is clear.
- Treat model confidence as advisory metadata, not a gate bypass.

## Equation Rules

Equation blocks must satisfy all of these:

- `type == "equation"`
- `assetId is None`
- `text` is generated formula text or LaTeX, not a screenshot path and not an explanatory paragraph.
- `source` has page number and bbox.
- KaTeX may render the text; fallback may show plain text.
- The formula text may come from model transcription first, then PyMuPDF text fallback only if it looks like a standalone equation.

Reject these as equation blocks:

- paragraphs with a few math symbols,
- captions,
- figure/table labels,
- PDF mojibake/private-use glyph noise,
- screenshots or asset-backed equation images.

## Figure/Table Rules

Figure/table blocks must satisfy all of these:

- `type in {"figure", "table"}`
- `assetId` points to an existing manifest asset.
- asset file exists inside the paper visual compiler directory.
- asset has valid width, height, checksum, source bbox, label, caption, and acceptable blankness.
- multi-image panels with one label compile into one block/asset.
- table assets may span the column/page width; figure assets should be readable and not stretched.

## Reader Rules

Open Reader must stay a full-screen reading surface for `/papers/[slug]/read`.

- Do not add the outer Research/Header bar to the formal reader.
- Render body only when backend document status is `compiled`.
- For non-compiled states, show status/diagnostics and do not render pseudo-body.
- Render equations through `EquationRenderer`, not `<img>`.
- Render figure/table cards from manifest asset URLs.
- Keep AI panel auxiliary and visually separate from the paper body.

## Validation Commands

Run the narrowest useful set, then broaden if shared behavior changed:

```powershell
python -m pytest tests\business\boards\paper_radar\test_visual_compiler.py -q
openspec validate paper-visual-compiler-runtime --strict
cd frontend; npm test -- --run paper-reader-page paper-document-reader-page
cd frontend; npm run typecheck
python -m scripts.dev compile
```

For a real paper artifact:

```powershell
python .codex\skills\paper-visual-compiler-guardrails\scripts\validate_paper_document.py .newsroom\papers\visual-compiler\arxiv-2605.26111v1
```
