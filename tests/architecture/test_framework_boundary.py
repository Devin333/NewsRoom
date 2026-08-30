from __future__ import annotations

from tests.architecture._helpers import PROJECT_ROOT, forbidden_imports


FRAMEWORK_ROOT = PROJECT_ROOT / "framework"
FORBIDDEN_IMPORT_PREFIXES = (
    "backend",
    "interfaces",
    "infrastructure",
    "storage",
    "domain",
    "evidence",
    "sources",
    "workflows",
    "quality",
)


def test_framework_does_not_import_forbidden_layers() -> None:
    assert forbidden_imports(FRAMEWORK_ROOT, FORBIDDEN_IMPORT_PREFIXES) == []
