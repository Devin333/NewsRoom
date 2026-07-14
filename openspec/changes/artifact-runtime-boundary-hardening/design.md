## Context

Artifact filesystem access is split across `framework/artifacts`, workflow runtime and inspection code, checkpoint recovery, builtin tools, and interface services. Several entry points implement partial `Path` checks independently, while `ArtifactManager.run_dir()` and `LocalArtifactPublisher` currently accept untrusted identifiers directly. The change must close all confirmed artifact-root paths without making the general reference model local-filesystem-only.

## Goals / Non-Goals

**Goals:**

- Establish `framework/artifacts/paths.py` as the only artifact path decision source.
- Reject unsafe identity/path input before directory, file, event, manifest, checkpoint, or index side effects.
- Protect publisher- and step-owned metadata fields from caller override.
- Make reference construction/deserialization reject missing, blank, non-string, or conflicting aliases.
- Preserve existing valid workflow, inspection, store, CLI, API, MCP, and remote-reference behavior.

**Non-Goals:**

- Unifying the three artifact reference models or the two local store implementations.
- Adding ACLs, encryption, signatures, remote object storage, or cross-process write locks.
- Enforcing local path semantics on remote `ArtifactReference.uri` values.
- Solving read-time checksum verification; that is owned by the dependent integrity change.

## Decisions

### Shared path API is public and deterministic

Add the fixed public API `ArtifactPathError`, `validate_artifact_path_segment()`, `validate_relative_artifact_path()`, and `resolve_artifact_descendant()`. Segment validation rejects separators, absolute/drive/UNC/device paths, control characters, Windows reserved characters, trailing dot/space, ADS syntax, and DOS device names. Relative path validation permits nested POSIX paths but applies the same rules to every segment and rejects any parent segment.

Canonical containment uses resolved `Path.relative_to()` rather than string prefix checks. Existing symlink or junction targets that resolve outside the root fail. The functions reject rather than sanitize identities so run/index/replay identity cannot silently change.

Alternatives rejected: keeping per-module validation duplicates platform behavior; a narrow character allowlist risks unnecessary compatibility breakage; string prefix checks are not path-safe.

### Filesystem boundaries validate even when governance gates are disabled

Manager, publisher, stores, workflow, checkpoint, builtin tool, and interface entry points validate before their first filesystem access. `gate_enabled=False` does not affect these checks. Workflow inspection wrappers may translate `ArtifactPathError` to `WorkflowRunInspectionError`, but delegate the decision to the shared helper.

### Trusted metadata conflicts fail before publication

Publisher callers cannot provide `publisher_id` or `run_id`. Nested `artifact_metadata` cannot provide identity, location, content description, integrity, lifecycle, or redaction keys defined by `ARTIFACT_STEP_RESERVED_METADATA_KEYS`. Exact-key conflicts produce a failed publish/step result with no file, reference, manifest, index, or buffer side effect. Normal custom metadata remains recursively redacted.

### General references retain remote URI semantics

`ArtifactReference.__post_init__()` and `from_dict()` share required-string and alias rules. `uri` and legacy `path` may both be present only when equal. The validator applies segment checks to `artifact_id` and a supplied `run_id`, but does not run local relative-path validation against a general URI. Local publishers/stores/resolvers enforce local path semantics at file access.

`ArtifactRef.from_dict()` receives the same required and alias checks, but its constructor is not globally tightened in this change because storage/index consumers are broader.

## Risks / Trade-offs

- [Historical special-character identifiers fail] → run a read-only deployment-root scanner before rollout; do not sanitize or rewrite automatically.
- [A direct path bypass remains] → maintain an explicit file inventory and adversarial tests for manager, workflow, tool, service, API, CLI, and MCP paths.
- [Windows behavior differs on POSIX CI] → test with both POSIX normalization and `PureWindowsPath` semantics.
- [Reserved keys expose old invalid configurations] → return a diagnostic key-specific failure and verify no partial side effect.
- [Shared helper becomes overly restrictive] → keep `_records` and valid nested paths supported; enforce only security/ambiguity rules in this change.

## Migration Plan

1. Add helpers and parameterized path tests.
2. Migrate core manager/publisher/stores, then workflow/tool/service bypasses.
3. Tighten metadata and reference boundaries with compatibility tests.
4. Run targeted tests, compile, smoke, and strict OpenSpec validation.
5. Roll back the change as one boundary unit if valid historical identifiers are rejected; never roll back by disabling validation.

## Open Questions

None. Namespace reservation beyond path safety and broad reference-model convergence remain separate future changes.
