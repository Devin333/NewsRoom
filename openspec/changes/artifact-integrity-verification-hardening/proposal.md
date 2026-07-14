## Why

Artifact writes already persist SHA-256 checksums, but the default `LocalArtifactStore`, generic integrity inspector, and service-facing workflow artifact reads do not consistently verify them. As a result, tampered bytes, corrupt metadata, half-written object pairs, and unavailable stores can be reported as valid or returned through replay, CLI, API, and MCP surfaces.

## What Changes

- Add one shared set of artifact store exceptions and checksum/metadata validation semantics across local stores and workflow inspection.
- Make `LocalArtifactStore` use temporary-file replacement, classify object/metadata half-states, validate persisted metadata, and verify SHA-256 before returning content.
- Make integrity inspection fail fast for a non-empty manifest without a store and report accurate checked counts and typed issues.
- Add strict workflow artifact reads and strict replay preflight so interface-facing reads reject checksum mismatch, corrupt metadata, and missing required integrity metadata before returning content.
- Preserve the documented one-release compatibility behavior for legacy `LocalArtifactStore` metadata with no checksum, while marking it unverified and failing integrity reports.
- Preserve the manifest self-checksum sentinel `"pending"` by excluding only the `manifest` artifact key from recursive self-verification.
- Map typed integrity failures consistently to HTTP, CLI, MCP service, and MCP-over-HTTP error contracts.
- Add tamper, half-state, fault-injection, legacy, workflow, CLI, API, and MCP regressions.

## Capabilities

### New Capabilities

- `artifact-integrity-verification`: Defines shared local-store integrity errors, atomic publication semantics, no-store inspection behavior, checksum verification, metadata validation, legacy checksum handling, and strict workflow artifact reads.

### Modified Capabilities

- `artifact-store-index`: Requires local artifact stores to verify persisted bytes and metadata and expose consistent typed failures.
- `artifact-inspection-interface`: Requires direct artifact detail reads to complete strict integrity verification before content is returned.
- `run-replay-cli`: Requires service-facing replay to verify all non-manifest artifacts and requires typed failures on stderr with exit code `1`.
- `run-replay-api`: Requires stable 409/500 integrity error responses and no replay content on verification failure.
- `mcp-run-replay`: Requires tool/resource replay failures to retain stable typed MCP failure envelopes.
- `mcp-artifact-resource`: Requires direct MCP artifact reads to retain stable typed integrity failure envelopes.

## Impact

- Core: `framework/artifacts/stores`, `framework/artifacts/inspection`, manager/resolver behavior, and workflow inspection checksum helpers.
- Interfaces: artifact and run inspection services, run/artifact HTTP routes, CLI artifact/run commands, MCP application service, and MCP HTTP routing.
- Tests: local-store fault injection and tamper cases, integrity reports, strict workflow replay/read, and adapter-specific error mappings.
- Compatibility: valid checksummed artifacts remain unchanged; legacy local-store metadata without a checksum remains readable only with an explicit unverified marker and cannot pass integrity inspection.
- Dependencies: no new third-party runtime dependency.
