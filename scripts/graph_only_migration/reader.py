from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
from types import MappingProxyType
from typing import Any

from scripts.graph_only_migration.contracts import (
    LegacyRecord,
    LegacyRecordKind,
    LegacySourceDescriptor,
    QuarantineReasonCode,
    required_text,
)


SOURCE_PROFILE_REGISTRY_SCHEMA = (
    "newsroom.graph-history-source-profile-registry/v1"
)
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_RECORDS = 1_000_000

_WINDOWS_RESERVED_CHARACTERS = frozenset('<>:"|?*')
_DOS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class MigrationSourceReadError(RuntimeError):
    def __init__(
        self,
        reason_code: QuarantineReasonCode | str,
        message: str,
    ) -> None:
        self.reason_code = QuarantineReasonCode(reason_code)
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class SourceProfile:
    record_kind: LegacyRecordKind
    source_schema_version: str
    document_format: str
    embedded_schema_field: str | None
    embedded_schema_optional: bool
    record_shape: str
    path_layout: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SourceProfile:
        expected = {
            "record_kind",
            "source_schema_version",
            "document_format",
            "embedded_schema_field",
            "embedded_schema_optional",
            "record_shape",
            "path_layout",
        }
        if set(value) != expected:
            raise ValueError("source profile contains missing or unknown fields")
        document_format = required_text(value["document_format"], "document_format")
        if document_format not in {"json", "jsonl"}:
            raise ValueError("source profile document_format is unsupported")
        embedded = value["embedded_schema_field"]
        if embedded is not None:
            embedded = required_text(embedded, "embedded_schema_field")
        embedded_optional = value["embedded_schema_optional"]
        if not isinstance(embedded_optional, bool):
            raise ValueError("embedded_schema_optional must be a boolean")
        if embedded is None and embedded_optional:
            raise ValueError("schema cannot be optional when no field is configured")
        record_shape = required_text(value["record_shape"], "record_shape")
        if record_shape not in {
            "legacy_flat",
            "canonical_stored_event",
            "legacy_checkpoint",
            "replay_bundle",
            "artifact_index",
            "conversation_cursor",
            "iteration_checkpoint",
        }:
            raise ValueError("source profile record_shape is unsupported")
        path_layout = required_text(value["path_layout"], "path_layout")
        if path_layout not in {
            "segment/manifest.json",
            "segment.jsonl",
            "segment/segment.json",
            "segment/replay_bundle.json",
            "segment/cursor.json",
            "segment/iteration_checkpoint.json",
        }:
            raise ValueError("source profile path_layout is unsupported")
        return cls(
            record_kind=LegacyRecordKind(value["record_kind"]),
            source_schema_version=required_text(
                value["source_schema_version"],
                "source_schema_version",
            ),
            document_format=document_format,
            embedded_schema_field=embedded,
            embedded_schema_optional=embedded_optional,
            record_shape=record_shape,
            path_layout=path_layout,
        )


class SourceProfileRegistry:
    def __init__(self, profiles: tuple[SourceProfile, ...]) -> None:
        if not profiles:
            raise ValueError("source profile registry must not be empty")
        indexed: dict[tuple[LegacyRecordKind, str], SourceProfile] = {}
        for profile in profiles:
            if not isinstance(profile, SourceProfile):
                raise TypeError("profiles must contain SourceProfile values")
            key = (profile.record_kind, profile.source_schema_version)
            if key in indexed:
                raise ValueError("source profile registry contains a duplicate profile")
            indexed[key] = profile
        self._profiles = MappingProxyType(indexed)

    @classmethod
    def load_default(cls) -> SourceProfileRegistry:
        path = Path(__file__).with_name("source_profiles.json")
        try:
            payload = _load_json_object(path.read_bytes(), source=str(path))
        except (OSError, UnicodeError, ValueError) as exc:
            raise RuntimeError("migration source profile registry is invalid") from exc
        if payload.get("schema_version") != SOURCE_PROFILE_REGISTRY_SCHEMA:
            raise RuntimeError("unsupported migration source profile registry schema")
        raw_profiles = payload.get("profiles")
        if not isinstance(raw_profiles, list):
            raise RuntimeError("migration source profile registry profiles must be an array")
        try:
            profiles = tuple(
                SourceProfile.from_dict(_object(item, "source profile"))
                for item in raw_profiles
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeError("migration source profile registry is invalid") from exc
        return cls(profiles)

    def resolve(self, source: LegacySourceDescriptor) -> SourceProfile:
        try:
            return self._profiles[(source.record_kind, source.source_schema_version)]
        except KeyError as exc:
            raise MigrationSourceReadError(
                QuarantineReasonCode.UNKNOWN_SCHEMA,
                "source schema is not registered for this migration record kind",
            ) from exc

    @property
    def profiles(self) -> tuple[SourceProfile, ...]:
        return tuple(
            self._profiles[key]
            for key in sorted(
                self._profiles,
                key=lambda item: (item[0].value, item[1]),
            )
        )


class BoundedLegacySourceReader:
    """Read exact, checksummed records from a detached migration snapshot."""

    def __init__(
        self,
        *,
        registry: SourceProfileRegistry | None = None,
        max_source_bytes: int = MAX_SOURCE_BYTES,
        max_source_records: int = MAX_SOURCE_RECORDS,
    ) -> None:
        self._registry = registry or SourceProfileRegistry.load_default()
        if (
            isinstance(max_source_bytes, bool)
            or not isinstance(max_source_bytes, int)
            or max_source_bytes < 1
        ):
            raise ValueError("max_source_bytes must be a positive integer")
        if (
            isinstance(max_source_records, bool)
            or not isinstance(max_source_records, int)
            or max_source_records < 1
        ):
            raise ValueError("max_source_records must be a positive integer")
        self._max_source_bytes = max_source_bytes
        self._max_source_records = max_source_records

    def read(self, source: LegacySourceDescriptor) -> tuple[LegacyRecord, ...]:
        if not isinstance(source, LegacySourceDescriptor):
            raise TypeError("source must be a LegacySourceDescriptor")
        profile = self._registry.resolve(source)
        path = _resolve_source_path(source, profile)
        raw = self._read_bounded_file(path)
        actual_checksum = checksum_bytes(raw)
        if not compare_digest(actual_checksum, source.source_checksum):
            raise MigrationSourceReadError(
                QuarantineReasonCode.CHECKSUM_MISMATCH,
                "source file checksum does not match the inventory checksum",
            )
        try:
            values = self._parse(raw, profile=profile, source_ref=source.source_ref)
        except (UnicodeError, ValueError, TypeError) as exc:
            raise MigrationSourceReadError(
                QuarantineReasonCode.MALFORMED_SOURCE,
                "source file is not strict canonicalizable JSON",
            ) from exc
        records: list[LegacyRecord] = []
        for ordinal, value in enumerate(values, start=1):
            _validate_embedded_schema(value, profile)
            _validate_minimum_shape(value, profile)
            record_ref = (
                f"{source.source_ref}#line={ordinal}"
                if profile.document_format == "jsonl"
                else source.source_ref
            )
            try:
                records.append(
                    LegacyRecord(
                        source=source,
                        source_record_ref=record_ref,
                        ordinal=ordinal,
                        value=value,
                    )
                )
            except (TypeError, ValueError) as exc:
                raise MigrationSourceReadError(
                    QuarantineReasonCode.MALFORMED_SOURCE,
                    "source record is not canonicalizable JSON",
                ) from exc
        return tuple(records)

    def _read_bounded_file(self, path: Path) -> bytes:
        try:
            before = path.stat()
        except OSError as exc:
            raise MigrationSourceReadError(
                QuarantineReasonCode.ILLEGAL_SOURCE_PATH,
                "source file cannot be inspected",
            ) from exc
        if not stat.S_ISREG(before.st_mode) or _stat_is_reparse_point(before):
            raise MigrationSourceReadError(
                QuarantineReasonCode.ILLEGAL_SOURCE_PATH,
                "source file must remain a non-linked regular file",
            )
        if before.st_size > self._max_source_bytes:
            raise MigrationSourceReadError(
                QuarantineReasonCode.MALFORMED_SOURCE,
                "source file exceeds the configured byte limit",
            )
        try:
            with path.open("rb") as handle:
                raw = handle.read(self._max_source_bytes + 1)
                after = os.fstat(handle.fileno())
        except OSError as exc:
            raise MigrationSourceReadError(
                QuarantineReasonCode.ILLEGAL_SOURCE_PATH,
                "source file cannot be read",
            ) from exc
        if len(raw) > self._max_source_bytes:
            raise MigrationSourceReadError(
                QuarantineReasonCode.MALFORMED_SOURCE,
                "source file grew beyond the configured byte limit while reading",
            )
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if (
            before_identity != after_identity
            or not stat.S_ISREG(after.st_mode)
            or _stat_is_reparse_point(after)
        ):
            raise MigrationSourceReadError(
                QuarantineReasonCode.ILLEGAL_SOURCE_PATH,
                "source file changed identity while it was being read",
            )
        return raw

    def _parse(
        self,
        raw: bytes,
        *,
        profile: SourceProfile,
        source_ref: str,
    ) -> tuple[Mapping[str, Any], ...]:
        if profile.document_format == "json":
            return (_load_json_object(raw, source=source_ref),)
        text = raw.decode("utf-8")
        records: list[Mapping[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                raise ValueError(f"blank JSONL record at line {line_number}")
            records.append(
                _load_json_object(
                    line.encode("utf-8"),
                    source=f"{source_ref}#line={line_number}",
                )
            )
            if len(records) > self._max_source_records:
                raise ValueError("source file exceeds the configured record limit")
        if not records:
            raise ValueError("source file contains no records")
        return tuple(records)


def checksum_bytes(value: bytes) -> str:
    return f"sha256:{sha256(value).hexdigest()}"


def _resolve_source_path(
    source: LegacySourceDescriptor,
    profile: SourceProfile,
) -> Path:
    try:
        normalized = _validate_relative_source_path(
            source.relative_path,
            layout=profile.path_layout,
        )
        root = source.source_root
        _reject_reparse_point(root, field="source_root")
        canonical_root = root.resolve(strict=True)
        if not canonical_root.is_dir():
            raise ValueError("source_root must be a directory")
        candidate = canonical_root.joinpath(*PurePosixPath(normalized).parts)
        current = canonical_root
        for part in PurePosixPath(normalized).parts:
            current = current / part
            _reject_reparse_point(current, field="source_path")
        canonical_candidate = candidate.resolve(strict=True)
        canonical_candidate.relative_to(canonical_root)
        status = canonical_candidate.stat()
        if not stat.S_ISREG(status.st_mode):
            raise ValueError("source path must identify a regular file")
        return canonical_candidate
    except (OSError, RuntimeError, ValueError) as exc:
        raise MigrationSourceReadError(
            QuarantineReasonCode.ILLEGAL_SOURCE_PATH,
            "source path is outside the approved snapshot layout or is linked",
        ) from exc


def _validate_relative_source_path(value: str, *, layout: str) -> str:
    raw = required_text(value, "relative_path")
    normalized = raw.replace("\\", "/")
    windows = PureWindowsPath(raw)
    posix = PurePosixPath(normalized)
    if windows.is_absolute() or windows.drive or posix.is_absolute():
        raise ValueError("relative_path must be relative")
    parts = posix.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("relative_path contains an unsafe component")
    if layout == "segment.jsonl":
        if len(parts) != 1 or not parts[0].endswith(".jsonl"):
            raise ValueError("relative_path does not match the source profile")
        _validate_segment(parts[0][:-6], "relative_path")
    elif layout == "segment/segment.json":
        if len(parts) != 2 or not parts[1].endswith(".json"):
            raise ValueError("relative_path does not match the source profile")
        _validate_segment(parts[0], "relative_path")
        _validate_segment(parts[1][:-5], "relative_path")
    else:
        expected_name = layout.split("/", maxsplit=1)[1]
        if len(parts) != 2 or parts[1] != expected_name:
            raise ValueError("relative_path does not match the source profile")
        _validate_segment(parts[0], "relative_path")
    return posix.as_posix()


def _validate_segment(value: str, field_name: str) -> None:
    text = required_text(value, field_name)
    if text in {".", ".."} or "/" in text or "\\" in text:
        raise ValueError(f"{field_name} contains an unsafe segment")
    if any(character in _WINDOWS_RESERVED_CHARACTERS for character in text):
        raise ValueError(f"{field_name} contains a reserved character")
    if text.endswith((".", " ")) or text.upper() in _DOS_DEVICE_NAMES:
        raise ValueError(f"{field_name} contains a reserved segment")


def _reject_reparse_point(path: Path, *, field: str) -> None:
    status = path.lstat()
    if path.is_symlink() or _stat_is_reparse_point(status):
        raise ValueError(f"{field} must not be a symlink, junction, or reparse point")


def _stat_is_reparse_point(status: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(status, "st_file_attributes", 0)
    return bool(attributes & reparse_flag)


def _load_json_object(raw: bytes, *, source: str) -> dict[str, Any]:
    text = raw.decode("utf-8")

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r} in {source}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON number {value!r} in {source}")

    value = json.loads(
        text,
        object_pairs_hook=object_pairs,
        parse_constant=reject_constant,
    )
    return _object(value, source)


def _object(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a JSON object")
    return value


def _validate_embedded_schema(
    value: Mapping[str, Any],
    profile: SourceProfile,
) -> None:
    field_name = profile.embedded_schema_field
    if field_name is None:
        if "schema_version" in value or "schema" in value:
            raise MigrationSourceReadError(
                QuarantineReasonCode.UNKNOWN_SCHEMA,
                "unversioned source profile contains an unexpected embedded schema",
            )
        return
    embedded_value = value.get(field_name)
    if embedded_value is None and profile.embedded_schema_optional:
        return
    if embedded_value != profile.source_schema_version:
        raise MigrationSourceReadError(
            QuarantineReasonCode.UNKNOWN_SCHEMA,
            "embedded source schema does not match the inventory profile",
        )


def _validate_minimum_shape(
    value: Mapping[str, Any],
    profile: SourceProfile,
) -> None:
    required_by_kind = {
        LegacyRecordKind.RUN_MANIFEST: {
            "run_id",
            "workflow_id",
            "workflow_version",
            "status",
            "started_at",
            "artifacts",
            "artifact_index",
        },
        LegacyRecordKind.WORKFLOW_CHECKPOINT: {
            "checkpoint_id",
            "run_id",
            "workflow_id",
            "workflow_version",
            "current_step_ids",
            "data_buffer_snapshot",
            "created_at",
        },
        LegacyRecordKind.REPLAY_BUNDLE: {
            "manifest",
            "events",
            "artifacts",
            "integrity",
            "routing_diagnostics",
        },
        LegacyRecordKind.ARTIFACT_INDEX: {
            "artifact_id",
            "run_id",
            "step_id",
            "path",
            "content_type",
            "size_bytes",
            "checksum",
        },
        LegacyRecordKind.CONVERSATION_CURSOR: {
            "conversation_id",
            "message_offset",
            "updated_at",
        },
        LegacyRecordKind.ITERATION_CHECKPOINT: {
            "conversation_id",
            "agent_id",
            "iteration",
            "status",
            "updated_at",
        },
    }
    if profile.record_shape == "canonical_stored_event":
        required_fields = {
            "envelope_schema",
            "event_id",
            "event_type",
            "data_schema",
            "source",
            "occurred_at",
            "observed_at",
            "stream_id",
            "stream_sequence",
            "business_context",
            "producer",
            "content_checksum",
            "record_checksum",
        }
        if "payload" not in value and "payload_ref" not in value:
            required_fields.add("payload")
    elif profile.record_kind is LegacyRecordKind.WORKFLOW_EVENT:
        required_fields = {
            "event_id",
            "event_type",
            "run_id",
            "stream_id",
            "stream_sequence",
            "payload",
        }
    else:
        required_fields = required_by_kind[profile.record_kind]
    missing = required_fields - set(value)
    if missing:
        raise MigrationSourceReadError(
            QuarantineReasonCode.AMBIGUOUS_RECORD,
            "source record is missing required migration fields: "
            + ", ".join(sorted(missing)),
        )


__all__ = [
    "BoundedLegacySourceReader",
    "MAX_SOURCE_BYTES",
    "MAX_SOURCE_RECORDS",
    "MigrationSourceReadError",
    "SOURCE_PROFILE_REGISTRY_SCHEMA",
    "SourceProfile",
    "SourceProfileRegistry",
    "checksum_bytes",
]
