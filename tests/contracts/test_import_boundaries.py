from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK_ROOT = PROJECT_ROOT / "framework"
BUSINESS_ROOT = PROJECT_ROOT / "business"
INTERFACES_ROOT = PROJECT_ROOT / "interfaces"

FRAMEWORK_FORBIDDEN_PREFIXES = (
    "business",
    "domain",
    "evidence",
    "interfaces",
    "quality",
    "sources",
    "workflows",
)

BUSINESS_FORBIDDEN_CONCRETE_CLIENTS = (
    "aiohttp",
    "httpx",
    "openai",
    "psycopg",
    "qdrant_client",
    "redis",
    "requests",
)

INTERFACE_FORBIDDEN_FLOW_PREFIXES = (
    "framework.workflow.compiler",
    "framework.workflow.runtime.executor",
    "framework.workflow.runtime.runner",
    "evidence",
    "quality",
    "sources",
    "storage",
    "business.boards.cross_board.workflows.daily_intelligence",
)

# TODO(boundary-migration): narrow this list as legacy interfaces are converted to
# board/report/insight services. New board interfaces should not be added here.
LEGACY_INTERFACE_ENTRYPOINTS = {
    "interfaces/api/routers/memory.py",
    "interfaces/api/routers/reports.py",
    "interfaces/api/routers/runs.py",
    "interfaces/api/routers/schedules.py",
    "interfaces/api/routers/sources.py",
    "interfaces/api/routers/storage.py",
    "interfaces/api/routers/workers.py",
    "interfaces/cli/news.py",
    "interfaces/mcp/server.py",
    "interfaces/services/approval_service.py",
    "interfaces/services/diagnose_service.py",
    "interfaces/services/entity_service.py",
    "interfaces/services/mcp_service.py",
    "interfaces/services/memory_service.py",
    "interfaces/services/report_service.py",
    "interfaces/services/run_inspection_service.py",
    "interfaces/services/run_operation_service.py",
    "interfaces/services/run_service.py",
    "interfaces/services/schedule_service.py",
    "interfaces/services/storage_service.py",
    "interfaces/services/subscription_service.py",
    "interfaces/services/worker_service.py",
}


def test_framework_has_no_business_or_interface_imports() -> None:
    violations = _forbidden_imports(
        FRAMEWORK_ROOT,
        forbidden_prefixes=FRAMEWORK_FORBIDDEN_PREFIXES,
    )

    assert violations == []


def test_business_has_no_concrete_external_client_imports() -> None:
    violations = _forbidden_imports(
        BUSINESS_ROOT,
        forbidden_prefixes=BUSINESS_FORBIDDEN_CONCRETE_CLIENTS,
    )

    assert violations == []


def test_business_memory_ingestion_does_not_depend_on_legacy_report_or_storage_models() -> None:
    imports = _imports_for_file(BUSINESS_ROOT / "layers" / "output" / "memory_ingestion.py")

    assert _matching_forbidden(imports, ("business.foundation.models.report_output", "evidence", "infrastructure.storage.vector")) == []


def test_graph_memory_port_has_single_canonical_definition() -> None:
    from business.memory.graph_memory import GraphMemoryPort as BusinessGraphMemoryPort
    from infrastructure.storage.graph.ports import GraphMemoryPort as InfrastructureGraphMemoryPort

    assert InfrastructureGraphMemoryPort is BusinessGraphMemoryPort


def test_new_board_interfaces_do_not_bypass_board_services() -> None:
    violations = _forbidden_imports(
        INTERFACES_ROOT,
        forbidden_prefixes=INTERFACE_FORBIDDEN_FLOW_PREFIXES,
        allowed_relative_paths=LEGACY_INTERFACE_ENTRYPOINTS,
    )

    assert violations == []


def test_board_api_calls_interface_board_service_only() -> None:
    board_api = INTERFACES_ROOT / "api" / "routers" / "boards.py"
    board_service = INTERFACES_ROOT / "services" / "board_service.py"

    api_imports = _imports_for_file(board_api)
    service_imports = _imports_for_file(board_service)

    assert _matching_forbidden(api_imports, INTERFACE_FORBIDDEN_FLOW_PREFIXES) == []
    assert _matching_forbidden(service_imports, INTERFACE_FORBIDDEN_FLOW_PREFIXES) == []
    assert "interfaces.api.deps" in api_imports
    assert any(imported == "business.boards" for imported in service_imports)


def test_source_application_service_uses_infrastructure_source_adapters() -> None:
    imports = _imports_for_file(INTERFACES_ROOT / "services" / "source_service.py")

    assert "infrastructure.external.sources" in imports
    assert "business.foundation.registry.source_registry" in imports
    assert "business.layers.signal.source_config" in imports
    assert _matching_forbidden(imports, ("domain.sources", "sources", "infrastructure.storage.postgres", "business.boards.cross_board.workflows.daily_intelligence")) == []


def test_cross_board_daily_source_config_uses_infrastructure_source_adapters() -> None:
    imports = _imports_for_file(
        BUSINESS_ROOT / "boards" / "cross_board" / "workflows" / "daily_intelligence" / "source_config.py"
    )

    assert "infrastructure.external.sources" in imports
    assert "business.layers.signal.source_config" in imports
    assert _matching_forbidden(imports, ("domain.sources", "sources")) == []


def test_cross_board_daily_source_processing_uses_business_signal_layer() -> None:
    imports = _imports_for_file(
        BUSINESS_ROOT / "boards" / "cross_board" / "workflows" / "daily_intelligence" / "source_processing.py"
    )

    assert "business.layers.signal.source_processing" in imports
    assert _matching_forbidden(
        imports,
        (
            "evidence",
            "sources",
            "domain.sources",
        ),
    ) == []


def test_worker_application_service_uses_target_business_handler_modules() -> None:
    imports = _imports_for_file(INTERFACES_ROOT / "services" / "worker_service.py")

    assert "business.boards.cross_board.worker_handlers" in imports
    assert "business.layers.output.worker_handlers" in imports
    assert "business.layers.signal.worker_handlers" in imports
    assert "business.workers" not in imports


def test_interface_daily_profile_enums_come_from_cross_board_business_layer() -> None:
    checked_paths = [
        INTERFACES_ROOT / "cli" / "news.py",
        INTERFACES_ROOT / "services" / "mcp_service.py",
        INTERFACES_ROOT / "services" / "report_service.py",
        INTERFACES_ROOT / "services" / "run_service.py",
    ]
    for path in checked_paths:
        imports = _imports_for_file(path)
        assert "business.boards.cross_board.workflows.daily_intelligence.profiles" not in imports

    assert "business.boards.cross_board.profiles" in _imports_for_file(
        INTERFACES_ROOT / "cli" / "news.py"
    )
    assert "business.boards.cross_board.profiles" in _imports_for_file(
        INTERFACES_ROOT / "services" / "mcp_service.py"
    )
    assert "business.boards.cross_board.profiles" in _imports_for_file(
        INTERFACES_ROOT / "services" / "report_service.py"
    )
    assert "business.boards.cross_board.profiles" in _imports_for_file(
        INTERFACES_ROOT / "services" / "run_service.py"
    )


def test_diagnostic_service_uses_infrastructure_source_adapters() -> None:
    imports = _imports_for_file(INTERFACES_ROOT / "services" / "diagnose_service.py")

    assert "business.layers.signal.source_config" in imports
    assert _matching_forbidden(imports, ("domain.sources", "sources")) == []


def _forbidden_imports(
    root: Path,
    *,
    forbidden_prefixes: tuple[str, ...],
    allowed_relative_paths: set[str] | None = None,
) -> list[str]:
    allowed_relative_paths = allowed_relative_paths or set()
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        if relative_path in allowed_relative_paths:
            continue
        imported_modules = _imports_for_file(path)
        for imported in _matching_forbidden(imported_modules, forbidden_prefixes):
            violations.append(f"{relative_path}: {imported}")
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
