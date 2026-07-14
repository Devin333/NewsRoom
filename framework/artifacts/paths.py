from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath


_WINDOWS_RESERVED_CHARACTERS = frozenset('<>:"|?*')
_DOS_DEVICE_NAME = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$",
    re.IGNORECASE,
)


class ArtifactPathError(ValueError):
    """Raised before an artifact path can escape or become ambiguous."""


def validate_artifact_path_segment(value: str, *, field: str) -> str:
    """Return an unchanged, validated single filesystem path segment."""

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
        validate_artifact_path_segment(part, field=field)
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

    canonical_root = Path(root).resolve(strict=False)
    normalized_parts: list[str] = []
    for index, part in enumerate(relative_parts):
        raw = str(part)
        normalized = validate_relative_artifact_path(
            raw,
            field=field if len(relative_parts) == 1 else f"{field}[{index}]",
        )
        normalized_parts.extend(PurePosixPath(normalized).parts)
    if not normalized_parts:
        raise ArtifactPathError(f"{field} is required")
    candidate = canonical_root.joinpath(*normalized_parts).resolve(strict=False)
    try:
        candidate.relative_to(canonical_root)
    except ValueError as exc:
        raise ArtifactPathError(f"{field} must stay within the artifact root") from exc
    return candidate


def _has_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


__all__ = [
    "ArtifactPathError",
    "resolve_artifact_descendant",
    "validate_artifact_path_segment",
    "validate_relative_artifact_path",
]
