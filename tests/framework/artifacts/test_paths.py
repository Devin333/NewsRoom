from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from framework.agent.artifacts import (
    ArtifactPathError,
    resolve_artifact_descendant,
    validate_artifact_path_segment,
    validate_relative_artifact_path,
)
from framework.agent.artifacts.paths import (
    artifact_path_key,
    artifact_path_relative_to,
)


@pytest.mark.parametrize("value", ["run-1", "abc.def", "_records", "0123456789abcdef"])
def test_validate_artifact_path_segment_accepts_safe_values(value: str) -> None:
    assert validate_artifact_path_segment(value, field="run_id") == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        ".",
        "..",
        "../x",
        "..\\x",
        "a/b",
        "a\\b",
        "/x",
        "C:\\x",
        "C:x",
        "\\\\server\\share",
        "\\\\?\\C:\\x",
        "report.txt:payload",
        "name.",
        "name ",
        "name<bad>",
        "CON",
        "NUL.txt",
        "COM1",
        "line\nbreak",
    ],
)
def test_validate_artifact_path_segment_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ArtifactPathError):
        validate_artifact_path_segment(value, field="run_id")


def test_validate_relative_artifact_path_normalizes_nested_path() -> None:
    assert (
        validate_relative_artifact_path("steps\\s1\\output.json", field="artifact_path")
        == "steps/s1/output.json"
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        ".",
        "steps/./output.json",
        "steps//output.json",
        "../secret",
        "steps/../../secret",
        "/secret",
        "C:\\secret",
        "C:secret",
        "\\\\server\\share",
        "steps/report.txt:payload",
        "steps/name.",
        "steps/NUL.txt",
    ],
)
def test_validate_relative_artifact_path_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ArtifactPathError):
        validate_relative_artifact_path(value, field="artifact_path")


def test_resolve_artifact_descendant_returns_canonical_target(tmp_path: Path) -> None:
    assert resolve_artifact_descendant(
        tmp_path,
        "run-1",
        "steps/s1/output.json",
        field="artifact_path",
    ) == tmp_path / "run-1" / "steps" / "s1" / "output.json"


def test_resolve_artifact_descendant_rejects_link_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "linked"
    try:
        if os.name == "nt":
            link.symlink_to(outside, target_is_directory=True)
        else:
            link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    with pytest.raises(ArtifactPathError):
        resolve_artifact_descendant(root, "linked/secret.txt", field="artifact_path")


@pytest.mark.parametrize(
    ("candidate", "root", "expected"),
    (
        (r"\\?\C:\Artifacts\run-1\output.json", r"C:\Artifacts", "run-1/output.json"),
        (r"C:\Artifacts\run-1\output.json", r"\\?\C:\Artifacts", "run-1/output.json"),
        (
            r"\\?\UNC\server\share\Artifacts\run-1\output.json",
            r"\\server\share\Artifacts",
            "run-1/output.json",
        ),
        (
            r"\\server\share\Artifacts\run-1\output.json",
            r"\\?\UNC\server\share\Artifacts",
            "run-1/output.json",
        ),
    ),
)
def test_artifact_path_relative_to_unifies_known_windows_namespaces(
    candidate: str,
    root: str,
    expected: str,
) -> None:
    relative = artifact_path_relative_to(
        PureWindowsPath(candidate),
        PureWindowsPath(root),
    )

    assert relative.as_posix() == expected


@pytest.mark.parametrize(
    ("candidate", "root"),
    (
        (r"\\?\D:\Artifacts\run-1", r"C:\Artifacts"),
        (r"\\?\UNC\server\other\Artifacts\run-1", r"\\server\share\Artifacts"),
        (r"\\?\C:\Artifacts-other\run-1", r"C:\Artifacts"),
        (r"\\?\C:\Artifacts\..\outside", r"C:\Artifacts"),
    ),
)
def test_artifact_path_relative_to_rejects_windows_escape_or_prefix_collision(
    candidate: str,
    root: str,
) -> None:
    with pytest.raises(ValueError):
        artifact_path_relative_to(
            PureWindowsPath(candidate),
            PureWindowsPath(root),
        )


def test_artifact_path_key_leaves_unknown_windows_device_namespace_unchanged() -> None:
    volume_path = PureWindowsPath(r"\\?\Volume{1234}\Artifacts\run-1")

    assert artifact_path_key(volume_path) == volume_path


def test_artifact_path_comparison_preserves_posix_root_names_and_case() -> None:
    root = PurePosixPath("/srv/artifacts:archive/NUL")
    candidate = root / "run-1" / "payload.json"

    assert artifact_path_key(root) == root
    assert artifact_path_relative_to(candidate, root) == PurePosixPath("run-1/payload.json")
    with pytest.raises(ValueError):
        artifact_path_relative_to(candidate, PurePosixPath("/srv/Artifacts:archive/NUL"))


@pytest.mark.parametrize(
    "path",
    (
        r"C:\Artifacts\name.\output.json",
        r"C:\Artifacts\name \output.json",
        r"C:\Artifacts\NUL\output.json",
        r"C:\Artifacts\report.txt:stream",
    ),
)
def test_artifact_path_key_rejects_ambiguous_resolved_windows_segment(
    path: str,
) -> None:
    with pytest.raises(ValueError):
        artifact_path_key(PureWindowsPath(path))
