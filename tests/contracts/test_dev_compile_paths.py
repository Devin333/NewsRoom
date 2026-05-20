from __future__ import annotations

from scripts.dev import COMPILE_PATHS


def test_dev_compile_covers_business_and_infrastructure_layers() -> None:
    assert "business" in COMPILE_PATHS
    assert "infrastructure" in COMPILE_PATHS
