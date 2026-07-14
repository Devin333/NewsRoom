## 1. Failing Regressions And Fixtures

- [x] 1.1 Replace the incomplete strict-replay fixtures with canonical terminal run manifests that pass `validate_run_manifest(..., require_terminal_artifact=True)` before any adversarial mutation.
- [x] 1.2 Add TOCTOU regressions that replace manifest-listed artifact, `events`, and `step_results` files after preflight and assert strict replay never returns the replacement bytes.
- [x] 1.3 Add strict replay regressions for invalid canonical manifest schema and assert `ArtifactStoreMetadataError` occurs before decode, redaction, truncation, or response construction.
- [x] 1.4 Add selected artifact-index regressions for top-level checksum, nested `artifact_ref.checksum` fallback, conflicting or missing checksums, unsafe/missing/non-regular targets, duplicate projected keys, size mismatch, serialized content-type mismatch, and all-or-nothing failure.
- [x] 1.5 Add a production-shape `source_response_headers` fixture proving top-level response `content_type` is preserved while `artifact_ref.content_type` owns persisted-file verification.
- [x] 1.6 Add `LocalArtifactStore` regressions for object/metadata directories or other stable non-regular nodes and for missing, null, blank, whitespace-padded, or non-string required fields during `list()`.
- [x] 1.7 Add publisher and artifact-service regressions proving non-string legacy metadata `run_id` values fail before coercion and fallback run-directory resolution uses the shared boundary.
- [x] 1.8 Convert object-replace failure coverage into automated fault injection and assert the prior committed artifact remains readable, no new metadata commit is exposed, and owned temporary files are removed.

## 2. Immutable Strict Replay Snapshot

- [x] 2.1 Add an internal frozen verified-snapshot model containing artifact key, canonical relative and absolute paths, validated metadata, serialized content type, size, and raw bytes.
- [x] 2.2 Make strict snapshot capture validate canonical path containment, regular-file kind, expected metadata, optional size/content type, and SHA-256 before returning a snapshot.
- [x] 2.3 Validate the canonical terminal run manifest first and wrap `RunManifestError` as `ArtifactStoreMetadataError` in direct strict artifact detail and strict replay.
- [x] 2.4 Capture every manifest-listed artifact exactly once, retain the verified bytes, and preserve the exact manifest self-checksum sentinel `"pending"` without claiming external authenticity.
- [x] 2.5 Add byte-based JSON, JSONL, text, binary preview, truncation, and redaction helpers so strict artifact records, events, step results, timeline, routing diagnostics, and manifest projection consume snapshots only.
- [x] 2.6 Prove by test instrumentation that no strict post-preflight branch calls `Path.read_*`, `_read_json_file()`, `read_events()`, `read_json_artifact()`, or `read_workflow_artifact_content()`.
- [x] 2.7 Keep non-strict workflow diagnostics on the existing tolerant path-based readers, including partial `read_error` behavior, default flags, and redaction output compatibility.

## 3. Transitive Artifact-Index Integrity

- [x] 3.1 Parse the selected artifact index from its manifest-verified snapshot instead of reopening the index path.
- [x] 3.2 Resolve index integrity declarations with top-level `checksum` first and nested `artifact_ref.checksum` as compatibility fallback; reject invalid, absent, or conflicting declarations as typed metadata corruption.
- [x] 3.3 Treat nested `artifact_ref` identity, path, serialized content type, and size as canonical when present; validate duplicated integrity fields while preserving documented top-level business projections such as source response `content_type`.
- [x] 3.4 Validate index entry shape, projected-key uniqueness, canonical descendant path, regular-file kind, optional serialized size/content type, and checksum before decoding any selected entry.
- [x] 3.5 Capture all selected entry targets into the verified snapshot set and fail strict replay as one unit on any missing, unsafe, malformed, non-regular, or mismatched target.
- [x] 3.6 Build index-expanded replay records exclusively from verified target bytes while preserving artifact keys, source/entity/object metadata, binary preview, truncation, and sensitive-value redaction.

## 4. Store, Reference, And Path Boundary Closure

- [x] 4.1 Make `LocalArtifactStore.get()` distinguish absence from a stable non-regular object or metadata node and raise `ArtifactStoreMetadataError` before JSON or byte reads.
- [x] 4.2 Route `LocalArtifactStore.list()` records through strict persisted-field validation and shared metadata error mapping instead of coercing required fields with `str()`.
- [x] 4.3 Validate the raw optional `WorkflowArtifactRef.metadata["run_id"]` type in `LocalArtifactPublisher._artifact_path()` and reject non-string values through `ArtifactPathError` before filesystem access.
- [x] 4.4 Remove the direct `self.artifact_root / run_id` fallback in `ArtifactInspectionService` and resolve every fallback using `validate_artifact_path_segment()` plus `resolve_artifact_descendant()`.
- [x] 4.5 Preserve valid legacy string run ids, valid local store listing, custom metadata, remote general references, and existing typed adapter mappings.

## 5. Artifact Integrity Observability

- [x] 5.1 Add a dependency-free artifact observability helper over standard logging with fixed event names, allow-listed dimensions, safe fallback labels, and no raw exception text or traceback.
- [x] 5.2 Emit `artifact_path_rejected_total{field,operation}` once at the shared path-boundary rejection owner.
- [x] 5.3 Emit `artifact_reserved_metadata_rejected_total{key,publisher}` once at publisher and artifact-step reserved-key rejection owners.
- [x] 5.4 Emit `artifact_checksum_mismatch_total{store,operation}` from shared checksum verification and `artifact_checksum_missing_total{store}` from legacy-compatible or strict missing-checksum classification.
- [x] 5.5 Emit `artifact_metadata_corrupt_total{store}` from deterministic typed corruption catch boundaries without double-counting propagated exceptions.
- [x] 5.6 Emit `artifact_integrity_inspection_total{result}` at info for successful inspection and warning for invalid or configuration-failure completion.
- [x] 5.7 Add structured-log tests for event name, level, exact dimensions, one-event ownership, safe unknown labels, and absence of paths, metadata values, content, credentials, tokens, exception text, and tracebacks.

## 6. Service And Adapter End-To-End Regressions

- [x] 6.1 Add real-filesystem `RunInspectionService` regressions for canonical-manifest failure, TOCTOU replacement, selected-index tamper, missing checksum, and successful snapshot replay.
- [x] 6.2 Add real-filesystem `ArtifactInspectionService` regressions for invalid manifest, fallback path resolution, tampered content, and successful direct read.
- [x] 6.3 Add HTTP run replay and artifact detail regressions that traverse the real service/filesystem path and assert stable 400/404/409 envelopes with no artifact content on failure; verify the unreachable-from-these-services `ArtifactStoreRequiredError` 500 mapping with an adapter-isolation test rather than representing a fake service as upstream proof.
- [x] 6.4 Add CLI `runs replay` and `artifacts show` regressions that traverse the real service path and assert exit `1`, sanitized stderr, and empty stdout content on typed integrity failure.
- [x] 6.5 Add MCP tool/resource, MCP-over-HTTP, and stdio JSON-RPC regressions using the real filesystem/service path; assert `success=False`, stable `error_type`, correct outer HTTP mapping, and no tampered replay/artifact data.
- [x] 6.6 Keep fake-service adapter tests for mapping isolation but do not count them as proof that upstream strict integrity failures are produced.

## 7. PRD, Evidence, And Release Gates

- [x] 7.1 Reopen stage 18 as `READY_FOR_IMPLEMENTATION / IN_PROGRESS`, add this completion-remediation contract, and keep the prior two archived changes as historical delivery evidence rather than current completion proof.
- [x] 7.2 Reconcile stage 18 acceptance checkboxes and DoD, replace archived-change validation commands with active/main-spec commands, add omitted workflow integrity tests, and label unreproducible historical counts as unverified snapshots.
- [x] 7.3 Complete the file/test impact matrix and implementation table, including commits `f8d300d0` and `9fddf4ec`, without modifying or staging the concurrent stage 19 PRD work.
- [x] 7.4 Run the focused artifact, workflow, business signal index, service, HTTP, CLI, MCP, and stdio suites defined by the PRD and record fresh counts only after all adversarial tests pass.
- [x] 7.5 Run `.\.venv\Scripts\python.exe -m scripts.dev compile`, `.\.venv\Scripts\python.exe -m scripts.dev smoke`, `openspec validate artifact-integrity-completion-hardening --strict`, `openspec validate --all --strict`, and `git diff --check`; fix root causes rather than weakening gates.
- [x] 7.6 Commit the implementation with path-scoped staging that excludes the user's stage 19 changes, archive the OpenSpec change, rerun post-archive strict validation, and restore `FINAL / IMPLEMENTED` only when every completion checkbox has current evidence.
