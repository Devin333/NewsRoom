from __future__ import annotations

from tests.architecture._helpers import PROJECT_ROOT, forbidden_imports


FRAMEWORK_ROOT = PROJECT_ROOT / "framework"


def test_framework_does_not_import_storage_or_infrastructure() -> None:
    assert forbidden_imports(FRAMEWORK_ROOT, ("storage", "infrastructure")) == []
