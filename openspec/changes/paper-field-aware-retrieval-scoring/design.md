## Context

Paper chunks already preserve field-like information:

- `section_title` and `section_role`
- abstract chunks
- figure/table captions in chunk content and `content_sources`
- caption locator metadata such as `caption_source_locator` and `caption_pdf_rect`
- formula fields such as `formula_latex` and `formula_description`

The current child ranking path uses semantic score plus position, and visual fusion for figure queries. Field information is visible in metadata but does not produce an explicit field-level relevance score.

## Goals

- Add explainable field-aware scoring without changing persistent schemas.
- Let query intent control which fields matter most.
- Keep semantic relevance dominant so field matching only boosts plausible candidates.
- Preserve visual fusion and parent/table expansion behavior.
- Make field scoring observable through chunk metadata and retrieval metrics.

## Non-Goals

- New embedding models.
- OCR/Surya/Nougat/parser changes.
- Image embedding changes.
- Learning-to-rank training.
- Database/vector schema migrations.

## Field Score

Each child candidate should compute:

```text
field_score =
  title_score * title_weight
+ abstract_score * abstract_weight
+ caption_score * caption_weight
+ equation_score * equation_weight
+ body_score * body_weight
```

Then child ranking should use:

```text
child_final_score =
  semantic_score * semantic_weight
+ field_score * field_weight
+ position_score * position_weight
```

Initial child score blend:

```text
semantic=0.75, field=0.20, position=0.05
```

## Intent-Specific Field Weights

Default field weights:

```text
title=0.25, abstract=0.15, caption=0.15, equation=0.15, body=0.30
```

Intent overrides:

```text
concept_method: title=0.35, abstract=0.15, caption=0.10, equation=0.10, body=0.30
contribution: title=0.30, abstract=0.40, caption=0.05, equation=0.05, body=0.20
figure_query: title=0.10, abstract=0.05, caption=0.60, equation=0.05, body=0.20
table_query: title=0.10, abstract=0.05, caption=0.40, equation=0.05, body=0.40
formula_query: title=0.10, abstract=0.05, caption=0.05, equation=0.60, body=0.20
numerical_result: title=0.20, abstract=0.05, caption=0.25, equation=0.05, body=0.45
comparison: title=0.20, abstract=0.05, caption=0.20, equation=0.05, body=0.50
```

Weights should be configurable through `RetrievalPolicy`.

## Metadata

Returned scored chunks should expose:

- `title_score`
- `abstract_score`
- `caption_score`
- `equation_score`
- `body_score`
- `field_score`
- `field_score_weights`
- `field_score_strategy`
- `child_semantic_score`
- `child_position_score`
- `child_final_score`
- `child_score_weights`

Retrieval metadata should expose:

- `field_scoring_enabled`
- `field_score_weights`
- `child_score_weights`
- `field_scored_count`
- `field_score_top`
- `field_score_min`

## Scoring Strategy

V1 can use deterministic lexical overlap for field scoring. This is intentionally lightweight and inspectable. If a reranker or vector score exists, it remains the semantic signal; field scoring is a bounded boost.

Field text sources:

- Title: `section_title`
- Abstract: `content` for abstract chunks or abstract sections
- Caption: explicit caption metadata or `Caption:` blocks in figure/table chunks
- Equation: `formula_latex`, `formula_description`, and formula chunk content
- Body: chunk `content`

## Failure Modes

- If a field is missing, its score is `0.0`.
- If all field scores are zero, semantic ranking still works.
- If weights are malformed, normalize valid non-negative weights or fall back to defaults.
