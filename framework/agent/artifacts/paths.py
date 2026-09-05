from __future__ import annotations

import re
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

from framework.agent.artifacts.observability import emit_artifact_path_rejected


_WINDOWS_RESERVED_CHARACTERS = frozenset('<>:"|?*')
_DOS_DEVICE_NAME = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$",
    re.IGNORECASE,
)


class ArtifactPathError(ValueError):
    """Raised before an artifact path can escape or become ambiguous."""


def artifact_path_key(path: PurePath) -> PurePath:
    """Compare filesystem paths without changing their operational namespace."""

    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("artifact path comparison requires an absolute path without '..'")
    if isinstance(path, PureWindowsPath):
        _validate_resolved_artifact_path_parts(path)
        drive = path.drive
        if re.fullmatch(r"\\\\\?\\[A-Za-z]:", drive):
            drive = drive[4:]
        elif drive.upper().startswith("\\\\?\\UNC\\"):
            drive = "\\\\" + drive[8:]
        return PureWindowsPath(drive + path.root, *path.parts[1:])
    return path


def _validate_resolved_artifact_path_parts(path: PurePath) -> None:
    """Reject ambiguous non-anchor segments before namespace comparison."""

    for part in path.parts[1:]:
        if (
            not part
            or _has_control_character(part)
            or any(character in _WINDOWS_RESERVED_CHARACTERS for character in part)
            or part.endswith((".", " "))
            or _DOS_DEVICE_NAME.fullmatch(part)
        ):
            raise ValueError("artifact path comparison contains an ambiguous segment")


def artifact_path_relative_to(path: PurePath, root: PurePath) -> PurePath:
    """Return relative components, allowing equivalent Windows namespaces."""

    relative = artifact_path_key(path).relative_to(artifact_path_key(root))
    # Preserve filename case and the original I/O path, including long-path prefixes.
    return type(path)(*path.parts[len(path.parts) - len(relative.parts):])


def validate_artifact_path_segment(value: str, *, field: str) -> str:
    """Return an unchanged, validated single filesystem path segment."""

    try:
        return _validate_artifact_path_segment(value, field=field)
    except ArtifactPathError:
        emit_artifact_path_rejected(field=field, operation="validate_segment")
        raise


def _validate_artifact_path_segment(value: str, *, field: str) -> str:
    """Validate a segment without emitting a nested boundary event."""

    if not isinstance(value, str):
        raise ArtifactPathError(f"{field} must be a string")
    if not value or not value.strip():
        raise ArtifactPathError(f"{field} is required")
    if value != value.strip():
        raise ArtifactPathError(
            f"invalid {field}: leading or trailing whitespace is not allowed"
        )
    if value in {".", ".."}:
        raise ArtifactPathError(f"invalid {field}: {value}")
    if "/" in value or "\\" in value:
        raise ArtifactPathError(f"invalid {field}: expected a single path segment")
    if _has_control_character(value):
        raise ArtifactPathError(f"invalid {field}: control characters are not allowed")
    if any(character in _WINDOWS_RESERVED_CHARACTERS for character in value):
        raise ArtifactPathError(f"invalid {field}: reserved path character")
    if value.endswith((".", " ")):
        raise ArtifactPathError(f"invalid {field}: trailing dot or space")
    if _DOS_DEVICE_NAME.fullmatch(value):
        raise ArtifactPathError(f"invalid {field}: reserved device name")

    windows = PureWindowsPath(value)
    posix = PurePosixPath(value)
    if windows.is_absolute() or windows.drive or posix.is_absolute():
        raise ArtifactPathError(f"invalid {field}: expected a relative path segment")
    if len(windows.parts) != 1 or len(posix.parts) != 1:
        raise ArtifactPathError(f"invalid {field}: expected a single path segment")
    return value


def validate_relative_artifact_path(value: str, *, field: str) -> str:
    """Return a normalized POSIX path that is relative to an artifact root."""

    try:
        return _validate_relative_artifact_path(value, field=field)
    except ArtifactPathError:
        emit_artifact_path_rejected(field=field, operation="validate_relative")
        raise


def _validate_relative_artifact_path(value: str, *, field: str) -> str:
    """Validate a relative path without emitting nested boundary events."""

    if not isinstance(value, str):
        raise ArtifactPathError(f"{field} must be a string")
    if not value or not value.strip():
        raise ArtifactPathError(f"{field} is required")
    if value != value.strip():
        raise ArtifactPathError(
            f"invalid {field}: leading or trailing whitespace is not allowed"
        )

    normalized = value.replace("\\", "/")
    raw_parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ArtifactPathError(f"invalid {field}: {value}")
    windows = PureWindowsPath(value)
    posix = PurePosixPath(normalized)
    if windows.is_absolute() or windows.drive or posix.is_absolute():
        raise ArtifactPathError(f"invalid {field}: expected a relative path")
    if not posix.parts:
        raise ArtifactPathError(f"invalid {field}: {value}")
    for part in posix.parts:
        _validate_artifact_path_segment(part, field=field)
    result = posix.as_posix()
    if result in {"", "."}:
        raise ArtifactPathError(f"invalid {field}: {value}")
    return result


def resolve_artifact_descendant(
    root: str | Path,
    *relative_parts: str | Path,
    field: str,
) -> Path:
    """Resolve a canonical descendant and reject targets outside ``root``."""

    try:
        return _resolve_artifact_descendant(
            root,
            *relative_parts,
            field=field,
        )
    except ArtifactPathError:
        emit_artifact_path_rejected(field=field, operation="resolve_descendant")
        raise


def _resolve_artifact_descendant(
    root: str | Path,
    *relative_parts: str | Path,
    field: str,
) -> Path:
    """Resolve a descendant without emitting nested boundary events."""

    canonical_root = Path(root).resolve(strict=False)
    normalized_parts: list[str] = []
    for index, part in enumerate(relative_parts):
        raw = str(part)
        normalized = _validate_relative_artifact_path(
            raw,
            field=field if len(relative_parts) == 1 else f"{field}[{index}]",
        )
        normalized_parts.extend(PurePosixPath(normalized).parts)
    if not normalized_parts:
        raise ArtifactPathError(f"{field} is required")
    candidate = canonical_root.joinpath(*normalized_parts).resolve(strict=False)
    try:
        artifact_path_relative_to(candidate, canonical_root)
    except ValueError as exc:
        raise ArtifactPathError(f"{field} must stay within the artifact root") from exc
    return candidate


def _has_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


__all__ = [
    "ArtifactPathError",
    "artifact_path_key",
    "artifact_path_relative_to",
    "resolve_artifact_descendant",
    "validate_artifact_path_segment",
    "validate_relative_artifact_path",
]
