from __future__ import annotations

import os
import stat
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from framework.agent.artifacts.paths import (
    ArtifactPathError,
    resolve_artifact_descendant,
    validate_artifact_path_segment,
)
from framework.agent.artifacts.stores.errors import ArtifactStoreMetadataError
from framework.agent.artifacts.stores.fs_safety import (
    is_link_or_reparse_point,
    reject_link_chain,
    verified_atomic_create,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.subagents.observability import (
    DEFAULT_SUBAGENT_TRANSCRIPT_OBSERVATION_SINK,
    SUBAGENT_TRANSCRIPT_BYTES,
    SUBAGENT_TRANSCRIPT_COMMIT_FAILED,
    SUBAGENT_TRANSCRIPT_COMMIT_LATENCY_MS,
    SUBAGENT_TRANSCRIPT_COMMIT_SUCCEEDED,
    SUBAGENT_TRANSCRIPT_CONFLICT,
    SUBAGENT_TRANSCRIPT_CORRUPT,
    SUBAGENT_TRANSCRIPT_VERIFY_FAILED,
    SubAgentTranscriptObservation,
    SubAgentTranscriptObservationSink,
    record_subagent_transcript_observation,
)
from framework.harness.subagents.transcript import (
    DEFAULT_MAX_BUNDLE_BYTES,
    DEFAULT_MAX_OUTPUT_BYTES,
    DEFAULT_MAX_TRANSCRIPT_BYTES,
    MAX_PARENT_QUERY,
    SUBAGENT_BUNDLE_SCHEMA,
    SubAgentAttemptIdentity,
    SubAgentContextEvidence,
    SubAgentOutputDocument,
    SubAgentTranscript,
    SubAgentTranscriptConflictError,
    SubAgentTranscriptCorruptError,
    SubAgentTranscriptReceipt,
    SubAgentTranscriptStoreError,
    _validate_bundle_identity,
)
from framework.shared.json import json_loads, stable_json_dumps
from framework.shared.time import utc_now


class FilesystemSubAgentTranscriptStore:
    """Run-scoped immutable durable store for subagent attempt evidence."""

    is_durable = True

    def __init__(
        self,
        root: str | Path,
        *,
        max_transcript_bytes: int = DEFAULT_MAX_TRANSCRIPT_BYTES,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        max_bundle_bytes: int = DEFAULT_MAX_BUNDLE_BYTES,
        clock: Callable[[], Any] = utc_now,
        monotonic: Callable[[], float] = time.perf_counter,
        observation_sink: SubAgentTranscriptObservationSink | None = (
            DEFAULT_SUBAGENT_TRANSCRIPT_OBSERVATION_SINK
        ),
    ) -> None:
        self.root = Path(root).expanduser().resolve(strict=False)
        self.max_transcript_bytes = _positive_limit(max_transcript_bytes, "max_transcript_bytes")
        self.max_output_bytes = _positive_limit(max_output_bytes, "max_output_bytes")
        self.max_bundle_bytes = _positive_limit(max_bundle_bytes, "max_bundle_bytes")
        if self.max_bundle_bytes < self.max_transcript_bytes or self.max_bundle_bytes < self.max_output_bytes:
            raise ValueError("max_bundle_bytes must cover each document limit")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not callable(monotonic):
            raise TypeError("monotonic must be callable")
        if observation_sink is not None and not isinstance(
            observation_sink,
            SubAgentTranscriptObservationSink,
        ):
            raise TypeError(
                "observation_sink must implement SubAgentTranscriptObservationSink"
            )
        self._clock = clock
        self._monotonic = monotonic
        self._observation_sink = observation_sink
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            root_info = os.lstat(self.root)
        except OSError as exc:
            raise _store_error(
                "subagent_transcript_store_unavailable",
                "create subagent transcript root failed",
                root=str(self.root),
            ) from exc
        if is_link_or_reparse_point(root_info) or not stat.S_ISDIR(root_info.st_mode):
            raise _store_error(
                "subagent_transcript_store_unavailable",
                "subagent transcript root must be a real directory",
                root=str(self.root),
            )

    def write(
        self,
        context: SubAgentContextEvidence,
        output: SubAgentOutputDocument,
        transcript: SubAgentTranscript,
    ) -> SubAgentTranscriptReceipt:
        started_at = self._monotonic()
        _validate_bundle_identity(context, output, transcript)
        identity = transcript.identity
        receipt = SubAgentTranscriptReceipt(
            transcript_ref=transcript.ref,
            transcript_checksum=transcript.transcript_checksum,
            transcript_id=transcript.transcript_id,
            invocation_id=identity.invocation_id,
            parent_run_id=identity.parent_run_id,
            child_run_id=identity.child_run_id,
            task_instance_id=identity.task_instance_id,
            attempt=identity.attempt,
            context_ref=f"subagent-context://v1/{identity.parent_run_id}/{identity.transcript_id}",
            context_checksum=context.context_checksum,
            output_ref=output.ref,
            output_checksum=output.output_checksum,
            storage_revision=f"bundle:{identity.transcript_id}:v1",
            committed_at=self._clock(),
        )
        payload = {
            "schema_version": SUBAGENT_BUNDLE_SCHEMA,
            "context": context.to_dict(),
            "output": output.to_dict(),
            "transcript": transcript.to_dict(),
            "receipt": receipt.to_dict(),
        }
        content = (stable_json_dumps(payload) + "\n").encode("utf-8")
        try:
            self._enforce_sizes(context, output, transcript, content)
            path = self._bundle_path(identity.parent_run_id, identity.transcript_id)
            try:
                created = verified_atomic_create(
                    path,
                    content,
                    root=self.root,
                    identity=f"{identity.parent_run_id}/{identity.transcript_id}",
                )
            except (ArtifactStoreMetadataError, OSError) as exc:
                raise _store_error(
                    "subagent_transcript_store_unavailable",
                    "commit subagent transcript bundle failed",
                    transcript_id=identity.transcript_id,
                ) from exc
            committed = receipt
            if not created:
                existing = self._read_bundle(path)
                committed = existing[3]
                if (
                    existing[0] != context
                    or existing[1] != output
                    or existing[2] != transcript
                ):
                    raise SubAgentTranscriptConflictError(
                        "subagent transcript identity already has different content",
                        code="subagent_transcript_conflict",
                        details={"transcript_id": identity.transcript_id},
                    )
            committed = self.verify(committed)
        except Exception as exc:
            reason_code = _reason_code(exc)
            if isinstance(exc, SubAgentTranscriptConflictError):
                self._observe(
                    SUBAGENT_TRANSCRIPT_CONFLICT,
                    identity,
                    reason_code=reason_code,
                )
            self._observe(
                SUBAGENT_TRANSCRIPT_COMMIT_FAILED,
                identity,
                reason_code=reason_code,
            )
            raise
        self._observe(
            SUBAGENT_TRANSCRIPT_COMMIT_SUCCEEDED,
            identity,
            receipt=committed,
            value=1,
        )
        self._observe(
            SUBAGENT_TRANSCRIPT_BYTES,
            identity,
            receipt=committed,
            value=len(content),
        )
        self._observe(
            SUBAGENT_TRANSCRIPT_COMMIT_LATENCY_MS,
            identity,
            receipt=committed,
            value=max(0.0, (self._monotonic() - started_at) * 1000),
        )
        return committed

    def read(self, transcript_ref: str) -> SubAgentTranscript:
        parent, transcript_id = _parse_ref(transcript_ref, "subagent-transcript")
        transcript = self._read_bundle(self._bundle_path(parent, transcript_id))[2]
        if transcript.ref != transcript_ref:
            raise _corrupt("subagent transcript ref does not match stored identity")
        return transcript

    def read_context(self, context_ref: str) -> SubAgentContextEvidence:
        parent, transcript_id = _parse_ref(context_ref, "subagent-context")
        context = self._read_bundle(self._bundle_path(parent, transcript_id))[0]
        expected = f"subagent-context://v1/{parent}/{transcript_id}"
        if context_ref != expected:
            raise _corrupt("subagent context ref does not match stored identity")
        return context

    def read_output(self, output_ref: str) -> SubAgentOutputDocument:
        parent, transcript_id = _parse_ref(output_ref, "subagent-output")
        output = self._read_bundle(self._bundle_path(parent, transcript_id))[1]
        if output.ref != output_ref:
            raise _corrupt("subagent output ref does not match stored identity")
        return output

    def verify(self, receipt: SubAgentTranscriptReceipt) -> SubAgentTranscriptReceipt:
        if not isinstance(receipt, SubAgentTranscriptReceipt):
            raise TypeError("receipt must be SubAgentTranscriptReceipt")
        try:
            parent, transcript_id = _parse_ref(
                receipt.transcript_ref,
                "subagent-transcript",
            )
            if parent != receipt.parent_run_id or transcript_id != receipt.transcript_id:
                raise _corrupt(
                    "subagent receipt ref identity mismatch",
                    code="subagent_transcript_identity_mismatch",
                )
            context, output, transcript, stored = self._read_bundle(
                self._bundle_path(parent, transcript_id)
            )
            if stored != receipt:
                raise _corrupt("subagent receipt does not match committed bundle")
            _validate_bundle_identity(context, output, transcript)
            identity = transcript.identity
            if (
                context.identity != identity
                or output.identity != identity
                or receipt.transcript_id != identity.transcript_id
                or receipt.invocation_id != identity.invocation_id
                or receipt.parent_run_id != identity.parent_run_id
                or receipt.child_run_id != identity.child_run_id
                or receipt.task_instance_id != identity.task_instance_id
                or receipt.attempt != identity.attempt
                or context.context_checksum != receipt.context_checksum
                or output.output_checksum != receipt.output_checksum
                or transcript.transcript_checksum != receipt.transcript_checksum
                or output.ref != receipt.output_ref
                or transcript.ref != receipt.transcript_ref
                or receipt.context_ref
                != f"subagent-context://v1/{identity.parent_run_id}/{identity.transcript_id}"
                or transcript.output_ref != output.ref
                or transcript.output_checksum != output.output_checksum
            ):
                raise _corrupt("subagent receipt checksum or ref mismatch")
            return receipt
        except Exception as exc:
            reason_code = _reason_code(exc)
            self._observe_receipt_failure(
                SUBAGENT_TRANSCRIPT_VERIFY_FAILED,
                receipt,
                reason_code=reason_code,
            )
            if _is_corrupt_reason(reason_code):
                self._observe_receipt_failure(
                    SUBAGENT_TRANSCRIPT_CORRUPT,
                    receipt,
                    reason_code=reason_code,
                )
            raise

    def refs_for_parent(
        self,
        parent_run_id: str,
        *,
        limit: int = MAX_PARENT_QUERY,
    ) -> tuple[str, ...]:
        parent = _path_segment(parent_run_id, "parent_run_id")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or limit > MAX_PARENT_QUERY:
            raise HarnessValidationError(
                "transcript parent query limit is invalid",
                code="subagent_transcript_query_limit_invalid",
            )
        directory = self._parent_dir(parent)
        if not directory.exists():
            return ()
        try:
            reject_link_chain(
                directory,
                root=self.root,
                identity=parent,
                role="subagent transcript parent query",
            )
            refs: list[str] = []
            for candidate in sorted(directory.glob("sat_*.json"), key=lambda item: item.name):
                if len(refs) >= limit:
                    break
                transcript_id = candidate.stem
                transcript = self._read_bundle(candidate)[2]
                if transcript.identity.parent_run_id != parent or transcript.transcript_id != transcript_id:
                    raise _corrupt("subagent parent query found mismatched bundle")
                refs.append(transcript.ref)
            return tuple(refs)
        except SubAgentTranscriptStoreError:
            raise
        except (ArtifactStoreMetadataError, OSError) as exc:
            raise _store_error(
                "subagent_transcript_store_unavailable",
                "query subagent transcript parent failed",
                parent_run_id=parent,
            ) from exc

    def find_by_identity(
        self,
        identity: SubAgentAttemptIdentity,
    ) -> SubAgentTranscriptReceipt | None:
        if not isinstance(identity, SubAgentAttemptIdentity):
            raise TypeError("identity must be SubAgentAttemptIdentity")
        path = self._bundle_path(identity.parent_run_id, identity.transcript_id)
        try:
            receipt = self._read_bundle(path)[3]
        except SubAgentTranscriptStoreError as exc:
            if exc.code == "subagent_transcript_not_found":
                return None
            raise
        transcript = self.read(receipt.transcript_ref)
        if transcript.identity != identity:
            raise _corrupt("subagent identity lookup resolved a different attempt")
        return self.verify(receipt)

    def _read_bundle(
        self,
        path: Path,
    ) -> tuple[
        SubAgentContextEvidence,
        SubAgentOutputDocument,
        SubAgentTranscript,
        SubAgentTranscriptReceipt,
    ]:
        try:
            reject_link_chain(
                path,
                root=self.root,
                identity=path.name,
                role="subagent transcript read",
            )
            before = os.lstat(path)
            if is_link_or_reparse_point(before) or not stat.S_ISREG(before.st_mode):
                raise _corrupt("subagent transcript bundle is not a regular file")
            if before.st_size > self.max_bundle_bytes:
                raise _store_error(
                    "subagent_transcript_size_exceeded",
                    "subagent transcript bundle exceeds size limit",
                    size_bytes=before.st_size,
                )
            with path.open("rb") as handle:
                opened = os.fstat(handle.fileno())
                if not os.path.samestat(before, opened):
                    raise _corrupt("subagent transcript bundle changed while opening")
                content = handle.read(self.max_bundle_bytes + 1)
            if len(content) > self.max_bundle_bytes:
                raise _store_error(
                    "subagent_transcript_size_exceeded",
                    "subagent transcript bundle exceeds size limit",
                )
            reject_link_chain(
                path,
                root=self.root,
                identity=path.name,
                role="subagent transcript read",
            )
            payload = json_loads(content.decode("utf-8"))
            if not isinstance(payload, Mapping) or set(payload) != {
                "schema_version", "context", "output", "transcript", "receipt"
            }:
                raise _corrupt("subagent transcript bundle fields are invalid")
            if payload["schema_version"] != SUBAGENT_BUNDLE_SCHEMA:
                raise _corrupt("subagent transcript bundle schema is unsupported", code="subagent_transcript_schema_unsupported")
            context = SubAgentContextEvidence.from_dict(_object(payload["context"], "context"))
            output = SubAgentOutputDocument.from_dict(_object(payload["output"], "output"))
            transcript = SubAgentTranscript.from_dict(_object(payload["transcript"], "transcript"))
            receipt = SubAgentTranscriptReceipt.from_dict(_object(payload["receipt"], "receipt"))
            self._enforce_sizes(context, output, transcript, content)
            return context, output, transcript, receipt
        except SubAgentTranscriptStoreError:
            raise
        except FileNotFoundError as exc:
            raise _store_error(
                "subagent_transcript_not_found",
                "subagent transcript bundle was not found",
                path=str(path),
            ) from exc
        except (ArtifactStoreMetadataError, HarnessValidationError, UnicodeError, ValueError, OSError) as exc:
            raise _corrupt("subagent transcript bundle is corrupt") from exc

    def _enforce_sizes(
        self,
        context: SubAgentContextEvidence,
        output: SubAgentOutputDocument,
        transcript: SubAgentTranscript,
        bundle: bytes,
    ) -> None:
        sizes = {
            "context": len(stable_json_dumps(context.to_dict()).encode("utf-8")),
            "output": len(stable_json_dumps(output.to_dict()).encode("utf-8")),
            "transcript": len(stable_json_dumps(transcript.to_dict()).encode("utf-8")),
            "bundle": len(bundle),
        }
        limits = {
            "context": self.max_transcript_bytes,
            "output": self.max_output_bytes,
            "transcript": self.max_transcript_bytes,
            "bundle": self.max_bundle_bytes,
        }
        exceeded = {name: {"size": size, "limit": limits[name]} for name, size in sizes.items() if size > limits[name]}
        if exceeded:
            raise _store_error(
                "subagent_transcript_size_exceeded",
                "subagent attempt evidence exceeds configured size",
                exceeded=exceeded,
            )

    def _parent_dir(self, parent_run_id: str) -> Path:
        try:
            return resolve_artifact_descendant(
                self.root,
                parent_run_id,
                "_harness/subagents",
                field="subagent transcript parent path",
            )
        except ArtifactPathError as exc:
            raise _store_error(
                "subagent_transcript_identity_mismatch",
                "subagent transcript parent path is invalid",
            ) from exc

    def _bundle_path(self, parent_run_id: str, transcript_id: str) -> Path:
        parent = _path_segment(parent_run_id, "parent_run_id")
        transcript = _path_segment(transcript_id, "transcript_id")
        if not transcript.startswith("sat_") or len(transcript) != 68:
            raise _store_error(
                "subagent_transcript_identity_mismatch",
                "subagent transcript id is invalid",
            )
        return resolve_artifact_descendant(
            self._parent_dir(parent),
            f"{transcript}.json",
            field="subagent transcript bundle path",
        )

    def _observe(
        self,
        name: str,
        identity: SubAgentAttemptIdentity,
        *,
        receipt: SubAgentTranscriptReceipt | None = None,
        reason_code: str | None = None,
        value: float | None = None,
    ) -> None:
        record_subagent_transcript_observation(
            self._observation_sink,
            SubAgentTranscriptObservation.from_identity(
                name,
                identity,
                receipt=receipt,
                reason_code=reason_code,
                value=value,
            ),
        )

    def _observe_receipt_failure(
        self,
        name: str,
        receipt: SubAgentTranscriptReceipt,
        *,
        reason_code: str,
    ) -> None:
        record_subagent_transcript_observation(
            self._observation_sink,
            SubAgentTranscriptObservation(
                name=name,
                transcript_id=receipt.transcript_id,
                invocation_id=receipt.invocation_id,
                parent_run_id=receipt.parent_run_id,
                child_run_id=receipt.child_run_id,
                task_instance_id=receipt.task_instance_id,
                attempt=receipt.attempt,
                transcript_ref=receipt.transcript_ref,
                transcript_checksum=receipt.transcript_checksum,
                output_ref=receipt.output_ref,
                output_checksum=receipt.output_checksum,
                reason_code=reason_code,
            ),
        )


def _parse_ref(value: str, kind: str) -> tuple[str, str]:
    prefix = f"{kind}://v1/"
    if not isinstance(value, str) or not value.startswith(prefix):
        raise _store_error(
            "subagent_transcript_identity_mismatch",
            "subagent evidence ref is invalid",
            ref=str(value),
        )
    parts = value.removeprefix(prefix).split("/")
    if len(parts) != 2:
        raise _store_error(
            "subagent_transcript_identity_mismatch",
            "subagent evidence ref is invalid",
            ref=value,
        )
    try:
        parent = validate_artifact_path_segment(parts[0], field="parent_run_id")
        transcript_id = validate_artifact_path_segment(parts[1], field="transcript_id")
    except ArtifactPathError as exc:
        raise _store_error(
            "subagent_transcript_identity_mismatch",
            "subagent evidence ref path is invalid",
        ) from exc
    return parent, transcript_id


def _path_segment(value: str, field_name: str) -> str:
    try:
        return validate_artifact_path_segment(value, field=field_name)
    except ArtifactPathError as exc:
        raise _store_error(
            "subagent_transcript_identity_mismatch",
            "subagent transcript path identity is invalid",
            field=field_name,
        ) from exc


def _object(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _corrupt(f"subagent bundle {field_name} must be an object")
    return value


def _positive_limit(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _reason_code(exc: Exception) -> str:
    value = getattr(exc, "code", None)
    if isinstance(value, str) and value:
        return value
    return "subagent_transcript_store_unavailable"


def _is_corrupt_reason(reason_code: str) -> bool:
    return reason_code not in {
        "subagent_transcript_not_found",
        "subagent_transcript_store_unavailable",
        "subagent_transcript_size_exceeded",
    }


def _store_error(code: str, message: str, **details: Any) -> SubAgentTranscriptStoreError:
    return SubAgentTranscriptStoreError(message, code=code, details=details)


def _corrupt(
    message: str,
    *,
    code: str = "subagent_transcript_corrupt",
) -> SubAgentTranscriptCorruptError:
    return SubAgentTranscriptCorruptError(message, code=code)


__all__ = ["FilesystemSubAgentTranscriptStore"]
