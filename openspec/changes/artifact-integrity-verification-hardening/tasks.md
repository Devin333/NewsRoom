## 1. Shared Integrity Contract

- [x] 1.1 Add shared store exceptions and preserve public imports from `framework.artifacts` and `framework.artifacts.stores`.
- [x] 1.2 Add shared SHA-256 metadata validation helpers for local-store and workflow strict-read consumers.

## 2. Local Store And Generic Inspection

- [x] 2.1 Implement unique temporary writes, object-first replacement, metadata-last commit, and owned-temp cleanup in `LocalArtifactStore.put()`.
- [x] 2.2 Implement pair-state classification, metadata identity/shape validation, checksum verification, and legacy checksum-missing marking in `LocalArtifactStore.get()`.
- [x] 2.3 Make generic integrity inspection fail fast without a store, count actual attempts, and classify missing, mismatch, metadata-corrupt, and checksum-missing issues.
- [x] 2.4 Add roundtrip, tamper, half-state, corrupt metadata, legacy metadata, resolver/manager, and fault-injection regressions.

## 3. Strict Workflow Reads

- [x] 3.1 Add strict single-artifact checksum verification before decode/redaction, including expected-metadata validation and the exact `manifest` self-checksum exception.
- [x] 3.2 Add strict all-artifact replay preflight while preserving existing non-strict workflow diagnostic defaults.
- [x] 3.3 Route direct artifact detail and service-facing run replay through strict verification without changing metadata-only list behavior.
- [x] 3.4 Add normal, tampered, missing-checksum, invalid-checksum, missing-file, and `manifest="pending"` workflow regressions.

## 4. Interface Error Contracts

- [x] 4.1 Map checksum mismatch, metadata corruption, and store-required failures to HTTP 409/409/500 with fixed codes while preserving path 400 and missing 404.
- [x] 4.2 Make artifact/run CLI commands print typed integrity failures to stderr, exit `1`, and emit no content.
- [x] 4.3 Preserve typed MCP application failure envelopes and MCP HTTP outer failure mapping for artifact detail and replay.
- [x] 4.4 Add service, API, CLI, MCP application, stdio, and MCP HTTP integrity regressions.

## 5. Validation And Delivery

- [x] 5.1 Run `openspec validate artifact-integrity-verification-hardening --strict` and all Change 2 targeted tests.
- [x] 5.2 Run `python -m scripts.dev compile`, `python -m scripts.dev smoke`, `openspec validate --all --strict`, and `git diff --check`.
- [ ] 5.3 Archive completed integrity and boundary changes, update the stage 18 PRD implementation record, and commit each completed change boundary.
