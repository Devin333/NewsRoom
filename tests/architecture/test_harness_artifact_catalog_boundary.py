from __future__ import annotations

from tests.architecture._helpers import PROJECT_ROOT, forbidden_imports


CATALOG_ROOT = PROJECT_ROOT / "framework" / "harness" / "artifacts"


def test_harness_artifact_catalog_has_no_outer_or_vendor_storage_dependencies() -> None:
    assert forbidden_imports(
        CATALOG_ROOT,
        (
            "business",
            "interfaces",
            "infrastructure",
            "storage",
            "psycopg",
            "redis",
            "qdrant_client",
            "sqlalchemy",
        ),
    ) == []
