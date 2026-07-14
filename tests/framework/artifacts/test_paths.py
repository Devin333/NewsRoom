from __future__ import annotations

import os
from pathlib import Path

import pytest

from framework.artifacts import (
    ArtifactPathError,
    resolve_artifact_descendant,
    validate_artifact_path_segment,
    validate_relative_artifact_path,
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
