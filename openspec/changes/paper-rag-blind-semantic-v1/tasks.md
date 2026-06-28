## 1. Blind Semantic Question Profile

- [x] 1.1 Add `blind_semantic` as an explicit Paper RAG question profile.
- [x] 1.2 Preserve `template` as the default profile.
- [x] 1.3 Preserve `blind_detemplated` compatibility.
- [x] 1.4 Generate blind semantic questions without direct figure/table/equation labels.
- [x] 1.5 Preserve natural semantic anchors for figure, table, experiment, formula, and citation QA.

## 2. Ambiguity Audit

- [x] 2.1 Add deterministic ambiguity/quality audit for generated QA pairs.
- [x] 2.2 Report duplicate question rate, ambiguous question rate, missing semantic anchor rate, label leakage rate, and caption copy rate.
- [x] 2.3 Include audit details in JSON reports and summary metrics in Markdown.

## 3. CLI and Reports

- [x] 3.1 Expose `blind_semantic` through `run_benchmark_suite --question-profile`.
- [x] 3.2 Mark both `blind_detemplated` and `blind_semantic` as blind tests in reports.
- [x] 3.3 Preserve the existing fixed-window baseline behavior as opt-in only.

## 4. Verification

- [x] 4.1 Add focused tests for `blind_semantic` question generation.
- [x] 4.2 Add focused tests for ambiguity audit and benchmark report output.
- [x] 4.3 Run focused Paper RAG tests.
- [x] 4.4 Run compile and OpenSpec validation.
- [x] 4.5 Run a real benchmark smoke with `blind_semantic`.
