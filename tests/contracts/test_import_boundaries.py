from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK_ROOT = PROJECT_ROOT / "framework"
BUSINESS_ROOT = PROJECT_ROOT / "backend"
INTERFACES_ROOT = PROJECT_ROOT / "interfaces"
FRAMEWORK_AGENT_SESSION_ROOT = FRAMEWORK_ROOT / "agent" / "session"

FRAMEWORK_FORBIDDEN_PREFIXES = (
    "backend",
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
    "backend.boards",
)


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


def test_business_memory_ingestion_boundary_does_not_depend_on_legacy_report_or_storage_models() -> None:
    imports = _imports_for_file(BUSINESS_ROOT / "layers" / "memory" / "ingestion.py")

    assert _matching_forbidden(
        imports,
        ("backend.foundation.models.report_output", "evidence", "infrastructure.storage.vector"),
    ) == []


def test_graph_memory_port_has_single_canonical_definition() -> None:
    from backend.memory.graph_memory import GraphMemoryPort as BusinessGraphMemoryPort
    from backend.memory.graph_memory import GraphMemoryPort as InfrastructureGraphMemoryPort

    assert InfrastructureGraphMemoryPort is BusinessGraphMemoryPort


def test_interface_entrypoints_do_not_reach_old_board_flow() -> None:
    violations = _forbidden_imports(
        INTERFACES_ROOT,
        forbidden_prefixes=INTERFACE_FORBIDDEN_FLOW_PREFIXES,
    )

    assert violations == []


def test_source_application_service_uses_source_policy_boundary() -> None:
    imports = _imports_for_file(INTERFACES_ROOT / "services" / "source_service.py")

    assert "infrastructure.external.sources" in imports
    assert "backend.foundation.registry.source_registry" in imports
    assert "backend.layers.signal.source_config" in imports
    assert _matching_forbidden(
        imports,
        ("domain.sources", "sources", "infrastructure.storage.postgres", "backend.boards"),
    ) == []


def test_worker_application_service_uses_research_neutral_handlers() -> None:
    imports = _imports_for_file(INTERFACES_ROOT / "services" / "worker_service.py")

    assert "backend.layers.output.worker_handlers" in imports
    assert "backend.layers.signal.worker_handlers" in imports
    assert "backend.boards" not in imports
    assert "backend.workers" not in imports


def test_api_app_uses_run_report_projection_boundary() -> None:
    app_path = INTERFACES_ROOT / "api" / "app.py"
    imports = _imports_for_file(app_path)
    text = app_path.read_text(encoding="utf-8")

    assert "interfaces.services.run_report_projection" in imports
    assert "interfaces.services.daily_interface_projection" not in imports
    assert "project_run_output_for_interface" not in text


def test_diagnostic_service_uses_business_source_config_boundary() -> None:
    imports = _imports_for_file(INTERFACES_ROOT / "services" / "diagnose_service.py")

    assert "backend.layers.signal.source_config" in imports
    assert _matching_forbidden(imports, ("domain.sources", "sources")) == []


def test_framework_agent_session_has_no_paper_business_terms_or_imports() -> None:
    violations = _forbidden_imports(
        FRAMEWORK_AGENT_SESSION_ROOT,
        forbidden_prefixes=("backend", "interfaces", "paper_radar"),
    )
    forbidden_terms = ("PublicPaper", "taskRefs", "methodRefs", "PaperRadar")
    term_violations = []
    for path in sorted(FRAMEWORK_AGENT_SESSION_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            if term in text:
                term_violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {term}")

    assert violations == []
    assert term_violations == []


def _forbidden_imports(
    root: Path,
    *,
    forbidden_prefixes: tuple[str, ...],
) -> list[str]:
    violations: list[str] = []
    if not root.exists():
        return violations
    for path in sorted(root.rglob("*.py")):
        imported_modules = _imports_for_file(path)
        for imported in _matching_forbidden(imported_modules, forbidden_prefixes):
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
