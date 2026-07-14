## Why

The stage 18 completion audit reproduced a strict-replay time-of-check/time-of-use gap: replay verifies one set of bytes during preflight, then re-reads files through non-strict paths and can return different tampered bytes. The same audit found fail-open manifest validation, unverified checksum-bearing artifact-index entries, non-file local-store states escaping the shared error contract, persisted null reference fields being coerced to the string `"None"`, non-string legacy run identifiers being accepted after coercion, and one residual direct run-directory join.

## What Changes

- Build strict replay from one immutable in-memory snapshot of every verified manifest-listed artifact, and reuse those exact bytes for artifact records, events, step results, and index parsing.
- Preflight checksum-bearing artifact-index entries before any replay content is decoded or returned, then build expanded replay records from the verified entry snapshots.
- Make strict artifact detail and replay reject structurally invalid run manifests as `ArtifactStoreMetadataError` instead of returning content from an invalid persisted contract.
- Classify object or metadata paths that exist but are not regular files as `ArtifactStoreMetadataError` in `LocalArtifactStore.get()`.
- Make `LocalArtifactStore.list()` validate persisted required fields before reference construction so null, blank, or non-string values cannot be coerced to `"None"` or another identity.
- Reject a non-string legacy `WorkflowArtifactRef.metadata["run_id"]` before coercion or filesystem access.
- Remove the residual `artifact_root / run_id` fallback from artifact detail inspection and use the shared artifact path boundary for every fallback path.
- Emit safe structured artifact path, reserved-metadata, checksum mismatch/missing, metadata corruption, and integrity-inspection events required by the stage 18 observability contract.
- Add adversarial TOCTOU, invalid-manifest, indexed-entry tamper/missing-checksum, non-file pair-state, service/API/CLI/MCP, and non-strict compatibility regressions.
- Correct the stage 18 PRD and index so completion status, acceptance checkboxes, historical validation commands, and current proof match the live implementation.
- **BREAKING for invalid persisted runs:** strict service-facing replay will reject manifests that do not satisfy the canonical run-manifest contract and expanded index entries that omit required checksum metadata; non-strict diagnostics remain available for forensic inspection.

## Capabilities

### New Capabilities

- `artifact-integrity-observability`: Defines the stable structured event names, required dimensions, severity, and no-secret rules for artifact boundary and integrity outcomes.

### Modified Capabilities

- `artifact-integrity-verification`: Require strict replay to return content only from the exact verified byte snapshot and require deterministic typed classification of non-file local-store states.
- `run-replay-cli`: Require canonical manifest validation and strict preflight of expanded artifact-index entries before any replay projection is returned.
- `artifact-store-index`: Require the default local artifact store to classify non-regular object/metadata paths as corrupt persisted state.
- `artifact-runtime-boundary`: Require artifact inspection fallback run-directory resolution to use the shared path boundary without direct joins.
- `artifact-inspection-interface`: Require direct artifact detail to validate the canonical run manifest before returning content.

## Impact

- Core: `framework/workflow/inspection/inspector.py`, strict replay snapshot and index expansion helpers, event/JSON decoding from verified bytes.
- Store/runtime: `framework/artifacts/stores/local.py` pair-state and list deserialization; `framework/artifacts/runtime/publisher.py` legacy reference resolution.
- Interface: `interfaces/services/run_inspection_service.py` delegates manifest capture to the strict inspector; `interfaces/services/artifact_service.py` closes manifest/fallback gaps; existing API/CLI/MCP typed mappings remain stable and gain end-to-end regressions.
- Observability: a dependency-free artifact event helper built on the standard logging stack and instrumentation at shared deterministic boundaries.
- Documentation: stage 18 PRD implementation record and harness/research PRD index.
- Tests: workflow integrity, artifact store/manager, run/artifact inspection services, HTTP, CLI, MCP application/stdio, and targeted adversarial scripts.
- Dependencies: no new third-party runtime dependency.
