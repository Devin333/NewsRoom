## Why

Research Reader artifacts can pass the existing asset gate while still exposing TeX parser failures such as raw table alignment tokens, unsupported equation wrappers, escaped entities, or broken symbol output. These failures should be reviewed by a framework-level reviewer so the business compiler keeps a clean boundary and repeated issues can be recognized immediately.

## What Changes

- Add a framework-level paper reader artifact review subagent with image, table, equation, and symbol gates.
- Persist a reusable issue memory journal keyed by stable fingerprints so repeated reader artifact failures return prior locator context.
- Route `PaperAssetGate` through the framework reviewer while keeping deterministic file integrity checks in the visual compiler boundary.
- Fix source-first TeX parsing for top-level tabular link tables, text wrapper commands, URL commands, equation size wrappers, and table inline math.
- Tighten the Research paper detail drawer width so title clicks do not create a full-window drawer.

## Capabilities

### Modified Capabilities
- `paper-visual-compiler-runtime`: publication checks include framework artifact review gates and issue memory.
- `paper-reader-source-compare-evolution`: source-first reader fidelity learns repeated artifact review failures in addition to source comparison lessons.

## Impact

- Framework agent subagent and memory-adjacent artifact review code.
- Business visual compiler asset gate integration.
- arXiv source TeX parser and table/equation rendering metadata.
- Research paper detail drawer UI and reader status fallback tests.
