from __future__ import annotations

import contextvars
import inspect
import json
import math
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any, Callable

from framework.agent.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactReference,
    ArtifactManager,
    ArtifactRef as StorageArtifactRef,
    ArtifactNotFoundError,
    ArtifactStoreMetadataError,
    FilesystemArtifactStore,
    compute_checksum,
    validate_artifact_path_segment,
)
from framework.agent.artifacts.stores.integrity import validate_sha256_checksum
from framework.harness import (
    ArtifactRef as HarnessArtifactRef,
    ArtifactWriteRequest,
    HarnessSideEffectDisposition,
    HarnessSideEffectOutcome,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.hashing import hash_text
from framework.shared.json import stable_json_dumps
from framework.shared.time import format_datetime, utc_now
from infrastructure.research.diagnostics import emit_research_persistence_diagnostic
from business.research.ports.artifact_publication import (
    RESEARCH_ARTIFACT_LEGACY_MANIFEST_VERSION,
    RESEARCH_ARTIFACT_MANIFEST_VERSION,
    ResearchArtifactDiagnosticClaim,
    ResearchArtifactReadClaim,
    ResearchArtifactReadResolution,
    artifact_evidence_ref,
    artifact_member_evidence_ref,
)


_CONTEXT_REF_ONLY_ARTIFACT_TYPES = frozenset(
    {
        "context-aggregate-verification",
        "context-compaction-action-result",
        "context-compaction-plan",
        "context-compaction-planning-result",
        "context-compression-record-v2",
        "context-physical-admission",
        "context-result-snapshot",
        "context-source-snapshot",
    }
)


CANONICAL_ARTIFACT_SCHEME = "artifact"
CANONICAL_ARTIFACT_DIRECTORY = "artifacts"


class ArtifactRunBindingError(HarnessValidationError):
    """Raised when a Research artifact operation has no safe run binding."""


class ArtifactWriteConflictError(ArtifactStoreMetadataError):
    """Raised when an immutable canonical artifact would be overwritten."""


class ArtifactPublicationVisibilityError(ArtifactStoreMetadataError):
    """Raised when a manifest is not authorized for a normal reader."""

    def __init__(self, message: str, *, disposition: str) -> None:
        self.disposition = disposition
        super().__init__(message)


class FilesystemHarnessArtifactPort:
    """Persist Harness JSON artifacts below one context-local Research run."""

    def __init__(
        self,
        root: str | Path = ".newsroom/runs",
        *,
        artifact_manager: ArtifactManager | None = None,
        artifact_store: FilesystemArtifactStore | None = None,
        max_write_bytes: int | None = None,
        accepted_run_resolver: Callable[..., bool] | None = None,
        diagnostic_run_resolver: Callable[..., bool] | None = None,
        legacy_identity_scope_ref: str | None = None,
    ) -> None:
        if max_write_bytes is not None and max_write_bytes < 0:
            raise ValueError("max_write_bytes must be non-negative")
        configured_root = Path(root)
        if artifact_manager is not None:
            manager_root = Path(artifact_manager.root)
            if manager_root.resolve(strict=False) != configured_root.resolve(strict=False):
                raise ValueError("artifact_manager root does not match root")
        self.root = configured_root
        self.manager = artifact_manager or ArtifactManager(
            self.root,
            max_write_bytes=max_write_bytes,
        )
        self.store = artifact_store or FilesystemArtifactStore(self.root)
        self.max_write_bytes = (
            max_write_bytes
            if max_write_bytes is not None
            else self.manager.max_write_bytes
        )
        if accepted_run_resolver is not None and not callable(accepted_run_resolver):
            raise TypeError("accepted_run_resolver must be callable")
        if diagnostic_run_resolver is not None and not callable(diagnostic_run_resolver):
            raise TypeError("diagnostic_run_resolver must be callable")
        self._accepted_run_resolver = accepted_run_resolver
        self._diagnostic_run_resolver = diagnostic_run_resolver
        self._legacy_identity_scope_ref = (
            _validated_checksum_ref(
                legacy_identity_scope_ref,
                field="legacy storage-root identity scope",
                artifact_id="research-artifact-root",
            )
            if legacy_identity_scope_ref is not None
            else None
        )
        self._manifest_lock = threading.RLock()
        self._run_binding: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            f"filesystem_harness_artifact_run_{id(self)}",
            default=None,
        )

    @property
    def current_run_id(self) -> str | None:
        return self._run_binding.get()

    def set_accepted_run_resolver(
        self,
        resolver: Callable[..., bool] | None,
    ) -> None:
        if resolver is not None and not callable(resolver):
            raise TypeError("accepted_run_resolver must be callable")
        self._accepted_run_resolver = resolver

    def set_diagnostic_run_resolver(
        self,
        resolver: Callable[..., bool] | None,
    ) -> None:
        if resolver is not None and not callable(resolver):
            raise TypeError("diagnostic_run_resolver must be callable")
        self._diagnostic_run_resolver = resolver

    @contextmanager
    def bind_run(self, run_id: str) -> Iterator[str]:
        validated = validate_artifact_path_segment(run_id, field="run_id")
        token = self._run_binding.set(validated)
        try:
            yield validated
        finally:
            self._run_binding.reset(token)

    def write_artifact(self, request: ArtifactWriteRequest) -> HarnessArtifactRef:
        run_id = self.current_run_id
        try:
            result = self._write_artifact(request)
        except Exception as exc:
            emit_research_persistence_diagnostic(
                component="artifact_store",
                operation="artifact_write",
                outcome="failed",
                reason=_artifact_failure_reason(exc),
                run_id=run_id,
            )
            raise
        emit_research_persistence_diagnostic(
            component="artifact_store",
            operation="artifact_write",
            outcome="succeeded",
            reason="completed",
            run_id=run_id,
        )
        return result

    def _write_artifact(self, request: ArtifactWriteRequest) -> HarnessArtifactRef:
        run_id = self._require_bound_run()
        if not isinstance(request, ArtifactWriteRequest):
            raise TypeError("request must be ArtifactWriteRequest")
        artifact_type = validate_artifact_path_segment(
            request.artifact_type,
            field="artifact_type",
        )
        request_run_id = request.metadata.get("run_id")
        if request_run_id is not None and request_run_id != run_id:
            raise ArtifactRunBindingError(
                "artifact metadata run_id conflicts with the bound run"
            )
        canonical_payload = request.to_dict()
        _assert_finite_json(canonical_payload)
        try:
            content = stable_json_dumps(canonical_payload).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ArtifactStoreMetadataError(
                f"artifact payload is not JSON serializable: {artifact_type}"
            ) from exc
        self._enforce_size(content, artifact_type)

        relative_path = self._canonical_path(artifact_type)
        checksum = compute_checksum(content)
        with self._manifest_lock:
            self._ensure_run_manifest(run_id)
            existing = self._existing_artifact_result(
                run_id=run_id,
                artifact_type=artifact_type,
                request=request,
                content=content,
                checksum=checksum,
            )
            if existing is not None:
                return existing
            self.manager.write_bytes(run_id, relative_path, content)
            self.manager.append_manifest_artifact(
                run_id,
                artifact_key=artifact_type,
                relative_path=relative_path,
                artifact_ref=ArtifactReference(
                    artifact_id=artifact_type,
                    run_id=run_id,
                    kind=artifact_type,
                    uri=relative_path,
                    content_type=request.media_type,
                    checksum=checksum,
                    size_bytes=len(content),
                    metadata=dict(request.metadata),
                ),
            )
        return HarnessArtifactRef(
            ref=self._canonical_ref(run_id, artifact_type),
            artifact_type=artifact_type,
            checksum=f"sha256:{checksum}",
            media_type=request.media_type,
            metadata=dict(request.metadata),
        )

    def read_artifact(self, ref: str) -> dict[str, Any]:
        run_id: str | None = None
        try:
            run_id, artifact_type = self._parse_ref(ref)
            result = self._read_artifact(run_id, artifact_type)
        except Exception as exc:
            emit_research_persistence_diagnostic(
                component="artifact_store",
                operation="artifact_read",
                outcome="failed",
                reason=_artifact_failure_reason(exc),
                run_id=run_id,
            )
            raise
        emit_research_persistence_diagnostic(
            component="artifact_store",
            operation="artifact_read",
            outcome="succeeded",
            reason="completed",
            run_id=run_id,
        )
        return result

    def verify_artifact_ref(self, ref: str, *, expected_run_id: str) -> None:
        """Verify canonical artifact integrity without exposing its payload.

        TaskPlan acceptance happens before Research terminal publication. This
        method therefore validates the run binding, manifest, checksum, size,
        and stored bytes directly, while the normal ``read_artifact`` method
        continues to enforce publication visibility for payload readers.
        """

        run_id: str | None = None
        try:
            run_id, artifact_type = self._parse_ref(ref)
            expected = validate_artifact_path_segment(
                expected_run_id,
                field="expected artifact ref run_id",
            )
            if run_id != expected:
                raise ArtifactRunBindingError(
                    "artifact ref run_id does not match the expected parent run"
                )
            manifest = self.manager.read_run_manifest(run_id)
            self._read_artifact_payload(
                manifest,
                run_id=run_id,
                artifact_type=artifact_type,
            )
        except Exception as exc:
            emit_research_persistence_diagnostic(
                component="artifact_store",
                operation="artifact_read",
                outcome="failed",
                reason=_artifact_failure_reason(exc),
                run_id=run_id,
            )
            raise
        emit_research_persistence_diagnostic(
            component="artifact_store",
            operation="artifact_read",
            outcome="succeeded",
            reason="completed",
            run_id=run_id,
        )

    def read_diagnostic_artifact(
        self,
        ref: str,
        *,
        identity_scope_ref: str,
        subject_scope_ref: str | None = None,
    ) -> dict[str, Any]:
        """Read retained quarantine bytes through an explicit scoped resolver.

        This method never upgrades the manifest and never makes it eligible for
        ``read_artifact``.  A legacy Research manifest is always projected as
        ``legacy_quarantined``; a version-2 manifest without accepted
        disposition is projected as ``quarantine``.
        """

        run_id: str | None = None
        try:
            run_id, artifact_type = self._parse_ref(ref)
            manifest = self.manager.read_run_manifest(run_id)
            schema_version = self._publication_schema_version(manifest)
            disposition = (
                "quarantine"
                if schema_version == RESEARCH_ARTIFACT_MANIFEST_VERSION
                else "legacy_quarantined"
            )
            diagnostic_claim = ResearchArtifactDiagnosticClaim(
                run_id=run_id,
                schema_version=schema_version,
                disposition=disposition,
                identity_scope_ref=_validated_checksum_ref(
                    identity_scope_ref,
                    field="diagnostic identity scope",
                    artifact_id=run_id,
                ),
                subject_scope_ref=(
                    _validated_checksum_ref(
                        subject_scope_ref,
                        field="diagnostic subject scope",
                        artifact_id=run_id,
                    )
                    if subject_scope_ref is not None
                    else None
                ),
                artifact_type=artifact_type,
            )
            if not self._resolve_diagnostic_access(diagnostic_claim):
                raise ArtifactPublicationVisibilityError(
                    "Research artifact diagnostic scope is not authorized",
                    disposition=disposition,
                )
            result = self._read_artifact_payload(
                manifest,
                run_id=run_id,
                artifact_type=artifact_type,
                allow_legacy_diagnostic=(
                    schema_version != RESEARCH_ARTIFACT_MANIFEST_VERSION
                ),
            )
        except Exception as exc:
            emit_research_persistence_diagnostic(
                component="artifact_store",
                operation="artifact_read",
                outcome="failed",
                reason=_artifact_failure_reason(exc),
                run_id=run_id,
            )
            raise
        emit_research_persistence_diagnostic(
            component="artifact_store",
            operation="artifact_read",
            outcome="succeeded",
            reason="completed",
            run_id=run_id,
        )
        return result

    def _read_artifact(self, run_id: str, artifact_type: str) -> dict[str, Any]:
        manifest = self.manager.read_run_manifest(run_id)
        schema_version = self._publication_schema_version(manifest)
        if schema_version == RESEARCH_ARTIFACT_MANIFEST_VERSION:
            claim = self._validated_v2_publication_claim(manifest, run_id=run_id)
            if not self._resolve_accepted_run(claim).accepted:
                raise ArtifactPublicationVisibilityError(
                    "Research artifact requires a matching accepted run disposition",
                    disposition="quarantine",
                )
        elif self._accepted_run_resolver is not None and _is_research_manifest(manifest):
            if manifest.get("status") in {
                "failed",
                "halted",
                "cancelled",
                "blocked",
                "waiting_approval",
            }:
                raise ArtifactPublicationVisibilityError(
                    "Research legacy artifact is legacy_quarantined",
                    disposition="legacy_quarantined",
                )
            try:
                claim = self._legacy_publication_claim(manifest, run_id=run_id)
            except ArtifactStoreMetadataError as exc:
                raise ArtifactPublicationVisibilityError(
                    "Research legacy artifact is legacy_quarantined",
                    disposition="legacy_quarantined",
                ) from exc
            resolution = self._resolve_accepted_run(claim)
            if (
                not resolution.accepted
                or resolution.identity_scope_ref is None
                or (
                    claim.identity_scope_ref is not None
                    and resolution.identity_scope_ref != claim.identity_scope_ref
                )
            ):
                raise ArtifactPublicationVisibilityError(
                    "Research legacy artifact is legacy_quarantined",
                    disposition="legacy_quarantined",
                )
        return self._read_artifact_payload(
            manifest,
            run_id=run_id,
            artifact_type=artifact_type,
        )

    def _read_artifact_payload(
        self,
        manifest: dict[str, Any],
        *,
        run_id: str,
        artifact_type: str,
        allow_legacy_diagnostic: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(manifest.get("manifest_hash"), str) and not allow_legacy_diagnostic:
            raise ArtifactStoreMetadataError(
                f"artifact manifest hash is missing: {run_id}"
            )
        relative_path = self._canonical_path(artifact_type)
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict) or artifacts.get(artifact_type) != relative_path:
            raise ArtifactStoreMetadataError(
                f"artifact manifest path mismatch: {artifact_type}"
            )

        try:
            metadata = self._manifest_metadata(
                manifest,
                artifact_type,
                run_id,
                relative_path,
            )
        except ArtifactStoreMetadataError:
            if not allow_legacy_diagnostic:
                raise
            metadata = self._legacy_diagnostic_metadata(
                manifest,
                artifact_type=artifact_type,
                run_id=run_id,
                relative_path=relative_path,
            )
        checksum = validate_sha256_checksum(
            metadata["checksum"],
            artifact_id=artifact_type,
            field="artifact manifest checksum",
        )
        size_bytes = metadata["size_bytes"]
        if not isinstance(size_bytes, int) or size_bytes < 0:
            raise ArtifactStoreMetadataError(
                f"invalid artifact manifest size: {artifact_type}"
            )
        content_type = metadata["content_type"]
        if not isinstance(content_type, str) or not content_type.strip():
            raise ArtifactStoreMetadataError(
                f"invalid artifact manifest content_type: {artifact_type}"
            )
        self._enforce_size(size_bytes, artifact_type)
        content = self.store.read(
            StorageArtifactRef(
                artifact_id=artifact_type,
                run_id=run_id,
                artifact_type=artifact_type,
                path=relative_path,
                content_type=content_type,
                size_bytes=size_bytes,
                checksum=checksum,
            )
        )
        try:
            payload = json.loads(
                content.decode("utf-8"),
                parse_constant=_reject_nonfinite_json,
            )
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ArtifactStoreMetadataError(
                f"invalid artifact JSON: {artifact_type}"
            ) from exc
        if not isinstance(payload, dict):
            raise ArtifactStoreMetadataError(
                f"invalid artifact JSON shape: {artifact_type}"
            )
        if payload.get("artifact_type") != artifact_type:
            raise ArtifactStoreMetadataError(
                f"artifact type mismatch: {artifact_type}"
            )
        payload_metadata = payload.get("metadata")
        if not isinstance(payload_metadata, dict):
            raise ArtifactStoreMetadataError(
                f"artifact metadata shape is invalid: {artifact_type}"
            )
        payload_run_id = payload_metadata.get("run_id")
        if payload_run_id is not None and payload_run_id != run_id:
            raise ArtifactStoreMetadataError(
                f"artifact payload run identity mismatch: {artifact_type}"
            )
        return payload

    def _validated_v2_publication_claim(
        self,
        manifest: dict[str, Any],
        *,
        run_id: str,
    ) -> ResearchArtifactReadClaim:
        identity_scope_ref = _validated_checksum_ref(
            manifest.get("identity_scope_ref"),
            field="publication identity scope",
            artifact_id=run_id,
        )
        subject_scope_ref = _validated_checksum_ref(
            manifest.get("subject_scope_ref"),
            field="publication subject scope",
            artifact_id=run_id,
        )
        publication_authority_ref = _validated_checksum_ref(
            manifest.get("publication_authority_ref"),
            field="publication authority",
            artifact_id=run_id,
        )
        terminal_outcome_ref = _validated_checksum_ref(
            manifest.get("terminal_side_effect_outcome_ref"),
            field="terminal side-effect outcome",
            artifact_id=run_id,
        )

        artifact_types = self._v2_artifact_types(manifest, run_id=run_id)
        artifact_refs = {
            artifact_type: self._canonical_ref(run_id, artifact_type)
            for artifact_type in artifact_types
        }
        expected_artifact_evidence_ref = artifact_evidence_ref(artifact_refs)
        persisted_artifact_evidence_ref = _validated_checksum_ref(
            manifest.get("artifact_evidence_ref"),
            field="artifact evidence",
            artifact_id=run_id,
        )
        if persisted_artifact_evidence_ref != expected_artifact_evidence_ref:
            raise ArtifactStoreMetadataError(
                f"Research artifact evidence mismatch: {run_id}"
            )

        member_evidence: list[dict[str, Any]] = []
        for artifact_type in artifact_types:
            relative_path = self._canonical_path(artifact_type)
            metadata = self._manifest_metadata(
                manifest,
                artifact_type,
                run_id,
                relative_path,
            )
            checksum = validate_sha256_checksum(
                metadata.get("checksum"),
                artifact_id=artifact_type,
                field="artifact manifest checksum",
            )
            size_bytes = metadata.get("size_bytes")
            if not isinstance(size_bytes, int) or size_bytes < 0:
                raise ArtifactStoreMetadataError(
                    f"invalid artifact manifest size: {artifact_type}"
                )
            content_type = metadata.get("content_type")
            if not isinstance(content_type, str) or not content_type.strip():
                raise ArtifactStoreMetadataError(
                    f"invalid artifact manifest content_type: {artifact_type}"
                )
            if (
                metadata.get("identity_scope_ref") != identity_scope_ref
                or metadata.get("subject_scope_ref") != subject_scope_ref
                or metadata.get("publication_authority_ref")
                != publication_authority_ref
                or metadata.get("artifact_evidence_ref")
                != persisted_artifact_evidence_ref
            ):
                raise ArtifactStoreMetadataError(
                    f"Research artifact member authority mismatch: {artifact_type}"
                )
            member_evidence.append(
                {
                    "artifact_type": artifact_type,
                    "artifact_ref": artifact_refs[artifact_type],
                    "path": relative_path,
                    "checksum": f"sha256:{checksum}",
                    "size_bytes": size_bytes,
                    "content_type": content_type,
                }
            )
            # Verify every member before asking the accepted-run resolver.  The
            # resolver therefore never authorizes a manifest whose group bytes
            # have drifted from its terminal outcome.
            self.store.read(
                StorageArtifactRef(
                    artifact_id=artifact_type,
                    run_id=run_id,
                    artifact_type=artifact_type,
                    path=relative_path,
                    content_type=content_type,
                    size_bytes=size_bytes,
                    checksum=checksum,
                )
            )

        expected_member_evidence_ref = artifact_member_evidence_ref(member_evidence)
        persisted_member_evidence_ref = _validated_checksum_ref(
            manifest.get("artifact_member_evidence_ref"),
            field="artifact member evidence",
            artifact_id=run_id,
        )
        if persisted_member_evidence_ref != expected_member_evidence_ref:
            raise ArtifactStoreMetadataError(
                f"Research artifact member evidence mismatch: {run_id}"
            )
        persisted_member_evidence = manifest.get("artifact_member_evidence")
        if not isinstance(persisted_member_evidence, list):
            raise ArtifactStoreMetadataError(
                f"Research artifact member evidence is missing: {run_id}"
            )
        if not all(isinstance(item, Mapping) for item in persisted_member_evidence):
            raise ArtifactStoreMetadataError(
                f"Research artifact member evidence projection is invalid: {run_id}"
            )
        if sorted(persisted_member_evidence, key=lambda item: str(item.get("artifact_type"))) != sorted(
            member_evidence,
            key=lambda item: str(item.get("artifact_type")),
        ):
            raise ArtifactStoreMetadataError(
                f"Research artifact member evidence projection mismatch: {run_id}"
            )
        if manifest.get("terminal_publication_authority_ref") != publication_authority_ref:
            raise ArtifactStoreMetadataError(
                f"Research terminal publication authority mismatch: {run_id}"
            )

        outcome = self._validated_terminal_outcome(
            manifest,
            run_id=run_id,
            identity_scope_ref=identity_scope_ref,
            subject_scope_ref=subject_scope_ref,
            publication_authority_ref=publication_authority_ref,
            terminal_outcome_ref=terminal_outcome_ref,
            artifact_refs=artifact_refs,
            artifact_evidence_ref_value=persisted_artifact_evidence_ref,
            member_evidence_ref=persisted_member_evidence_ref,
            member_evidence=member_evidence,
        )
        if outcome.checksum != terminal_outcome_ref:
            raise ArtifactStoreMetadataError(
                f"Research terminal outcome checksum mismatch: {run_id}"
            )
        return ResearchArtifactReadClaim(
            run_id=run_id,
            schema_version=RESEARCH_ARTIFACT_MANIFEST_VERSION,
            identity_scope_ref=identity_scope_ref,
            subject_scope_ref=subject_scope_ref,
            publication_authority_ref=publication_authority_ref,
            artifact_evidence_ref=persisted_artifact_evidence_ref,
            terminal_side_effect_outcome_ref=terminal_outcome_ref,
            artifact_refs=tuple(sorted(artifact_refs.items())),
            member_checksums=tuple(
                sorted(
                    (
                        member["artifact_type"],
                        member["checksum"],
                    )
                    for member in member_evidence
                )
            ),
        )

    @staticmethod
    def _publication_schema_version(manifest: dict[str, Any]) -> str:
        value = manifest.get("publication_schema_version")
        if value is None:
            return RESEARCH_ARTIFACT_LEGACY_MANIFEST_VERSION
        if not isinstance(value, str) or value not in {
            RESEARCH_ARTIFACT_LEGACY_MANIFEST_VERSION,
            RESEARCH_ARTIFACT_MANIFEST_VERSION,
        }:
            raise ArtifactStoreMetadataError(
                "Research artifact publication schema is unsupported"
            )
        return value

    def _legacy_publication_claim(
        self,
        manifest: dict[str, Any],
        *,
        run_id: str,
    ) -> ResearchArtifactReadClaim:
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict):
            raise ArtifactStoreMetadataError(
                f"Research legacy artifact manifest is invalid: {run_id}"
            )
        legacy_refs: list[tuple[str, str]] = []
        for artifact_type, path in artifacts.items():
            if artifact_type == "manifest":
                continue
            if not isinstance(artifact_type, str):
                raise ArtifactStoreMetadataError(
                    f"Research legacy artifact identity is invalid: {run_id}"
                )
            validate_artifact_path_segment(artifact_type, field="artifact_type")
            if path != self._canonical_path(artifact_type):
                raise ArtifactStoreMetadataError(
                    f"Research legacy artifact path mismatch: {artifact_type}"
                )
            legacy_refs.append(
                (artifact_type, self._canonical_ref(run_id, artifact_type))
            )
        artifact_refs = tuple(sorted(legacy_refs))
        member_checksums: list[tuple[str, str]] = []
        for artifact_type, _ in artifact_refs:
            metadata = self._manifest_metadata(
                manifest,
                artifact_type,
                run_id,
                self._canonical_path(artifact_type),
            )
            checksum = validate_sha256_checksum(
                metadata.get("checksum"),
                artifact_id=artifact_type,
                field="artifact manifest checksum",
            )
            size_bytes = metadata.get("size_bytes")
            content_type = metadata.get("content_type")
            if (
                not isinstance(size_bytes, int)
                or size_bytes < 0
                or not isinstance(content_type, str)
                or not content_type.strip()
            ):
                raise ArtifactStoreMetadataError(
                    f"Research legacy artifact metadata is invalid: {artifact_type}"
                )
            self.store.read(
                StorageArtifactRef(
                    artifact_id=artifact_type,
                    run_id=run_id,
                    artifact_type=artifact_type,
                    path=self._canonical_path(artifact_type),
                    content_type=content_type,
                    size_bytes=size_bytes,
                    checksum=checksum,
                )
            )
            member_checksums.append((artifact_type, f"sha256:{checksum}"))
        if not artifact_refs:
            raise ArtifactStoreMetadataError(
                f"Research legacy artifact evidence is missing: {run_id}"
            )
        persisted_scope_ref = _optional_checksum_ref(
            manifest.get("identity_scope_ref"),
            field="legacy identity scope",
            artifact_id=run_id,
        )
        if (
            persisted_scope_ref is not None
            and self._legacy_identity_scope_ref is not None
            and persisted_scope_ref != self._legacy_identity_scope_ref
        ):
            raise ArtifactStoreMetadataError(
                f"Research legacy artifact identity scope conflicts: {run_id}"
            )
        resolved_scope_ref = persisted_scope_ref or self._legacy_identity_scope_ref
        refs_map = dict(artifact_refs)
        derived_artifact_evidence = artifact_evidence_ref(refs_map)
        persisted_artifact_evidence = _optional_checksum_ref(
            manifest.get("artifact_evidence_ref"),
            field="legacy artifact evidence",
            artifact_id=run_id,
        )
        if (
            persisted_artifact_evidence is not None
            and persisted_artifact_evidence != derived_artifact_evidence
        ):
            raise ArtifactStoreMetadataError(
                f"Research legacy artifact evidence conflicts: {run_id}"
            )
        return ResearchArtifactReadClaim(
            run_id=run_id,
            schema_version=RESEARCH_ARTIFACT_LEGACY_MANIFEST_VERSION,
            identity_scope_ref=resolved_scope_ref,
            subject_scope_ref=_optional_checksum_ref(
                manifest.get("subject_scope_ref"),
                field="legacy subject scope",
                artifact_id=run_id,
            ),
            publication_authority_ref=_optional_checksum_ref(
                manifest.get("publication_authority_ref"),
                field="legacy publication authority",
                artifact_id=run_id,
            ),
            artifact_evidence_ref=derived_artifact_evidence,
            terminal_side_effect_outcome_ref=_optional_checksum_ref(
                manifest.get("terminal_side_effect_outcome_ref"),
                field="legacy terminal side-effect outcome",
                artifact_id=run_id,
            ),
            artifact_refs=artifact_refs,
            member_checksums=tuple(member_checksums),
        )

    def _v2_artifact_types(
        self,
        manifest: dict[str, Any],
        *,
        run_id: str,
    ) -> tuple[str, ...]:
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict):
            raise ArtifactStoreMetadataError(
                f"Research artifact manifest is invalid: {run_id}"
            )
        artifact_types: list[str] = []
        for artifact_type, path in artifacts.items():
            if artifact_type == "manifest":
                if path != "manifest.json":
                    raise ArtifactStoreMetadataError(
                        f"Research manifest path mismatch: {run_id}"
                    )
                continue
            if not isinstance(artifact_type, str):
                raise ArtifactStoreMetadataError(
                    f"Research artifact identity is invalid: {run_id}"
                )
            validate_artifact_path_segment(artifact_type, field="artifact_type")
            if path != self._canonical_path(artifact_type):
                raise ArtifactStoreMetadataError(
                    f"Research artifact path mismatch: {artifact_type}"
                )
            if _is_verified_context_ref_only_artifact(
                manifest,
                artifact_type=artifact_type,
                path=path,
            ):
                continue
            artifact_types.append(artifact_type)
        if not artifact_types:
            raise ArtifactStoreMetadataError(
                f"Research artifact manifest has no published members: {run_id}"
            )
        return tuple(sorted(artifact_types))

    @staticmethod
    def _validated_terminal_outcome(
        manifest: dict[str, Any],
        *,
        run_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
        publication_authority_ref: str,
        terminal_outcome_ref: str,
        artifact_refs: dict[str, str],
        artifact_evidence_ref_value: str,
        member_evidence_ref: str,
        member_evidence: list[dict[str, Any]],
    ) -> HarnessSideEffectOutcome:
        payload = manifest.get("terminal_side_effect_outcome")
        if not isinstance(payload, dict):
            raise ArtifactStoreMetadataError(
                f"Research terminal outcome is missing: {run_id}"
            )
        try:
            outcome = HarnessSideEffectOutcome.from_dict(payload)
        except Exception as exc:
            raise ArtifactStoreMetadataError(
                f"Research terminal outcome is invalid: {run_id}"
            ) from exc
        if (
            outcome.checksum != terminal_outcome_ref
            or outcome.run_id != run_id
            or outcome.identity_scope_ref != identity_scope_ref
            or outcome.subject_scope_ref != subject_scope_ref
            or outcome.decision_ref != publication_authority_ref
            or outcome.disposition is not HarnessSideEffectDisposition.ACCEPTED
            or tuple(sorted(outcome.public_refs))
            != tuple(sorted(artifact_refs.values()))
        ):
            raise ArtifactStoreMetadataError(
                f"Research terminal outcome authority mismatch: {run_id}"
            )
        metadata = outcome.metadata
        if (
            dict(metadata.get("artifact_refs") or {}) != artifact_refs
            or metadata.get("publication_authority_ref")
            != publication_authority_ref
            or metadata.get("artifact_evidence_ref")
            != artifact_evidence_ref_value
            or metadata.get("artifact_member_evidence_ref")
            != member_evidence_ref
        ):
            raise ArtifactStoreMetadataError(
                f"Research terminal outcome evidence mismatch: {run_id}"
            )
        persisted_members = metadata.get("members")
        if not isinstance(persisted_members, (list, tuple)):
            raise ArtifactStoreMetadataError(
                f"Research terminal outcome members are missing: {run_id}"
            )
        expected_members = {
            member["artifact_type"]: {
                "checksum": member["checksum"].removeprefix("sha256:"),
                "size_bytes": member["size_bytes"],
                "content_type": member["content_type"],
                "canonical_path": member["path"],
            }
            for member in member_evidence
        }
        actual_members: dict[str, dict[str, Any]] = {}
        for item in persisted_members:
            if not isinstance(item, Mapping) or not isinstance(
                item.get("artifact_type"), str
            ):
                raise ArtifactStoreMetadataError(
                    f"Research terminal outcome member is invalid: {run_id}"
                )
            artifact_type = item["artifact_type"]
            actual_members[artifact_type] = {
                "checksum": item.get("checksum"),
                "size_bytes": item.get("size_bytes"),
                "content_type": item.get("content_type"),
                "canonical_path": item.get("canonical_path"),
            }
        if actual_members != expected_members:
            raise ArtifactStoreMetadataError(
                f"Research terminal outcome member evidence mismatch: {run_id}"
            )
        return outcome

    def _resolve_accepted_run(
        self,
        claim: ResearchArtifactReadClaim,
    ) -> ResearchArtifactReadResolution:
        resolver = self._accepted_run_resolver
        if resolver is None:
            return ResearchArtifactReadResolution(accepted=False)
        raw_resolution = _invoke_evidence_resolver(
            resolver,
            claim,
            legacy_args=(
                claim.run_id,
                claim.identity_scope_ref,
                claim.publication_authority_ref,
            ),
            expanded_args=(
                claim.run_id,
                claim.identity_scope_ref,
                claim.subject_scope_ref,
                claim.publication_authority_ref,
                claim.artifact_evidence_ref,
                claim.terminal_side_effect_outcome_ref,
                claim.member_checksums,
            ),
        )
        if isinstance(raw_resolution, ResearchArtifactReadResolution):
            resolution = raw_resolution
        else:
            accepted = bool(raw_resolution)
            resolution = ResearchArtifactReadResolution(
                accepted=accepted,
                identity_scope_ref=(
                    claim.identity_scope_ref if accepted else None
                ),
            )
        if not resolution.accepted:
            return ResearchArtifactReadResolution(accepted=False)
        resolved_scope = resolution.identity_scope_ref
        if resolved_scope is None:
            return resolution
        try:
            validated_scope = _validated_checksum_ref(
                resolved_scope,
                field="resolved accepted-run identity scope",
                artifact_id=claim.run_id,
            )
        except ArtifactStoreMetadataError:
            return ResearchArtifactReadResolution(accepted=False)
        if (
            claim.identity_scope_ref is not None
            and validated_scope != claim.identity_scope_ref
        ):
            return ResearchArtifactReadResolution(accepted=False)
        return ResearchArtifactReadResolution(
            accepted=True,
            identity_scope_ref=validated_scope,
        )

    def _resolve_diagnostic_access(
        self,
        claim: ResearchArtifactDiagnosticClaim,
    ) -> bool:
        resolver = self._diagnostic_run_resolver
        if resolver is None:
            return False
        return bool(
            _invoke_evidence_resolver(
                resolver,
                claim,
                legacy_args=(
                    claim.run_id,
                    claim.identity_scope_ref,
                    claim.subject_scope_ref,
                ),
                expanded_args=(
                    claim.run_id,
                    claim.identity_scope_ref,
                    claim.subject_scope_ref,
                    claim.disposition,
                    claim.artifact_type,
                ),
            )
        )

    def _legacy_diagnostic_metadata(
        self,
        manifest: dict[str, Any],
        *,
        artifact_type: str,
        run_id: str,
        relative_path: str,
    ) -> dict[str, Any]:
        if self._publication_schema_version(manifest) == RESEARCH_ARTIFACT_MANIFEST_VERSION:
            raise ArtifactStoreMetadataError(
                f"version-2 artifact metadata is invalid: {artifact_type}"
            )
        content = self.store.read(
            StorageArtifactRef(
                artifact_id=artifact_type,
                run_id=run_id,
                artifact_type=artifact_type,
                path=relative_path,
                content_type="application/json",
            )
        )
        return {
            "artifact_id": artifact_type,
            "run_id": run_id,
            "kind": artifact_type,
            "path": relative_path,
            "content_type": "application/json",
            "size_bytes": len(content),
            "checksum": compute_checksum(content),
        }

    def _existing_artifact_result(
        self,
        *,
        run_id: str,
        artifact_type: str,
        request: ArtifactWriteRequest,
        content: bytes,
        checksum: str,
    ) -> HarnessArtifactRef | None:
        manifest = self.manager.read_run_manifest(run_id)
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict) or artifact_type not in artifacts:
            return None
        existing_path = artifacts.get(artifact_type)
        expected_path = self._canonical_path(artifact_type)
        if existing_path != expected_path:
            raise ArtifactStoreMetadataError(
                f"artifact manifest path mismatch: {artifact_type}"
            )
        metadata = self._manifest_metadata(
            manifest,
            artifact_type,
            run_id,
            expected_path,
        )
        existing_checksum = validate_sha256_checksum(
            metadata["checksum"],
            artifact_id=artifact_type,
            field="artifact manifest checksum",
        )
        existing_size = metadata.get("size_bytes")
        existing_content_type = metadata.get("content_type")
        if (
            existing_checksum != checksum
            or existing_size != len(content)
            or existing_content_type != request.media_type
        ):
            raise ArtifactWriteConflictError(
                f"immutable artifact already exists with different content: {artifact_type}"
            )
        existing_payload = self._read_artifact(run_id, artifact_type)
        if stable_json_dumps(existing_payload) != stable_json_dumps(request.to_dict()):
            raise ArtifactWriteConflictError(
                f"immutable artifact metadata conflicts: {artifact_type}"
            )
        return HarnessArtifactRef(
            ref=self._canonical_ref(run_id, artifact_type),
            artifact_type=artifact_type,
            checksum=f"sha256:{existing_checksum}",
            media_type=str(existing_content_type),
            metadata=dict(request.metadata),
        )

    def _require_bound_run(self) -> str:
        run_id = self._run_binding.get()
        if run_id is None:
            raise ArtifactRunBindingError("artifact write requires a bound run")
        return run_id

    def _ensure_run_manifest(self, run_id: str) -> None:
        try:
            self.manager.read_run_manifest(run_id)
            return
        except ArtifactNotFoundError:
            pass
        started_at = format_datetime(utc_now()) or ""
        self.manager.create_run_manifest(
            run_id=run_id,
            workflow_id="research.paper_analysis",
            workflow_version="1",
            profile="research",
            status="running",
            started_at=started_at,
            run_type="research",
        )

    def _manifest_metadata(
        self,
        manifest: dict[str, Any],
        artifact_type: str,
        run_id: str,
        relative_path: str,
    ) -> dict[str, Any]:
        all_metadata = manifest.get("artifact_metadata")
        if not isinstance(all_metadata, dict):
            raise ArtifactStoreMetadataError(
                f"artifact manifest metadata is missing: {artifact_type}"
            )
        metadata = all_metadata.get(artifact_type)
        if not isinstance(metadata, dict):
            raise ArtifactStoreMetadataError(
                f"artifact manifest metadata is missing: {artifact_type}"
            )
        if metadata.get("artifact_id") != artifact_type:
            raise ArtifactStoreMetadataError(
                f"artifact manifest artifact identity mismatch: {artifact_type}"
            )
        if metadata.get("run_id") != run_id:
            raise ArtifactStoreMetadataError(
                f"artifact manifest run identity mismatch: {artifact_type}"
            )
        if metadata.get("path") != relative_path:
            raise ArtifactStoreMetadataError(
                f"artifact manifest path mismatch: {artifact_type}"
            )

        refs = manifest.get("artifact_refs")
        ref = _find_manifest_entry(refs, artifact_type)
        if ref is None:
            raise ArtifactStoreMetadataError(
                f"artifact manifest ref is missing: {artifact_type}"
            )
        if (ref.get("uri") or ref.get("path")) != relative_path:
            raise ArtifactStoreMetadataError(
                f"artifact manifest ref path mismatch: {artifact_type}"
            )
        if (ref.get("content_hash") or ref.get("checksum")) != metadata.get("checksum"):
            raise ArtifactStoreMetadataError(
                f"artifact manifest ref checksum mismatch: {artifact_type}"
            )
        if ref.get("size_bytes") != metadata.get("size_bytes"):
            raise ArtifactStoreMetadataError(
                f"artifact manifest ref size mismatch: {artifact_type}"
            )

        index = manifest.get("artifact_index")
        indexed = _find_manifest_entry(index, artifact_type)
        if indexed is None:
            raise ArtifactStoreMetadataError(
                f"artifact manifest index is missing: {artifact_type}"
            )
        if indexed.get("run_id") != run_id or indexed.get("path") != relative_path:
            raise ArtifactStoreMetadataError(
                f"artifact manifest index identity mismatch: {artifact_type}"
            )
        if indexed.get("checksum") != metadata.get("checksum"):
            raise ArtifactStoreMetadataError(
                f"artifact manifest index checksum mismatch: {artifact_type}"
            )
        if indexed.get("size_bytes") != metadata.get("size_bytes"):
            raise ArtifactStoreMetadataError(
                f"artifact manifest index size mismatch: {artifact_type}"
            )
        return metadata

    def _enforce_size(self, content_or_size: bytes | int, artifact_type: str) -> None:
        if self.max_write_bytes is None:
            return
        size = len(content_or_size) if isinstance(content_or_size, bytes) else content_or_size
        if size > self.max_write_bytes:
            raise ValueError(
                f"artifact exceeds max_write_bytes: {artifact_type} ({size} > {self.max_write_bytes})"
            )

    @staticmethod
    def _canonical_path(artifact_type: str) -> str:
        file_name = f"{artifact_type}.json"
        if len(file_name) > 80:
            file_name = f"a-{hash_text(artifact_type)}.json"
        return f"{CANONICAL_ARTIFACT_DIRECTORY}/{file_name}"

    @staticmethod
    def _canonical_ref(run_id: str, artifact_type: str) -> str:
        return f"{CANONICAL_ARTIFACT_SCHEME}://{run_id}/{artifact_type}"

    @staticmethod
    def _parse_ref(ref: str) -> tuple[str, str]:
        if not isinstance(ref, str) or not ref:
            raise ArtifactStoreMetadataError("artifact ref is required")
        try:
            parsed = urlsplit(ref)
        except ValueError as exc:
            raise ArtifactStoreMetadataError("artifact ref is invalid") from exc
        if parsed.scheme != CANONICAL_ARTIFACT_SCHEME or parsed.query or parsed.fragment:
            raise ArtifactStoreMetadataError("artifact ref is not canonical")
        if not parsed.netloc or ":" in parsed.netloc or parsed.path.count("/") != 1:
            raise ArtifactStoreMetadataError("artifact ref is not canonical")
        run_id = validate_artifact_path_segment(parsed.netloc, field="artifact ref run_id")
        artifact_type = validate_artifact_path_segment(
            parsed.path.lstrip("/"),
            field="artifact ref artifact_type",
        )
        canonical = FilesystemHarnessArtifactPort._canonical_ref(run_id, artifact_type)
        if ref != canonical:
            raise ArtifactStoreMetadataError("artifact ref is not canonical")
        return run_id, artifact_type


def _find_manifest_entry(entries: Any, artifact_id: str) -> dict[str, Any] | None:
    if not isinstance(entries, list):
        return None
    for item in entries:
        if isinstance(item, dict) and item.get("artifact_id") == artifact_id:
            return item
    return None


def _is_research_manifest(manifest: Mapping[str, Any]) -> bool:
    return (
        manifest.get("run_type") == "research"
        or manifest.get("profile") == "research"
        or (
            isinstance(manifest.get("workflow_id"), str)
            and manifest["workflow_id"].startswith("research.")
        )
    )


def _validated_checksum_ref(
    value: Any,
    *,
    field: str,
    artifact_id: str,
) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ArtifactStoreMetadataError(
            f"invalid {field} for artifact {artifact_id}"
        )
    digest = validate_sha256_checksum(
        value.removeprefix("sha256:"),
        artifact_id=artifact_id,
        field=field,
    )
    return f"sha256:{digest}"


def _optional_checksum_ref(
    value: Any,
    *,
    field: str,
    artifact_id: str,
) -> str | None:
    if value is None:
        return None
    return _validated_checksum_ref(value, field=field, artifact_id=artifact_id)


def _invoke_evidence_resolver(
    resolver: Callable[..., bool],
    claim: ResearchArtifactReadClaim | ResearchArtifactDiagnosticClaim,
    *,
    legacy_args: tuple[Any, ...],
    expanded_args: tuple[Any, ...],
) -> Any:
    """Call old and new resolver shapes without hiding resolver failures."""

    try:
        signature = inspect.signature(resolver)
    except (TypeError, ValueError):
        return resolver(claim)
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    has_varargs = any(
        parameter.kind is inspect.Parameter.VAR_POSITIONAL
        for parameter in signature.parameters.values()
    )
    if has_varargs:
        return resolver(*expanded_args)
    if len(positional) <= 1:
        return resolver(claim)
    if len(positional) > len(legacy_args):
        return resolver(*expanded_args[: len(positional)])
    return resolver(*legacy_args)


def _assert_finite_json(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ArtifactStoreMetadataError("artifact JSON contains non-finite number")
    if isinstance(value, dict):
        for item in value.values():
            _assert_finite_json(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _assert_finite_json(item)


def _reject_nonfinite_json(value: str) -> Any:
    raise ArtifactStoreMetadataError(
        f"artifact JSON contains non-finite number: {value}"
    )


def _artifact_failure_reason(exc: Exception) -> str:
    if isinstance(exc, ArtifactRunBindingError):
        return "run_binding_invalid"
    if isinstance(exc, ArtifactWriteConflictError):
        return "write_conflict"
    if isinstance(exc, ArtifactChecksumMismatchError):
        return "checksum_invalid"
    if isinstance(exc, ArtifactStoreMetadataError):
        return "metadata_invalid"
    if isinstance(exc, (TypeError, ValueError)):
        return "invalid_input"
    if isinstance(exc, OSError):
        return "filesystem_unavailable"
    return "other"


def _is_verified_context_ref_only_artifact(
    manifest: Mapping[str, Any],
    *,
    artifact_type: Any,
    path: Any,
) -> bool:
    if not isinstance(artifact_type, str) or not isinstance(path, str):
        return False
    identity_suffix: str | None = None
    for allowed_type in _CONTEXT_REF_ONLY_ARTIFACT_TYPES:
        prefix = f"{allowed_type}-"
        if artifact_type.startswith(prefix):
            identity_suffix = artifact_type.removeprefix(prefix)
            break
    if identity_suffix is None or len(identity_suffix) != 64:
        return False
    try:
        int(identity_suffix, 16)
    except ValueError:
        return False
    artifact_index = manifest.get("artifact_index")
    if not isinstance(artifact_index, list):
        return False
    matches = [
        item
        for item in artifact_index
        if isinstance(item, Mapping)
        and item.get("artifact_id") == artifact_type
        and item.get("kind") == artifact_type
        and item.get("path") == path
    ]
    if len(matches) != 1:
        return False
    metadata = matches[0].get("metadata")
    return (
        isinstance(metadata, Mapping)
        and metadata.get("context_ref_only") is True
        and metadata.get("identity_checksum") == f"sha256:{identity_suffix}"
    )


__all__ = [
    "ArtifactRunBindingError",
    "ArtifactPublicationVisibilityError",
    "ArtifactWriteConflictError",
    "CANONICAL_ARTIFACT_DIRECTORY",
    "CANONICAL_ARTIFACT_SCHEME",
    "FilesystemHarnessArtifactPort",
]
