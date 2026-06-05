from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUSINESS_ROOT = PROJECT_ROOT / "business"


def test_business_foundation_does_not_import_layers_or_boards() -> None:
    violations = _forbidden_imports(
        BUSINESS_ROOT / "foundation",
        forbidden_prefixes=("business.layers", "business.boards"),
    )

    assert violations == []


def test_business_layers_do_not_import_boards() -> None:
    violations = _forbidden_imports(
        BUSINESS_ROOT / "layers",
        forbidden_prefixes=("business.boards",),
    )

    assert violations == []


def test_business_research_does_not_import_legacy_or_interface_layers() -> None:
    violations = _forbidden_imports(
        BUSINESS_ROOT / "research",
        forbidden_prefixes=("business.boards", "interfaces", "infrastructure"),
    )

    assert violations == []


def test_business_has_no_direct_legacy_domain_or_source_imports() -> None:
    violations = _forbidden_imports(
        BUSINESS_ROOT,
        forbidden_prefixes=("domain", "sources", "workflows", "evidence", "quality", "storage", "interfaces"),
    )

    assert violations == []


def test_signal_artifact_boundary_does_not_import_storage_artifacts() -> None:
    violations = _forbidden_imports(
        BUSINESS_ROOT / "layers" / "signal",
        forbidden_prefixes=("infrastructure.storage.artifacts",),
    )

    assert violations == []


def test_signal_source_processing_does_not_import_external_source_infrastructure() -> None:
    violations = _forbidden_imports(
        BUSINESS_ROOT / "layers" / "signal" / "source_processing",
        forbidden_prefixes=("infrastructure.external.sources",),
    )

    assert violations == []


def test_signal_source_router_uses_injected_connector_boundary() -> None:
    imported_modules = _imports_for_file(BUSINESS_ROOT / "layers" / "signal" / "source_router.py")

    assert _matching_forbidden(imported_modules, ("infrastructure.external.sources",)) == []


def test_signal_connector_tools_keep_real_connector_urls_outside_old_boards() -> None:
    imported_modules = _imports_for_file(BUSINESS_ROOT / "layers" / "signal" / "connector_tools.py")
    source = (BUSINESS_ROOT / "layers" / "signal" / "connector_tools.py").read_text(encoding="utf-8")

    assert _matching_forbidden(imported_modules, ("business.boards",)) == []
    assert "https://export.arxiv.org/api/query" in source
    assert "https://api.github.com" in source


def test_relation_lineage_boundary_does_not_import_storage_lineage() -> None:
    violations = _forbidden_imports(
        BUSINESS_ROOT / "layers" / "relation",
        forbidden_prefixes=("infrastructure.storage.lineage",),
    )

    assert violations == []


def test_output_report_tools_do_not_import_storage_or_domain_report_models() -> None:
    violations = _forbidden_imports(
        BUSINESS_ROOT / "layers" / "output",
        forbidden_prefixes=(
            "business.foundation.models.report_output",
            "business.foundation.models.source",
            "infrastructure.storage.persistence",
        ),
    )

    assert violations == []


def test_analysis_quality_tools_do_not_import_legacy_quality_or_evidence_packages() -> None:
    violations = _forbidden_imports(
        BUSINESS_ROOT / "layers" / "analysis",
        forbidden_prefixes=("business.foundation.models.source", "evidence", "quality", "sources"),
    )

    assert violations == []


def _forbidden_imports(root: Path, *, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    if not root.exists():
        return violations
    for path in root.rglob("*.py"):
        for imported in _imports_for_file(path):
            if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in forbidden_prefixes):
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")
    return violations


def _imports_for_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _matching_forbidden(
    imported_modules: list[str],
    forbidden_prefixes: tuple[str, ...],
) -> list[str]:
    return [
        imported
        for imported in imported_modules
        if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in forbidden_prefixes)
    ]
