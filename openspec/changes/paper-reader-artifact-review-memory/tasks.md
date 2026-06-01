## 1. OpenSpec

- [x] 1.1 Create artifact review memory proposal, tasks, and specs.
- [x] 1.2 Validate `paper-reader-artifact-review-memory` with strict OpenSpec validation.

## 2. Framework Review Subagent

- [x] 2.1 Add a framework-level paper reader artifact review subagent with image, table, equation, and symbol gates.
- [x] 2.2 Return stable issue fingerprints, locators, gate summaries, and repeat memory matches.
- [x] 2.3 Persist review issues to a local durable memory journal without making memory write failures block compilation.

## 3. Visual Compiler Integration

- [x] 3.1 Route `PaperAssetGate` through the framework reviewer while preserving deterministic asset file integrity checks.
- [x] 3.2 Fix source-first TeX parser handling for top-level tabular blocks, text wrappers, URL commands, equation wrappers, and table inline math.
- [x] 3.3 Fix the Research paper detail drawer width so it stays a side drawer.

## 4. Verification

- [x] 4.1 Add framework reviewer and memory tests.
- [x] 4.2 Update visual compiler and frontend reader/drawer tests for the fixed behavior.
- [x] 4.3 Run targeted backend and frontend tests.
- [x] 4.4 Run strict OpenSpec validation and type/compile checks where available.
- [x] 4.5 Commit the completed code and OpenSpec change.
- [x] 4.6 Recompile Cambrian-P and verify reader-facing fields and rendered page no longer expose `rll`, HTML entities, or raw inline LaTeX commands.
