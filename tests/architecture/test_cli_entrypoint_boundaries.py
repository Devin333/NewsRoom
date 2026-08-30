from __future__ import annotations

from tests.architecture._helpers import PROJECT_ROOT, imported_modules, matches_prefix


NEWS_ENTRYPOINT = PROJECT_ROOT / "interfaces" / "cli" / "news.py"
FORBIDDEN_DIRECT_IMPORTS = (
    "backend",
    "framework",
    "infrastructure",
    "interfaces.services",
)


def test_cli_news_does_not_import_business_framework_infrastructure_or_services() -> None:
    violations = [
        imported
        for imported in imported_modules(NEWS_ENTRYPOINT)
        if matches_prefix(imported, FORBIDDEN_DIRECT_IMPORTS)
    ]

    assert violations == []
