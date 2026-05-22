from __future__ import annotations

from scripts.dev import COMPILE_PATHS


def test_dev_compile_covers_business_and_infrastructure_layers() -> None:
    assert "business" in COMPILE_PATHS
    assert "infrastructure" in COMPILE_PATHS


def test_dev_compile_paths_exist() -> None:
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]

    missing = [path for path in COMPILE_PATHS if not (project_root / path).exists()]

    assert missing == []
