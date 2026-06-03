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


def test_business_has_no_direct_legacy_domain_or_source_imports() -> None:
    violations = _forbidden_imports(
        BUSINESS_ROOT,
        forbidden_prefixes=(
            "domain",
            "sources",
            "workflows",
            "evidence",
            "quality",
            "storage",
            "interfaces",
        ),
    )

    assert violations == []


def test_business_has_no_runtime_legacy_source_import_adapters() -> None:
    needles = (
        'import_module("domain',
        "import_module('domain",
        'import_module("sources',
        "import_module('sources",
    )
    violations = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()}: {needle}"
        for path in BUSINESS_ROOT.rglob("*.py")
        for needle in needles
        if needle in path.read_text(encoding="utf-8")
    ]

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
    violations = _matching_forbidden(
        imported_modules,
        ("infrastructure.external.sources",),
    )

    assert violations == []


def test_signal_source_config_uses_business_fetch_policy_boundary() -> None:
    imported_modules = _imports_for_file(BUSINESS_ROOT / "layers" / "signal" / "source_config.py")
    violations = _matching_forbidden(
        imported_modules,
        ("infrastructure.external.sources",),
    )

    assert violations == []


def test_signal_source_health_checker_uses_probe_adapter_boundary() -> None:
    imported_modules = _imports_for_file(BUSINESS_ROOT / "layers" / "signal" / "source_health" / "checker.py")
    violations = _matching_forbidden(
        imported_modules,
        ("infrastructure.external.sources",),
    )

    assert violations == []


def test_signal_source_tools_use_runtime_adapter_boundary() -> None:
    imported_modules = _imports_for_file(BUSINESS_ROOT / "layers" / "signal" / "tools.py")
    violations = _matching_forbidden(
        imported_modules,
        ("infrastructure.external.sources",),
    )

    assert violations == []


def test_signal_pipeline_uses_records_facade_for_source_processing() -> None:
    pipeline_imports = _imports_for_file(BUSINESS_ROOT / "layers" / "signal" / "pipeline.py")
    assert _matching_forbidden(
        pipeline_imports,
        ("business.foundation.models.source", "business.layers.signal.source_processing"),
    ) == []

    record_imports = _imports_for_file(BUSINESS_ROOT / "layers" / "signal" / "records.py")
    assert "business.foundation.models.source" in record_imports
    assert any(imported.startswith("business.layers.signal.source_processing") for imported in record_imports)


def test_relation_lineage_boundary_does_not_import_storage_lineage() -> None:
    violations = _forbidden_imports(
        BUSINESS_ROOT / "layers" / "relation",
        forbidden_prefixes=("infrastructure.storage.lineage",),
    )

    assert violations == []


def test_output_report_tools_do_not_import_storage_or_domain_report_models() -> None:
    violations = _forbidden_imports(
        BUSINESS_ROOT / "layers" / "output",
        forbidden_prefixes=("business.foundation.models.report_output", "business.foundation.models.source", "infrastructure.storage.repository"),
    )

    assert violations == []


def test_analysis_quality_tools_do_not_import_legacy_quality_or_evidence_packages() -> None:
    violations = _forbidden_imports(
        BUSINESS_ROOT / "layers" / "analysis",
        forbidden_prefixes=("business.foundation.models.source", "evidence", "quality", "sources"),
    )

    assert violations == []


def test_business_boards_do_not_import_concrete_storage() -> None:
    violations = _forbidden_imports(
        BUSINESS_ROOT / "boards",
        forbidden_prefixes=(
            "infrastructure.storage.postgres",
            "infrastructure.storage.qdrant",
            "infrastructure.storage.redis",
            "infrastructure.storage.postgres",
            "infrastructure.storage.qdrant",
            "infrastructure.storage.redis",
        ),
    )

    assert violations == []


def test_productized_workflow_steps_delegate_business_logic_to_productized_services() -> None:
    imported_modules = _imports_for_file(BUSINESS_ROOT / "boards" / "_productized_steps.py")

    assert "business.boards.productized.steps" in imported_modules
    assert "business.boards.productized.workflow" in imported_modules
    assert "business.layers.signal" not in imported_modules
    assert "business.foundation.subscription" not in imported_modules


def test_business_boards_use_policy_experiment_application_api() -> None:
    violations = _attribute_calls(
        BUSINESS_ROOT / "boards",
        forbidden_names=("apply_approved_overrides",),
    )

    assert violations == []


def test_daily_agent_registry_stays_fixture_free() -> None:
    registry_path = (
        BUSINESS_ROOT
        / "boards"
        / "cross_board"
        / "workflows"
        / "daily_intelligence"
        / "agent_registry.py"
    )
    imported_modules = _imports_for_file(registry_path)
    defined_functions = _function_defs_for_file(registry_path)

    assert (
        "business.boards.cross_board.workflows.daily_intelligence.agent_fixtures"
        not in imported_modules
    )
    assert [
        name
        for name in defined_functions
        if "fake" in name or "fixture" in name
    ] == []


def test_agentic_daily_runner_uses_explicit_fixture_runner_factory() -> None:
    runner_path = (
        BUSINESS_ROOT
        / "boards"
        / "cross_board"
        / "workflows"
        / "daily_intelligence"
        / "runner_agentic.py"
    )
    imported_modules = _imports_for_file(runner_path)

    assert (
        "business.boards.cross_board.workflows.daily_intelligence.agent_fixtures"
        not in imported_modules
    )
    assert (
        "business.boards.cross_board.workflows.daily_intelligence.agent_runner_factory"
        in imported_modules
    )


def test_board_radar_tools_do_not_import_legacy_source_modules() -> None:
    violations: list[str] = []
    for path in (
        BUSINESS_ROOT / "boards" / "paper_radar" / "tools.py",
        BUSINESS_ROOT / "boards" / "project_radar" / "tools.py",
    ):
        imported_modules = _imports_for_file(path)
        for imported in _matching_forbidden(imported_modules, ("business.foundation.models.source", "infrastructure.external.sources")):
            violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")

    assert violations == []


def _forbidden_imports(root: Path, *, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for path in root.rglob("*.py"):
        for imported in _imports_for_file(path):
            if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in forbidden_prefixes):
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")
    return violations


def _imports_for_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return _imported_modules(tree)


def _function_defs_for_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _attribute_calls(root: Path, *, forbidden_names: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in forbidden_names:
                violations.append(
                    f"{path.relative_to(PROJECT_ROOT).as_posix()}:{node.lineno}: {node.attr}"
                )
    return violations


def _matching_forbidden(
    imported_modules: list[str],
    forbidden_prefixes: tuple[str, ...],
) -> list[str]:
    return [
        imported
        for imported in imported_modules
        if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in forbidden_prefixes)
    ]


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules
