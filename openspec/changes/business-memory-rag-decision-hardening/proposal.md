## Why

NewsRoom already ingests report and evidence memory, but board scoring cannot yet use recalled memory as deterministic decision evidence. This change turns business memory/RAG recall into optional scoring features without coupling framework scoring to memory.

## What Changes

- Add `business/memory` decision helpers for memory hits, context, recall, source reliability, duplicate detection, topic momentum, feedback penalties, and scoring features.
- Extend the board scoring service to optionally merge memory-derived features.
- Keep memory unavailable paths soft-fail and score-neutral.
- Add focused tests for memory decisions and scoring impact.

## Capabilities

### New Capabilities
- `business-memory-rag-decision`: Business memory recall and decision features for scoring.

### Modified Capabilities

## Impact

- Affected code: `business/memory`, `business/scoring`, tests, and package metadata.
- Public API impact: additive business-layer APIs only.
- Dependency impact: none; business memory uses ports/protocols instead of concrete vector clients.
