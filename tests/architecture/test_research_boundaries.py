from __future__ import annotations

from tests.architecture._helpers import (
    PROJECT_ROOT,
    forbidden_imports,
    imported_modules,
)


def test_research_does_not_depend_on_legacy_or_interface_layers() -> None:
    violations = forbidden_imports(
        PROJECT_ROOT / "business" / "research",
        (
            "business.boards.paper_radar",
            "business.boards",
            "interfaces",
            "infrastructure",
            "frontend",
            "apps",
        ),
    )

    assert violations == []


def test_research_rag_evaluation_does_not_import_cli_entrypoints() -> None:
    violations = forbidden_imports(
        PROJECT_ROOT / "business" / "research" / "rag" / "evaluation",
        ("business.research.rag.cli",),
    )

    assert violations == []


def test_research_graphs_do_not_depend_on_legacy_orchestration() -> None:
    violations = forbidden_imports(
        PROJECT_ROOT / "business" / "research" / "graphs",
        (
            "business.research.workflows",
            "framework.harness.workflow",
            "framework.workflow",
        ),
    )

    assert violations == []


def test_legacy_research_workflow_surface_is_declaration_only() -> None:
    legacy_root = PROJECT_ROOT / "business" / "research" / "workflows"
    assert {path.name for path in legacy_root.glob("*.py")} == {
        "__init__.py",
        "paper_analysis_workflow.py",
    }

    package_source = (legacy_root / "__init__.py").read_text(encoding="utf-8")
    assert "from business.research" not in package_source
    assert "__all__: list[str] = []" in package_source

    allowed = "business.research.workflows.paper_analysis_workflow"
    violations = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()}: {module}"
        for root_name in ("business", "interfaces")
        for path in (PROJECT_ROOT / root_name).rglob("*.py")
        for module in imported_modules(path)
        if module.startswith("business.research.workflows")
        and module != allowed
    ]

    assert violations == []


def test_reader_repair_subagent_declarations_are_graph_owned() -> None:
    reader_repair_root = PROJECT_ROOT / "business" / "research" / "reader_repair"
    graph_owner = (
        PROJECT_ROOT
        / "business"
        / "research"
        / "graphs"
        / "reader_repair.py"
    )
    expected_owner = "business.research.graphs.reader_repair"

    assert not (reader_repair_root / "workflow.py").exists()
    assert graph_owner.exists()
    assert "def build_reader_repair_subagent_specs" in graph_owner.read_text(
        encoding="utf-8"
    )
    for caller in (
        reader_repair_root / "__init__.py",
        reader_repair_root / "repair_service.py",
    ):
        modules = imported_modules(caller)
        assert expected_owner in modules
        assert not any(module.endswith("reader_repair.workflow") for module in modules)


def test_reader_repair_memory_side_effect_is_atomic_and_inactive() -> None:
    handler_path = (
        PROJECT_ROOT
        / "infrastructure"
        / "research"
        / "reader_repair_memory_side_effect.py"
    )
    port_path = (
        PROJECT_ROOT
        / "business"
        / "research"
        / "ports"
        / "repair_memory.py"
    )
    adapter_path = (
        PROJECT_ROOT
        / "interfaces"
        / "services"
        / "reader_repair_memory.py"
    )
    factory_path = (
        PROJECT_ROOT
        / "interfaces"
        / "services"
        / "reader_repair_factory.py"
    )
    handler_source = handler_path.read_text(encoding="utf-8")
    port_source = port_path.read_text(encoding="utf-8")
    adapter_source = adapter_path.read_text(encoding="utf-8")
    factory_source = factory_path.read_text(encoding="utf-8")

    assert "class ReaderRepairMemoryCommitPort" in port_source
    assert "class ReaderRepairMemorySideEffectHandler" in handler_source
    assert "class PostgresReaderRepairMemoryCommitPort" in adapter_source
    assert "build_reader_repair_memory_commit_port_from_env" in factory_source
    assert ".write_case(" not in handler_source
    assert ".write_strategy(" not in handler_source
    assert "business.research.reader_repair.repair_memory" not in imported_modules(
        handler_path
    )

    inactive_module = (
        "infrastructure.research.reader_repair_memory_side_effect"
    )
    production_paths = (
        PROJECT_ROOT / "business" / "research" / "application" / "single_paper_runtime.py",
        PROJECT_ROOT / "interfaces" / "composition" / "research.py",
    )
    assert all(
        inactive_module not in imported_modules(path)
        for path in production_paths
    )
    assert all(
        "ReaderRepairMemorySideEffectHandler" not in path.read_text(encoding="utf-8")
        for path in production_paths
    )
