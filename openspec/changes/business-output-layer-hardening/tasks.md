## 1. OpenSpec

- [x] 1.1 Create and validate `business-output-layer-hardening`.

## 2. Output Layer Refactor

- [x] 2.1 Move BoardOutput DTO helper models out of `pipeline.py`.
- [x] 2.2 Move BoardCard, DetailPage, Insight, Report, section composition, and output quality logic into focused output-layer modules.
- [x] 2.3 Slim `BoardOutputPipeline` so it only orchestrates split builders and aggregates stats/metadata.
- [x] 2.4 Preserve package-level imports and board/interface call compatibility.

## 3. Tests and Validation

- [x] 3.1 Add output-layer hardening tests for no-raw BoardCard serialization, required card evidence fields, detail sections, report sections, and split builder pipeline execution.
- [x] 3.2 Run targeted output/board/interface tests and full business/script regression; fix failures forward.
