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


def test_reader_repair_memory_side_effect_is_atomic_and_composition_owned() -> None:
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
    failure_handler_path = (
        PROJECT_ROOT
        / "infrastructure"
        / "research"
        / "reader_repair_failure_diagnostic_side_effect.py"
    )
    failure_port_path = (
        PROJECT_ROOT
        / "business"
        / "research"
        / "ports"
        / "reader_repair_failure_diagnostic.py"
    )
    handler_source = handler_path.read_text(encoding="utf-8")
    port_source = port_path.read_text(encoding="utf-8")
    adapter_source = adapter_path.read_text(encoding="utf-8")
    factory_source = factory_path.read_text(encoding="utf-8")
    failure_handler_source = failure_handler_path.read_text(encoding="utf-8")
    failure_port_source = failure_port_path.read_text(encoding="utf-8")

    assert "class ReaderRepairMemoryCommitPort" in port_source
    assert "class ReaderRepairMemorySideEffectHandler" in handler_source
    assert "class PostgresReaderRepairMemoryCommitPort" in adapter_source
    assert "build_reader_repair_memory_commit_port_from_env" in factory_source
    assert "class ReaderRepairFailureDiagnosticCommitPort" in failure_port_source
    assert (
        "class ReaderRepairFailureDiagnosticSideEffectHandler"
        in failure_handler_source
    )
    assert "class PostgresReaderRepairFailureDiagnosticCommitPort" in adapter_source
    assert (
        "build_reader_repair_failure_diagnostic_commit_port_from_env"
        in factory_source
    )
    assert ".write_case(" not in handler_source
    assert ".write_strategy(" not in handler_source
    assert ".write_case(" not in failure_handler_source
    assert ".write_strategy(" not in failure_handler_source
    assert "business.research.reader_repair.repair_memory" not in imported_modules(
        handler_path
    )

    memory_module = (
        "infrastructure.research.reader_repair_memory_side_effect"
    )
    failure_module = (
        "infrastructure.research.reader_repair_failure_diagnostic_side_effect"
    )
    business_application_path = (
        PROJECT_ROOT
        / "business"
        / "research"
        / "application"
        / "reader_repair_runtime.py"
    )
    composition_path = PROJECT_ROOT / "interfaces" / "composition" / "research.py"
    legacy_application_path = (
        PROJECT_ROOT
        / "business"
        / "research"
        / "application"
        / "single_paper_runtime.py"
    )
    assert memory_module not in imported_modules(business_application_path)
    assert failure_module not in imported_modules(business_application_path)
    assert memory_module in imported_modules(composition_path)
    assert failure_module in imported_modules(composition_path)
    assert memory_module not in imported_modules(legacy_application_path)
    assert failure_module not in imported_modules(legacy_application_path)
    composition_source = composition_path.read_text(encoding="utf-8")
    assert "ReaderRepairMemorySideEffectHandler" in composition_source
    assert "ReaderRepairFailureDiagnosticSideEffectHandler" in composition_source
    application_source = business_application_path.read_text(encoding="utf-8")
    assert ".write_case(" not in application_source
    assert ".write_strategy(" not in application_source


def test_reader_repair_execution_v2_contract_is_candidate_only_and_inactive() -> None:
    research_root = PROJECT_ROOT / "business" / "research"
    contract_paths = (
        research_root / "reader_repair" / "application.py",
        research_root / "graphs" / "reader_repair_contracts.py",
        research_root / "graphs" / "reader_repair_execution_gates.py",
        research_root / "graphs" / "reader_repair_execution_workers.py",
    )
    forbidden_prefixes = (
        "business.research.ports.artifact_publication",
        "business.research.ports.repair_memory",
        "framework.harness.artifacts",
        "framework.harness.memory",
        "infrastructure",
        "interfaces",
    )

    for path in contract_paths:
        assert path.exists()
        assert not any(
            module == prefix or module.startswith(f"{prefix}.")
            for module in imported_modules(path)
            for prefix in forbidden_prefixes
        )

    production_paths = (
        research_root / "application" / "single_paper_runtime.py",
        PROJECT_ROOT / "interfaces" / "composition" / "research.py",
    )
    inactive_symbols = (
        "build_reader_repair_application_worker_result",
        "build_reader_repair_application_verification_worker_result",
        "build_reader_repair_result_worker_result",
        "build_reader_repair_execution_gate_registry",
    )
    for path in production_paths:
        source = path.read_text(encoding="utf-8")
        assert all(symbol not in source for symbol in inactive_symbols)

    graph_source = (
        research_root / "graphs" / "reader_repair.py"
    ).read_text(encoding="utf-8")
    contract_source = (
        research_root / "graphs" / "reader_repair_contracts.py"
    ).read_text(encoding="utf-8")
    assert 'READER_REPAIR_GRAPH_VERSION = "2"' in contract_source
    assert "READER_REPAIR_APPLICATION_STEP_ID" in graph_source
    assert "HarnessGraphCommittedNodeOutputBinding" in graph_source
