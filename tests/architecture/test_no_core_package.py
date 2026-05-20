from __future__ import annotations

from tests.architecture._helpers import PROJECT_ROOT


def test_core_package_directory_is_removed() -> None:
    assert not (PROJECT_ROOT / "core").exists()
