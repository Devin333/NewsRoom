from __future__ import annotations

from tests.architecture._helpers import PROJECT_ROOT, forbidden_imports


FRAMEWORK_ROOT = PROJECT_ROOT / "framework"


def test_framework_does_not_import_business() -> None:
    assert forbidden_imports(FRAMEWORK_ROOT, ("business",)) == []


def test_framework_does_not_import_interfaces() -> None:
    assert forbidden_imports(FRAMEWORK_ROOT, ("interfaces",)) == []
