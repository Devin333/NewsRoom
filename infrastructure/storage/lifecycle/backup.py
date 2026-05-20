from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from infrastructure.storage.artifacts.filesystem import _validate_relative_path


_MANIFEST_PATH = "_backup/manifest.json"
_FILES_PREFIX = "files/"
_SCHEMA_VERSION = "1.0"


class BackupValidationError(ValueError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class BackupFileEntry:
    path: str
    size_bytes: int
    checksum: str

    def __post_init__(self) -> None:
        _normalize_backup_path(self.path)
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be greater than or equal to zero")
        if not self.checksum:
            raise ValueError("checksum is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BackupFileEntry:
        return cls(
            path=_normalize_backup_path(str(payload["path"])),
            size_bytes=int(payload["size_bytes"]),
            checksum=str(payload["checksum"]),
        )


@dataclass(frozen=True)
class BackupManifest:
    source_artifact_root: str
    created_at: datetime = field(default_factory=_utc_now)
    files: list[BackupFileEntry] = field(default_factory=list)
    schema_version: str = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not str(self.source_artifact_root).strip():
            raise ValueError("source_artifact_root is required")

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def total_bytes(self) -> int:
        return sum(entry.size_bytes for entry in self.files)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_artifact_root": self.source_artifact_root,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "files": [entry.to_dict() for entry in self.files],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BackupManifest:
        schema_version = str(payload.get("schema_version", ""))
        if schema_version != _SCHEMA_VERSION:
            raise BackupValidationError(f"unsupported backup schema_version: {schema_version}")
        files = [BackupFileEntry.from_dict(item) for item in payload.get("files", [])]
        _reject_duplicate_paths(files)
        return cls(
            schema_version=schema_version,
            source_artifact_root=str(payload.get("source_artifact_root", "")),
            created_at=_parse_datetime(str(payload["created_at"])),
            files=files,
        )


class LocalArtifactBackupService:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.artifact_root = Path(artifact_root)

    def create_backup(
        self,
        backup_path: str | Path,
        *,
        overwrite: bool = False,
        now: datetime | None = None,
    ) -> BackupManifest:
        if not self.artifact_root.exists():
            raise FileNotFoundError(f"artifact root does not exist: {self.artifact_root}")
        if not self.artifact_root.is_dir():
            raise ValueError(f"artifact root is not a directory: {self.artifact_root}")

        target = Path(backup_path)
        _ensure_backup_target_allowed(self.artifact_root, target)
        if target.exists() and not overwrite:
            raise FileExistsError(f"backup already exists: {target}")

        files = list(_iter_files(self.artifact_root))
        entries: list[BackupFileEntry] = []
        target.parent.mkdir(parents=True, exist_ok=True)

        with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
            for source_path, relative_path in files:
                data = source_path.read_bytes()
                entry = BackupFileEntry(
                    path=relative_path,
                    size_bytes=len(data),
                    checksum=sha256(data).hexdigest(),
                )
                archive.writestr(f"{_FILES_PREFIX}{relative_path}", data)
                entries.append(entry)

            manifest = BackupManifest(
                source_artifact_root=str(self.artifact_root),
                created_at=(now or _utc_now()).astimezone(UTC),
                files=entries,
            )
            archive.writestr(
                _MANIFEST_PATH,
                json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )

        return manifest

    def restore_backup(
        self,
        backup_path: str | Path,
        *,
        overwrite: bool = False,
    ) -> BackupManifest:
        source = Path(backup_path)
        if not source.exists():
            raise FileNotFoundError(f"backup does not exist: {source}")

        with ZipFile(source, "r") as archive:
            try:
                manifest = BackupManifest.from_dict(
                    json.loads(archive.read(_MANIFEST_PATH).decode("utf-8"))
                )
            except KeyError as exc:
                raise BackupValidationError("backup manifest is missing") from exc
            _ensure_restore_target_allowed(self.artifact_root, manifest)

            restored_files = []
            for entry in manifest.files:
                relative_path = _normalize_backup_path(entry.path)
                member_name = f"{_FILES_PREFIX}{relative_path}"
                try:
                    data = archive.read(member_name)
                except KeyError as exc:
                    raise BackupValidationError(f"backup file is missing: {relative_path}") from exc
                _validate_entry_bytes(entry, data)
                target = self.artifact_root / Path(relative_path)
                if target.exists() and not overwrite:
                    raise FileExistsError(f"target file already exists: {target}")
                restored_files.append((target, data))

            for target, data in restored_files:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

        return manifest


def _iter_files(root: Path) -> list[tuple[Path, str]]:
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative_path = _normalize_backup_path(path.relative_to(root).as_posix())
        files.append((path, relative_path))
    return files


def _normalize_backup_path(value: str) -> str:
    return _validate_relative_path(value).as_posix()


def _ensure_backup_target_allowed(artifact_root: Path, backup_path: Path) -> None:
    root = artifact_root.resolve()
    target = backup_path.resolve()
    if target == root or target.is_relative_to(root):
        raise ValueError("backup path must be outside artifact root")


def _ensure_restore_target_allowed(artifact_root: Path, manifest: BackupManifest) -> None:
    target = artifact_root.resolve()
    source_root = Path(manifest.source_artifact_root).resolve()
    if target == source_root:
        raise BackupValidationError("restore target must differ from backup source artifact root")


def _validate_entry_bytes(entry: BackupFileEntry, data: bytes) -> None:
    if len(data) != entry.size_bytes:
        raise BackupValidationError(f"backup file size mismatch: {entry.path}")
    if sha256(data).hexdigest() != entry.checksum:
        raise BackupValidationError(f"backup file checksum mismatch: {entry.path}")


def _reject_duplicate_paths(entries: list[BackupFileEntry]) -> None:
    seen = set()
    for entry in entries:
        if entry.path in seen:
            raise BackupValidationError(f"duplicate backup path: {entry.path}")
        seen.add(entry.path)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
