## 1. Penalized Scoring

- [x] 1.1 Add parser bake-off acceptance threshold config.
- [x] 1.2 Compute per-parser penalized metrics with explicit penalty details.
- [x] 1.3 Add cascade acceptance checks to report recommendations.

## 2. Report And CLI Surface

- [x] 2.1 Add penalized metrics and cascade acceptance to JSON reports.
- [x] 2.2 Add penalized score and cascade acceptance sections to Markdown reports.
- [x] 2.3 Add `--acceptance-threshold KEY=VALUE` parsing to the parser bake-off report CLI.

## 3. Tests And Validation

- [x] 3.1 Add tests for penalized scoring and ingest failure penalties.
- [x] 3.2 Add tests for cascade acceptance pass/fail and CLI threshold parsing.
- [x] 3.3 Run targeted tests, compile, strict OpenSpec validation, smoke/full checks, and strict all-change validation.
