## 1. OpenSpec Setup

- [x] 1.1 Create `source-html-extraction-connector` OpenSpec change.
- [x] 1.2 Define proposal, design, tasks, and spec delta.
- [x] 1.3 Keep OpenSpec files, local state, generated outputs, and secrets out of commits.

## 2. HTML Extraction Connector

- [x] 2.1 Add `html` source type.
- [x] 2.2 Add deterministic HTML extraction result and parser.
- [x] 2.3 Add `HtmlConnector` with fetch policy, retry, and rate-limit support.
- [x] 2.4 Emit `RawSourceItem` with extraction metadata and separated extracted text.

## 3. Validation

- [x] 3.1 Add focused HTML connector tests.
- [x] 3.2 Run OpenSpec validation and focused tests.
- [x] 3.3 Run full tests, diff checks, secret scan, and commit.
