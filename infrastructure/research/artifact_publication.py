"""Harness-owned Research artifact preparation and terminal publication.

The adapter deliberately keeps the existing ``FilesystemHarnessArtifactPort``
as the only JSON/path/checksum runtime.  This module only supplies the
side-effect handler boundary around it: worker authorization writes hidden
candidate files, while the controller-terminal authorization performs the
single manifest visibility commit.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from framework.agent.artifacts import (
    ArtifactNotFoundError,
    ArtifactStoreMetadataError,
    compute_checksum,
    validate_artifact_path_segment,
)
from framework.agent.artifacts.models import ArtifactRef as StorageArtifactRef
from framework.events.canonical import checksum_for
from framework.harness import (
    ArtifactWriteRequest,
    HarnessSideEffectDecision,
    HarnessSideEffectDisposition,
    HarnessSideEffectIntent,
    HarnessSideEffectOrigin,
    HarnessSideEffectOutcome,
    HarnessSideEffectStorePort,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.artifacts import (
    GraphTerminalArtifact,
    GraphTerminalManifest,
    GraphTerminalManifestContext,
    GraphTerminalPublicationEvidence,
)
from framework.shared.hashing import hash_text
from framework.shared.json import stable_json_dumps
from framework.shared.time import utc_now

from business.research.ports.artifact_publication import (
    RESEARCH_ARTIFACT_EFFECT_KIND,
    RESEARCH_ARTIFACT_HANDLER_ID,
    RESEARCH_ARTIFACT_HANDLER_REF,
    RESEARCH_ARTIFACT_HANDLER_VERSION,
    RESEARCH_ARTIFACT_MANIFEST_VERSION,
    RESEARCH_ARTIFACT_SCHEMA_VERSION,
    artifact_evidence_ref,
    artifact_member_evidence_ref,
)

from infrastructure.research.artifact_port import (
    ArtifactWriteConflictError,
    FilesystemHarnessArtifactPort,
    is_verified_internal_staged_artifact,
)


# Keep the on-disk staging segment compact for Windows path-length limits.  Its
# semantic role is carried by the manifest/outcome metadata and not by the
# directory spelling.
_CANDIDATE_ROOT = ".rc"
_DEFAULT_RETENTION = timedelta(hours=24)


TerminalArtifactPayloadFactory = Callable[
    [str | None],
    Mapping[str, ArtifactWriteRequest] | tuple[ArtifactWriteRequest, ...],
]
CandidateArtifactPayloadFactory = Callable[
    [HarnessSideEffectIntent],
    tuple[ArtifactWriteRequest, ...],
]


class ResearchArtifactBundleHandler:
    """Prepare and publish one run-scoped Research artifact bundle.

    ``prepare`` is the worker-originated handler and never changes the
    canonical manifest or index.  ``commit`` is the controller-terminal
    handler and is the only method that can expose the bundle to normal
    readers.  The handler is intentionally instance-scoped so two concurrent
    runs cannot share candidate state.
    """

    def __init__(
        self,
        *,
        artifact_port: FilesystemHarnessArtifactPort,
        side_effect_store: HarnessSideEffectStorePort,
        terminal_payload_factory: TerminalArtifactPayloadFactory | None = None,
        candidate_payload_factory: CandidateArtifactPayloadFactory | None = None,
        retention: timedelta = _DEFAULT_RETENTION,
        failure_injector: Callable[[int, str, str], None] | None = None,
    ) -> None:
        if not isinstance(artifact_port, FilesystemHarnessArtifactPort):
            raise TypeError("ResearchArtifactBundleHandler requires FilesystemHarnessArtifactPort")
        if not isinstance(retention, timedelta) or retention.total_seconds() <= 0:
            raise ValueError("retention must be positive")
        self.artifact_port = artifact_port
        self.side_effect_store = side_effect_store
        self.terminal_payload_factory = terminal_payload_factory
        self.candidate_payload_factory = candidate_payload_factory
        self.retention = retention
        self.failure_injector = failure_injector
        self.prepare_calls = 0
        self.commit_calls = 0

    def prepare(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome:
        self.prepare_calls += 1
        _assert_worker_authority(intent, authorization)
        existing = self._existing_prepared_outcome(intent, authorization)
        if existing is not None:
            self._verify_prepared_outcome(intent, existing)
            return existing
        members = self._resolved_bundle_members(intent)
        candidate_dir = self._candidate_dir(intent)
        self._remove_owned_candidate(intent.run_id, candidate_dir)
        try:
            records: list[dict[str, Any]] = []
            for index, member in enumerate(members, start=1):
                artifact_type = member["artifact_type"]
                if self.failure_injector is not None:
                    self.failure_injector(index, artifact_type, "prepare")
                request = _member_request(member)
                content = _request_bytes(request)
                checksum = compute_checksum(content)
                relative_path = self._candidate_relative_path(intent, artifact_type)
                self.artifact_port.manager.write_bytes(
                    intent.run_id,
                    relative_path,
                    content,
                )
                self._verify_bytes(
                    intent.run_id,
                    relative_path,
                    artifact_type,
                    checksum,
                    len(content),
                )
                records.append(
                    {
                        "artifact_type": artifact_type,
                        "candidate_ref": _candidate_ref(
                            intent.run_id,
                            intent.effect_id,
                            artifact_type,
                        ),
                        "candidate_path": relative_path,
                        "canonical_path": f"artifacts/{artifact_type}.json",
                        "checksum": checksum,
                        "size_bytes": len(content),
                        "content_type": request.media_type,
                        "metadata": dict(request.metadata),
                        "node_id": intent.step_id,
                        "attempt_id": f"attempt-{intent.attempt}",
                        "required_for_replay": True,
                        "required_for_publication": True,
                    }
                )
            candidate_refs = tuple(record["candidate_ref"] for record in records)
            committed_at = utc_now()
            retention_until = committed_at + self.retention
            metadata = {
                "schema_version": RESEARCH_ARTIFACT_SCHEMA_VERSION,
                "candidate_root": candidate_dir.relative_to(
                    self.artifact_port.manager.run_dir(intent.run_id)
                ).as_posix(),
                "members": records,
                "bundle_checksum": _bundle_checksum(records),
            }
            return HarnessSideEffectOutcome(
                outcome_id=f"research-artifact-prepared:{hash_text(intent.effect_id)}",
                effect_id=intent.effect_id,
                decision_ref=authorization.checksum,
                run_id=intent.run_id,
                kind=intent.kind,
                handler=authorization.handler,
                idempotency_key=intent.idempotency_key,
                identity_scope_ref=intent.identity_scope_ref,
                subject_scope_ref=intent.subject_scope_ref,
                atomic_group=intent.atomic_group,
                disposition=HarnessSideEffectDisposition.PREPARED,
                candidate_refs=candidate_refs,
                result_ref=_bundle_checksum(records),
                reason_code="prepared",
                committed_at=committed_at,
                retention_until=retention_until,
                metadata=metadata,
            )
        except BaseException:
            # A failed member is never allowed to leave a candidate that can
            # accidentally be mistaken for a later publication.
            self._remove_owned_candidate(intent.run_id, candidate_dir)
            raise

    def commit(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome:
        self.commit_calls += 1
        _assert_terminal_authority(intent, authorization)
        if self.terminal_payload_factory is None:
            raise HarnessValidationError(
                "terminal Research artifact publication requires a payload factory"
            )
        prepared = self._prepared_outcomes(intent)
        if not prepared:
            raise HarnessValidationError(
                "terminal Research artifact publication has no prepared outcome",
                code="research_prepared_outcome_missing",
            )
        atomic_groups = {outcome.atomic_group for outcome in prepared}
        if atomic_groups != {intent.atomic_group}:
            raise HarnessValidationError(
                "prepared Research artifacts do not share the terminal atomic group",
                code="research_atomic_group_mismatch",
            )

        # A crash after the manifest replace but before outcome persistence is
        # recovered from the manifest's immutable outcome projection.
        existing = self._existing_terminal_outcome(
            intent,
            authorization,
        )
        if existing is not None:
            self._cleanup_prepared_candidates(prepared)
            return existing

        prepared_members = [
            member
            for outcome in prepared
            for member in _outcome_members(outcome)
        ]
        if len({member["artifact_type"] for member in prepared_members}) != len(
            prepared_members
        ):
            raise HarnessValidationError(
                "prepared Research artifact members must be unique",
                code="research_artifact_member_duplicate",
            )
        cutoff = _history_cutoff(intent)
        terminal_payloads = self.terminal_payload_factory(cutoff)
        terminal_members = _coerce_terminal_payloads(terminal_payloads)
        all_members = [*prepared_members]
        existing_types = {member["artifact_type"] for member in all_members}
        for request in terminal_members:
            if request.artifact_type in existing_types:
                raise HarnessValidationError(
                    f"terminal Research artifact conflicts with prepared member: {request.artifact_type}",
                    code="research_artifact_member_duplicate",
                )
            content = _request_bytes(request)
            all_members.append(
                {
                    "artifact_type": request.artifact_type,
                    "request": request,
                    "checksum": compute_checksum(content),
                    "size_bytes": len(content),
                    "content_type": request.media_type,
                    "metadata": dict(request.metadata),
                    "candidate_path": None,
                    "canonical_path": f"artifacts/{request.artifact_type}.json",
                    "candidate_ref": None,
                    "node_id": "terminal",
                    "attempt_id": "terminal-1",
                    "required_for_replay": True,
                    "required_for_publication": True,
                }
            )
            existing_types.add(request.artifact_type)

        committed_at = utc_now()
        public_refs = tuple(
            _canonical_ref(intent.run_id, member["artifact_type"])
            for member in all_members
        )
        artifact_ref_map = {
            member["artifact_type"]: _canonical_ref(
                intent.run_id,
                member["artifact_type"],
            )
            for member in all_members
        }
        artifact_evidence = artifact_evidence_ref(artifact_ref_map)
        member_evidence = _member_evidence_projection(
            intent.run_id,
            all_members,
        )
        member_evidence_checksum = artifact_member_evidence_ref(member_evidence)
        outcome = HarnessSideEffectOutcome(
            outcome_id=f"research-artifact-published:{hash_text(intent.effect_id)}",
            effect_id=intent.effect_id,
            decision_ref=authorization.checksum,
            run_id=intent.run_id,
            kind=intent.kind,
            handler=authorization.handler,
            idempotency_key=intent.idempotency_key,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            atomic_group=intent.atomic_group,
            disposition=HarnessSideEffectDisposition.ACCEPTED,
            candidate_refs=tuple(
                member["candidate_ref"]
                for member in all_members
                if member.get("candidate_ref")
            ),
            public_refs=public_refs,
            result_ref=_checksum_ref(
                stable_json_dumps(
                    {
                        "artifact_refs": artifact_ref_map,
                        "authority": authorization.checksum,
                        "history_cutoff": cutoff,
                        "artifact_evidence_ref": artifact_evidence,
                        "artifact_member_evidence_ref": member_evidence_checksum,
                    }
                ).encode("utf-8")
            ),
            reason_code="published",
            committed_at=committed_at,
            metadata={
                "schema_version": RESEARCH_ARTIFACT_SCHEMA_VERSION,
                "artifact_refs": artifact_ref_map,
                "publication_authority_ref": authorization.checksum,
                "artifact_evidence_ref": artifact_evidence,
                "artifact_member_evidence_ref": member_evidence_checksum,
                "member_evidence": member_evidence,
                "prepared_outcome_refs": tuple(
                    sorted(
                        outcome.checksum
                        for outcome in prepared
                        if outcome.checksum is not None
                    )
                ),
                "history_cutoff": cutoff,
                "members": [
                    _public_member_projection(member) for member in all_members
                ],
            },
        )

        written_paths: list[Path] = []
        manifest_committed = False
        try:
            for index, member in enumerate(all_members, start=1):
                artifact_type = member["artifact_type"]
                if self.failure_injector is not None:
                    self.failure_injector(index, artifact_type, "commit")
                if member.get("request") is not None:
                    request = member["request"]
                    content = _request_bytes(request)
                else:
                    content = self._read_candidate_member(intent, member)
                self._verify_content(content, member)
                target = self.artifact_port.manager.run_dir(intent.run_id) / member[
                    "canonical_path"
                ]
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    existing_content = self.artifact_port.store.read(
                        StorageArtifactRef(
                            artifact_id=artifact_type,
                            run_id=intent.run_id,
                            artifact_type=artifact_type,
                            path=member["canonical_path"],
                            content_type=member["content_type"],
                            size_bytes=member["size_bytes"],
                            checksum=member["checksum"],
                        )
                    )
                    if existing_content != content:
                        raise ArtifactWriteConflictError(
                            f"immutable Research artifact conflicts: {artifact_type}"
                        )
                else:
                    self.artifact_port.manager.write_bytes(
                        intent.run_id,
                        member["canonical_path"],
                        content,
                    )
                    written_paths.append(target)

            manifest = self._build_final_manifest(
                intent,
                authorization,
                outcome,
                all_members,
                committed_at=committed_at,
            )
            cleanup_paths = self._validated_candidate_cleanup_paths(prepared)
            # This is the sole visibility write.  Every member has already
            # been checksum-verified, and the manager uses temp-write + flush
            # + atomic replace for manifest.json.
            self.artifact_port.write_terminal_manifest(manifest)
            manifest_committed = True
            # Cleanup is intentionally best-effort after the atomic visibility
            # commit.  A filesystem cleanup failure retains hidden bytes under
            # their bounded retention instead of turning a committed manifest
            # into a failed terminal handler result.
            self._cleanup_candidate_paths(cleanup_paths)
            return outcome
        except BaseException:
            if not manifest_committed:
                try:
                    persisted_manifest = self.artifact_port.read_terminal_manifest(
                        intent.run_id
                    )
                except Exception:
                    persisted_manifest = None
                if (
                    isinstance(persisted_manifest, GraphTerminalManifest)
                    and persisted_manifest.publication is not None
                    and persisted_manifest.publication.terminal_side_effect_outcome_ref
                    == outcome.checksum
                ):
                    manifest_committed = True
            if not manifest_committed:
                for path in reversed(written_paths):
                    try:
                        if path.is_file():
                            path.unlink()
                    except OSError:
                        pass
            raise

    def cleanup_candidates(
        self,
        run_id: str,
        *,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        """Quarantine expired prepared outcomes, then remove owned hidden bytes.

        The durable disposition transition always precedes deletion.  Prepared
        outcomes referenced by an accepted terminal publication are consumed,
        not failed, and may have only their leftover hidden bytes removed.
        """

        validated_run_id = validate_artifact_path_segment(run_id, field="run_id")
        current = now or utc_now()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now must be timezone-aware")

        outcomes: list[HarnessSideEffectOutcome] = []
        seen_effects: set[str] = set()
        for decision in self.side_effect_store.list_decisions(run_id=validated_run_id):
            if decision.effect_id in seen_effects:
                continue
            seen_effects.add(decision.effect_id)
            outcome = self.side_effect_store.get_outcome(
                effect_id=decision.effect_id,
                identity_scope_ref=decision.identity_scope_ref,
                subject_scope_ref=decision.subject_scope_ref,
                idempotency_key=decision.idempotency_key,
            )
            if outcome is not None and outcome.kind == RESEARCH_ARTIFACT_EFFECT_KIND:
                outcomes.append(outcome)

        consumed_prepared_refs: set[str] = set()
        for outcome in outcomes:
            if outcome.disposition is not HarnessSideEffectDisposition.ACCEPTED:
                continue
            refs = outcome.metadata.get("prepared_outcome_refs")
            if isinstance(refs, (list, tuple)):
                consumed_prepared_refs.update(
                    ref for ref in refs if isinstance(ref, str) and ref
                )
        try:
            manifest = self.artifact_port.read_terminal_manifest(validated_run_id)
            self.artifact_port._validated_v2_publication_claim(
                self.artifact_port._artifact_metadata_projection(validated_run_id),
                run_id=validated_run_id,
            )
            terminal_payload = (
                None
                if manifest.publication is None
                else manifest.publication.metadata.get("terminal_side_effect_outcome")
            )
            terminal_outcome = (
                HarnessSideEffectOutcome.from_dict(terminal_payload)
                if isinstance(terminal_payload, Mapping)
                else None
            )
        except (ArtifactNotFoundError, ArtifactStoreMetadataError, HarnessValidationError):
            terminal_outcome = None
        if (
            terminal_outcome is not None
            and terminal_outcome.disposition is HarnessSideEffectDisposition.ACCEPTED
        ):
            refs = terminal_outcome.metadata.get("prepared_outcome_refs")
            if isinstance(refs, (list, tuple)):
                consumed_prepared_refs.update(
                    ref for ref in refs if isinstance(ref, str) and ref
                )

        cleaned: list[str] = []
        for outcome in outcomes:
            if outcome.disposition is HarnessSideEffectDisposition.ACCEPTED:
                continue
            consumed = outcome.checksum in consumed_prepared_refs
            removable = consumed or outcome.disposition is HarnessSideEffectDisposition.QUARANTINE
            if (
                outcome.disposition is HarnessSideEffectDisposition.PREPARED
                and not consumed
                and outcome.retention_until is not None
                and outcome.retention_until <= current
            ):
                quarantined = self.side_effect_store.set_disposition(
                    effect_id=outcome.effect_id,
                    disposition=HarnessSideEffectDisposition.QUARANTINE,
                    identity_scope_ref=outcome.identity_scope_ref,
                    subject_scope_ref=outcome.subject_scope_ref,
                )
                if (
                    quarantined is None
                    or quarantined.disposition
                    is not HarnessSideEffectDisposition.QUARANTINE
                ):
                    raise HarnessValidationError(
                        "Research candidate cleanup requires durable quarantine",
                        code="research_candidate_quarantine_missing",
                    )
                outcome = quarantined
                removable = True
            if not removable:
                continue
            paths = self._validated_candidate_cleanup_paths((outcome,))
            self._cleanup_candidate_paths(paths)
            if all(not path.exists() for path in paths):
                cleaned.append(outcome.effect_id)
        return tuple(sorted(cleaned))

    def _prepared_outcomes(
        self,
        intent: HarnessSideEffectIntent,
    ) -> tuple[HarnessSideEffectOutcome, ...]:
        refs = intent.payload.get("prepared_outcome_refs", ())
        if not isinstance(refs, (list, tuple)):
            raise HarnessValidationError("terminal prepared_outcome_refs must be an array")
        wanted = {str(value) for value in refs if isinstance(value, str)}
        if not wanted:
            return ()
        outcomes: list[HarnessSideEffectOutcome] = []
        for decision in self.side_effect_store.list_decisions(run_id=intent.run_id):
            if decision.origin is not HarnessSideEffectOrigin.WORKER:
                continue
            if (
                decision.identity_scope_ref != intent.identity_scope_ref
                or decision.subject_scope_ref != intent.subject_scope_ref
            ):
                continue
            outcome = self.side_effect_store.get_outcome(
                effect_id=decision.effect_id,
                identity_scope_ref=decision.identity_scope_ref,
                subject_scope_ref=decision.subject_scope_ref,
                idempotency_key=decision.idempotency_key,
            )
            if outcome is not None and outcome.checksum in wanted:
                if outcome.disposition is not HarnessSideEffectDisposition.PREPARED:
                    raise HarnessValidationError(
                        "terminal publication requires prepared outcomes",
                        code="research_prepared_outcome_invalid",
                    )
                outcomes.append(outcome)
        if len(outcomes) != len(wanted):
            raise HarnessValidationError(
                "terminal publication prepared outcome refs are incomplete",
                code="research_prepared_outcome_missing",
            )
        return tuple(sorted(outcomes, key=lambda value: value.checksum or ""))

    def _existing_prepared_outcome(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome | None:
        existing = self.side_effect_store.get_outcome(
            effect_id=intent.effect_id,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            idempotency_key=intent.idempotency_key,
        )
        if existing is None:
            return None
        if (
            existing.decision_ref != authorization.checksum
            or existing.run_id != intent.run_id
            or existing.kind != intent.kind
            or existing.atomic_group != intent.atomic_group
            or existing.identity_scope_ref != intent.identity_scope_ref
            or existing.subject_scope_ref != intent.subject_scope_ref
        ):
            raise HarnessValidationError(
                "existing Research prepared outcome authority conflicts with intent",
                code="research_prepared_outcome_conflict",
            )
        if existing.disposition is not HarnessSideEffectDisposition.PREPARED:
            raise HarnessValidationError(
                "Research prepared effect already has a terminal disposition",
                code="research_prepared_outcome_terminal",
            )
        return existing

    def _verify_prepared_outcome(
        self,
        intent: HarnessSideEffectIntent,
        outcome: HarnessSideEffectOutcome,
    ) -> None:
        if outcome.disposition is not HarnessSideEffectDisposition.PREPARED:
            raise HarnessValidationError("Research prepared outcome disposition is invalid")
        members = _outcome_members(outcome)
        candidate_refs = tuple(
            member.get("candidate_ref")
            for member in members
            if isinstance(member.get("candidate_ref"), str)
        )
        if candidate_refs != outcome.candidate_refs:
            raise HarnessValidationError(
                "Research prepared outcome candidate refs are inconsistent",
                code="research_prepared_outcome_invalid",
            )
        if outcome.metadata.get("bundle_checksum") != _bundle_checksum(members):
            raise HarnessValidationError(
                "Research prepared outcome bundle checksum is invalid",
                code="research_prepared_outcome_invalid",
            )
        for member in members:
            path = member.get("candidate_path")
            if not isinstance(path, str) or not path:
                raise HarnessValidationError(
                    "Research prepared outcome candidate path is missing",
                    code="research_prepared_outcome_invalid",
                )
            content = self._read_candidate_member(intent, member)
            self._verify_content(content, member)

    def _resolved_bundle_members(
        self,
        intent: HarnessSideEffectIntent,
    ) -> list[dict[str, Any]]:
        raw_members = intent.payload.get("members")
        if raw_members is not None:
            return _bundle_members(intent)
        if self.candidate_payload_factory is None:
            raise HarnessValidationError(
                "Research artifact candidate payload factory is unavailable"
            )
        requests = self.candidate_payload_factory(intent)
        if not requests or not all(
            isinstance(request, ArtifactWriteRequest) for request in requests
        ):
            raise HarnessValidationError("Research artifact candidate bundle is invalid")
        members = [request.to_dict() for request in requests]
        expected_ref = checksum_for(
            {
                "schema_version": RESEARCH_ARTIFACT_SCHEMA_VERSION,
                "run_id": intent.run_id,
                "paper_id": intent.payload.get("paper_id"),
                "members": members,
            }
        )
        if intent.payload.get("bundle_ref") != expected_ref:
            raise HarnessValidationError(
                "Research artifact bundle checksum is invalid",
                code="research_artifact_bundle_checksum_mismatch",
            )
        expected_members = [
            {
                "artifact_type": request.artifact_type,
                "request_ref": checksum_for(request.to_dict()),
            }
            for request in requests
        ]
        if list(intent.payload.get("member_refs") or ()) != expected_members:
            raise HarnessValidationError(
                "Research artifact member refs are invalid",
                code="research_artifact_member_ref_mismatch",
            )
        return _validated_bundle_members(members)

    def _existing_terminal_outcome(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome | None:
        try:
            terminal_manifest = self.artifact_port.read_terminal_manifest(intent.run_id)
        except ArtifactNotFoundError:
            return None
        publication = terminal_manifest.publication
        if publication is None:
            return None
        payload = publication.metadata.get("terminal_side_effect_outcome")
        if not isinstance(payload, Mapping):
            return None
        try:
            outcome = HarnessSideEffectOutcome.from_dict(payload)
        except Exception:
            return None
        if (
            outcome.effect_id != intent.effect_id
            or outcome.decision_ref != authorization.checksum
            or outcome.identity_scope_ref != intent.identity_scope_ref
            or outcome.subject_scope_ref != intent.subject_scope_ref
            or outcome.disposition is not HarnessSideEffectDisposition.ACCEPTED
        ):
            raise HarnessValidationError(
                "existing Research publication authority conflicts with terminal intent",
                code="research_publication_authority_conflict",
            )
        try:
            claim = self.artifact_port._validated_v2_publication_claim(
                self.artifact_port._artifact_metadata_projection(intent.run_id),
                run_id=intent.run_id,
            )
        except ArtifactStoreMetadataError as exc:
            raise HarnessValidationError(
                "existing Research publication evidence is invalid",
                code="research_publication_evidence_invalid",
            ) from exc
        if (
            claim.identity_scope_ref != intent.identity_scope_ref
            or claim.subject_scope_ref != intent.subject_scope_ref
            or claim.publication_authority_ref != authorization.checksum
            or claim.terminal_side_effect_outcome_ref != outcome.checksum
        ):
            raise HarnessValidationError(
                "existing Research publication evidence conflicts with terminal intent",
                code="research_publication_authority_conflict",
            )
        return outcome

    def _build_final_manifest(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
        outcome: HarnessSideEffectOutcome,
        members: list[dict[str, Any]],
        *,
        committed_at: datetime,
    ) -> GraphTerminalManifest:
        context_value = intent.payload.get("graph_terminal_manifest_context")
        if not isinstance(context_value, Mapping):
            raise HarnessValidationError(
                "Research terminal publication requires pinned Graph manifest context",
                code="research_graph_manifest_context_missing",
            )
        try:
            context = GraphTerminalManifestContext.from_dict(context_value)
        except (TypeError, ValueError) as exc:
            raise HarnessValidationError(
                "Research terminal publication Graph manifest context is invalid",
                code="research_graph_manifest_context_invalid",
            ) from exc

        staged = self.artifact_port.list_staged_artifacts(intent.run_id)
        invalid_staged = tuple(
            artifact.artifact_key
            for artifact in staged
            if not is_verified_internal_staged_artifact(artifact)
        )
        if invalid_staged:
            raise ArtifactWriteConflictError(
                "Research terminal publication found non-internal staged artifacts"
            )
        artifact_ref_map = {
            member["artifact_type"]: _canonical_ref(
                intent.run_id,
                member["artifact_type"],
            )
            for member in members
        }
        artifact_evidence = artifact_evidence_ref(artifact_ref_map)
        member_evidence = _member_evidence_projection(intent.run_id, members)
        member_evidence_checksum = artifact_member_evidence_ref(member_evidence)
        outcome_metadata = outcome.metadata
        if (
            outcome_metadata.get("artifact_refs") != artifact_ref_map
            or outcome_metadata.get("artifact_evidence_ref") != artifact_evidence
            or outcome_metadata.get("artifact_member_evidence_ref")
            != member_evidence_checksum
        ):
            raise HarnessValidationError(
                "Research terminal outcome evidence does not match publication members",
                code="research_artifact_evidence_mismatch",
            )
        published = tuple(
            _graph_terminal_artifact(
                intent,
                authorization,
                member,
                artifact_evidence=artifact_evidence,
            )
            for member in members
        )
        all_artifacts = (*staged, *published)
        artifact_keys = tuple(artifact.artifact_key for artifact in all_artifacts)
        if len(artifact_keys) != len(set(artifact_keys)):
            raise ArtifactWriteConflictError(
                "Research terminal publication artifact identity conflicts with staging"
            )
        gate_evidence_refs = tuple(
            value
            for value in (
                *authorization.gate_result_refs,
                authorization.aggregate_verdict_ref,
            )
            if isinstance(value, str)
        )
        if not gate_evidence_refs:
            raise HarnessValidationError(
                "Research terminal publication requires deterministic gate evidence",
                code="research_graph_gate_evidence_missing",
            )
        if intent.state_checksum is None or outcome.checksum is None:
            raise HarnessValidationError(
                "Research terminal publication identity is incomplete",
                code="research_graph_terminal_identity_missing",
            )
        publication = GraphTerminalPublicationEvidence(
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            publication_authority_ref=authorization.checksum,
            terminal_side_effect_outcome_ref=outcome.checksum,
            artifact_evidence_ref=artifact_evidence,
            artifact_member_evidence_ref=member_evidence_checksum,
            committed_at=committed_at,
            metadata={
                "handler_ref": str(authorization.handler),
                "history_cutoff": _history_cutoff(intent),
                "artifact_member_evidence": member_evidence,
                "terminal_side_effect_outcome": outcome.to_dict(),
            },
        )
        return GraphTerminalManifest(
            tenant_id=context.tenant_id,
            run_id=intent.run_id,
            graph_id=context.graph_id,
            graph_version=context.graph_version,
            graph_schema_version=context.graph_schema_version,
            compiler_version=context.compiler_version,
            normalized_graph_checksum=context.normalized_graph_checksum,
            status="succeeded",
            started_at=context.started_at,
            completed_at=committed_at,
            terminal_state_ref=intent.state_checksum,
            checkpoint_ref=(
                f"graph-state://{intent.run_id}/"
                f"{intent.state_checksum.removeprefix('sha256:')}"
            ),
            terminal_node_ids=context.terminal_node_ids,
            gate_evidence_refs=gate_evidence_refs,
            artifacts=all_artifacts,
            publication=publication,
        )


    def _read_candidate_member(
        self,
        intent: HarnessSideEffectIntent,
        member: Mapping[str, Any],
    ) -> bytes:
        path = member.get("candidate_path")
        if not isinstance(path, str) or not path:
            raise HarnessValidationError("prepared artifact candidate path is missing")
        return self.artifact_port.store.read(
            StorageArtifactRef(
                artifact_id=str(member["artifact_type"]),
                run_id=intent.run_id,
                artifact_type=str(member["artifact_type"]),
                path=path,
                content_type=str(member["content_type"]),
                size_bytes=int(member["size_bytes"]),
                checksum=str(member["checksum"]),
            )
        )

    def _verify_bytes(
        self,
        run_id: str,
        path: str,
        artifact_type: str,
        checksum: str,
        size_bytes: int,
    ) -> None:
        self.artifact_port.store.read(
            StorageArtifactRef(
                artifact_id=artifact_type,
                run_id=run_id,
                artifact_type=artifact_type,
                path=path,
                content_type="application/json",
                size_bytes=size_bytes,
                checksum=checksum,
            )
        )

    @staticmethod
    def _verify_content(content: bytes, member: Mapping[str, Any]) -> None:
        if len(content) != int(member["size_bytes"]):
            raise ArtifactStoreMetadataError(
                f"Research artifact candidate size mismatch: {member['artifact_type']}"
            )
        if compute_checksum(content) != member["checksum"]:
            raise ArtifactStoreMetadataError(
                f"Research artifact candidate checksum mismatch: {member['artifact_type']}"
            )

    def _candidate_dir(self, intent: HarnessSideEffectIntent) -> Path:
        run_dir = self.artifact_port.manager.run_dir(intent.run_id)
        return run_dir / _CANDIDATE_ROOT / _effect_path_token(intent.effect_id)

    def _candidate_relative_path(self, intent: HarnessSideEffectIntent, artifact_type: str) -> str:
        validate_artifact_path_segment(artifact_type, field="artifact_type")
        return f"{_CANDIDATE_ROOT}/{_effect_path_token(intent.effect_id)}/artifacts/{artifact_type}.json"

    def _remove_owned_candidate(self, run_id: str, candidate_dir: Path) -> None:
        run_dir = self.artifact_port.manager.run_dir(run_id)
        try:
            candidate_dir.resolve(strict=False).relative_to(run_dir.resolve(strict=False))
        except ValueError as exc:
            raise HarnessValidationError("candidate cleanup escaped the Research run root") from exc
        if candidate_dir.exists():
            shutil.rmtree(candidate_dir)

    def _cleanup_prepared_candidates(
        self,
        outcomes: tuple[HarnessSideEffectOutcome, ...],
    ) -> None:
        self._cleanup_candidate_paths(self._validated_candidate_cleanup_paths(outcomes))

    def _validated_candidate_cleanup_paths(
        self,
        outcomes: tuple[HarnessSideEffectOutcome, ...],
    ) -> tuple[Path, ...]:
        paths: list[Path] = []
        for outcome in outcomes:
            root = outcome.metadata.get("candidate_root")
            if not isinstance(root, str) or not root:
                continue
            path = self.artifact_port.manager.run_dir(outcome.run_id) / root
            run_dir = self.artifact_port.manager.run_dir(outcome.run_id)
            try:
                path.resolve(strict=False).relative_to(run_dir.resolve(strict=False))
            except ValueError as exc:
                raise HarnessValidationError(
                    "candidate cleanup escaped the Research run root"
                ) from exc
            paths.append(path)
        return tuple(paths)

    @staticmethod
    def _cleanup_candidate_paths(paths: tuple[Path, ...]) -> None:
        for path in paths:
            try:
                if path.exists():
                    shutil.rmtree(path)
            except OSError:
                # Hidden candidates are retained for bounded quarantine/expiry
                # cleanup when the post-commit filesystem is temporarily busy.
                continue


def _assert_worker_authority(
    intent: HarnessSideEffectIntent,
    authorization: HarnessSideEffectDecision,
) -> None:
    if intent.origin is not HarnessSideEffectOrigin.WORKER:
        raise HarnessValidationError("Research preparation requires a worker-origin intent")
    if authorization.disposition is not HarnessSideEffectDisposition.PREPARED:
        raise HarnessValidationError("Research preparation requires prepared authorization")
    _assert_common_authority(intent, authorization)


def _assert_terminal_authority(
    intent: HarnessSideEffectIntent,
    authorization: HarnessSideEffectDecision,
) -> None:
    if intent.origin is not HarnessSideEffectOrigin.CONTROLLER_TERMINAL:
        raise HarnessValidationError("Research publication requires a controller-terminal intent")
    if authorization.disposition is not HarnessSideEffectDisposition.ACCEPTED:
        raise HarnessValidationError("Research publication requires accepted authorization")
    _assert_common_authority(intent, authorization)


def _assert_common_authority(
    intent: HarnessSideEffectIntent,
    authorization: HarnessSideEffectDecision,
) -> None:
    if (
        authorization.effect_id != intent.effect_id
        or authorization.intent_ref != intent.checksum
        or authorization.run_id != intent.run_id
        or authorization.kind != intent.kind
        or authorization.identity_scope_ref != intent.identity_scope_ref
        or authorization.subject_scope_ref != intent.subject_scope_ref
        or authorization.atomic_group != intent.atomic_group
        or authorization.idempotency_key != intent.idempotency_key
    ):
        raise HarnessValidationError("Research side-effect authority does not match intent")


def _bundle_members(intent: HarnessSideEffectIntent) -> list[dict[str, Any]]:
    if intent.kind != RESEARCH_ARTIFACT_EFFECT_KIND:
        raise HarnessValidationError("Research artifact intent kind is invalid")
    payload = intent.payload
    if payload.get("schema_version") != RESEARCH_ARTIFACT_SCHEMA_VERSION:
        raise HarnessValidationError("Research artifact intent schema is invalid")
    members = payload.get("members")
    if not isinstance(members, (list, tuple)) or not members:
        raise HarnessValidationError("Research artifact intent requires members")
    return _validated_bundle_members(members)


def _validated_bundle_members(members: Any) -> list[dict[str, Any]]:
    if not isinstance(members, (list, tuple)) or not members:
        raise HarnessValidationError("Research artifact intent requires members")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in members:
        if not isinstance(raw, Mapping):
            raise HarnessValidationError("Research artifact member must be an object")
        member = dict(raw)
        artifact_type = member.get("artifact_type")
        if not isinstance(artifact_type, str) or not artifact_type.strip():
            raise HarnessValidationError("Research artifact member type is required")
        validate_artifact_path_segment(artifact_type, field="artifact_type")
        if artifact_type in seen:
            raise HarnessValidationError("Research artifact member types must be unique")
        seen.add(artifact_type)
        if not isinstance(member.get("payload"), Mapping):
            raise HarnessValidationError("Research artifact member payload is required")
        normalized.append(member)
    return normalized


def _member_request(member: Mapping[str, Any]) -> ArtifactWriteRequest:
    return ArtifactWriteRequest(
        artifact_type=str(member["artifact_type"]),
        payload=dict(member["payload"]),
        media_type=str(member.get("media_type") or "application/json"),
        metadata=dict(member.get("metadata") or {}),
    )


def _request_bytes(request: ArtifactWriteRequest) -> bytes:
    return stable_json_dumps(request.to_dict()).encode("utf-8")


def _candidate_ref(run_id: str, effect_id: str, artifact_type: str) -> str:
    return f"artifact-candidate://{run_id}/{_effect_path_token(effect_id)}/{artifact_type}"


def _canonical_ref(run_id: str, artifact_type: str) -> str:
    return f"artifact://{run_id}/{artifact_type}"


def _effect_path_token(effect_id: str) -> str:
    # Keep Windows temp-root tests below the legacy MAX_PATH boundary while
    # retaining 48 bits of collision resistance inside one run directory.
    return hash_text(effect_id)[:12]


def _bundle_checksum(records: list[Mapping[str, Any]]) -> str:
    return _checksum_ref(
        stable_json_dumps(
            [
                {
                    key: value
                    for key, value in record.items()
                    if key not in {"candidate_path", "candidate_ref"}
                }
                for record in records
            ]
        ).encode("utf-8")
    )


def _checksum_ref(content: bytes) -> str:
    return f"sha256:{compute_checksum(content)}"


def _outcome_members(outcome: HarnessSideEffectOutcome) -> list[dict[str, Any]]:
    raw = outcome.metadata.get("members")
    if not isinstance(raw, (list, tuple)):
        raise HarnessValidationError("prepared Research outcome has no member projection")
    members: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise HarnessValidationError("prepared Research outcome member is invalid")
        members.append(dict(item))
    return members


def _public_member_projection(member: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_type": member["artifact_type"],
        "checksum": member["checksum"],
        "size_bytes": member["size_bytes"],
        "content_type": member["content_type"],
        "canonical_path": member["canonical_path"],
        "candidate_ref": member.get("candidate_ref"),
    }


def _graph_terminal_artifact(
    intent: HarnessSideEffectIntent,
    authorization: HarnessSideEffectDecision,
    member: Mapping[str, Any],
    *,
    artifact_evidence: str,
) -> GraphTerminalArtifact:
    artifact_type = str(member["artifact_type"])
    checksum = str(member["checksum"])
    if not checksum.startswith("sha256:"):
        checksum = f"sha256:{checksum}"
    return GraphTerminalArtifact(
        artifact_key=artifact_type,
        artifact_id=artifact_type,
        ref=_canonical_ref(intent.run_id, artifact_type),
        relative_path=str(member["canonical_path"]),
        content_checksum=checksum,
        byte_size=int(member["size_bytes"]),
        media_type=str(member["content_type"]),
        node_id=str(member["node_id"]),
        attempt_id=str(member["attempt_id"]),
        required_for_replay=bool(member["required_for_replay"]),
        required_for_publication=bool(member["required_for_publication"]),
        metadata={
            **dict(member.get("metadata") or {}),
            "identity_scope_ref": intent.identity_scope_ref,
            "subject_scope_ref": intent.subject_scope_ref,
            "publication_authority_ref": authorization.checksum,
            "artifact_evidence_ref": artifact_evidence,
        },
    )


def _member_evidence_projection(
    run_id: str,
    members: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        (
            {
                "artifact_type": str(member["artifact_type"]),
                "artifact_ref": _canonical_ref(
                    run_id,
                    str(member["artifact_type"]),
                ),
                "path": str(member["canonical_path"]),
                "checksum": f"sha256:{member['checksum']}",
                "size_bytes": int(member["size_bytes"]),
                "content_type": str(member["content_type"]),
            }
            for member in members
        ),
        key=lambda item: item["artifact_type"],
    )


def _coerce_terminal_payloads(
    value: Mapping[str, ArtifactWriteRequest] | tuple[ArtifactWriteRequest, ...],
) -> tuple[ArtifactWriteRequest, ...]:
    if isinstance(value, Mapping):
        values = tuple(value.values())
    elif isinstance(value, tuple):
        values = value
    else:
        raise HarnessValidationError("terminal artifact payload factory returned an invalid value")
    if not all(isinstance(item, ArtifactWriteRequest) for item in values):
        raise HarnessValidationError("terminal artifact payload factory returned invalid members")
    return values


def _history_cutoff(intent: HarnessSideEffectIntent) -> str | None:
    value = intent.payload.get("history_cutoff")
    return value if isinstance(value, str) and value.strip() else None


__all__ = [
    "RESEARCH_ARTIFACT_EFFECT_KIND",
    "RESEARCH_ARTIFACT_HANDLER_ID",
    "RESEARCH_ARTIFACT_HANDLER_REF",
    "RESEARCH_ARTIFACT_HANDLER_VERSION",
    "RESEARCH_ARTIFACT_MANIFEST_VERSION",
    "RESEARCH_ARTIFACT_SCHEMA_VERSION",
    "ResearchArtifactBundleHandler",
    "CandidateArtifactPayloadFactory",
    "TerminalArtifactPayloadFactory",
]
