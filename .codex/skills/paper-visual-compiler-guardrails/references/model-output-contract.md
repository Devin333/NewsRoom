# Model Output Contract

Use this reference when editing `model_layout_provider.py`, model prompts, provider adapters, or any code that converts model regions into `PaperBlock` / `PaperVisualAsset`.

## Required JSON Shape

The model response should normalize to:

```json
{
  "regions": [
    {
      "kind": "figure | table | equation",
      "label": "Figure 1 / Table 1 / Equation 1",
      "caption": "caption copied from the paper",
      "equationText": "LaTeX or plain math for equations",
      "bbox": {"x0": 0, "y0": 0, "x1": 100, "y1": 100},
      "confidence": 0.0
    }
  ]
}
```

## Provider Requirements

- Normalize pixel, relative, and PDF-point bbox formats into PDF points.
- Reject bboxes outside the page or smaller than a useful region.
- Record diagnostics for malformed regions instead of raising unless the provider itself failed.
- Keep raw model metadata for traceability.
- Do not use model regions as final truth without deterministic validation.

## Prompt Requirements

The system prompt must say:

- return strict JSON only,
- do not summarize, translate, or rewrite,
- detect real figures, tables, and standalone equations,
- equations return `equationText` and are not image assets,
- prefer one complete region for multi-panel figures,
- exclude surrounding prose,
- exclude captions from crops when the visual body is clear.

## Equation Text Priority

For equation regions, prefer model `equationText` when it looks like a standalone equation. Use overlapping PyMuPDF text only as fallback. Do not let explanatory paragraphs become equation blocks just because they contain `=`, Greek letters, or a trailing colon.

## Failure Handling

- Timeout, invalid JSON, and retry exhaustion produce diagnostics.
- No model output must not publish bad output.
- If deterministic fallback runs, mark diagnostics so review and UI can explain the lower-confidence path.
