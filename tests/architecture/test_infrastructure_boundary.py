from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INFRASTRUCTURE_ROOT = PROJECT_ROOT / "infrastructure"

# TODO(architecture-p2-memory-port-migration): remove these exceptions when
# infrastructure memory/vector/graph adapters use storage-facing port DTOs.
ALLOWED_BUSINESS_IMPORTS = {
    "infrastructure/storage/graph/postgres_graph_store.py": {"business.memory.graph_models"},
    "infrastructure/storage/memory/intelligence_vector_index.py": {
        "business.memory.intelligence_models",
    },
    "infrastructure/storage/postgres/memory_repository.py": {
        "business.memory.intelligence_builder",
        "business.memory.intelligence_models",
    },
    "infrastructure/storage/postgres/repository.py": {
        "business.foundation.models.source_error_normalization",
    },
    "infrastructure/external/sources/url_utils.py": {
        "business.foundation.primitives.source_ref",
    },
    "infrastructure/external/sources/errors/taxonomy.py": {
        "business.layers.signal.source_processing.error_taxonomy",
    },
    "infrastructure/research/document_compiler.py": {
        "business.research.domain.common",
        "business.research.domain.document",
        "business.research.domain.paper",
        "business.research.ports.document_compiler",
        "business.research.ports.document_parser",
    },
    "infrastructure/research/artifact_publication.py": {
        "business.research.ports.artifact_publication",
    },
    "infrastructure/research/artifact_port.py": {
        "business.research.ports.artifact_publication",
    },
    "infrastructure/research/filesystem_run_store.py": {
        "business.research.domain.run_disposition",
        "business.research.ports.run_store",
    },
    "infrastructure/research/github_repository.py": {
        "business.research.domain.code_repository",
    },
    "infrastructure/research/reader_repair_memory_side_effect.py": {
        "business.research.ports.repair_memory",
    },
    "infrastructure/research/candidate_worker.py": {
        "business.research.ports.reader_repair_candidate",
    },
    "infrastructure/research/source_provider.py": {
        "business.research.domain.paper",
    },
}

SOURCE_ADAPTER_BUSINESS_IMPORTS = {
    "infrastructure/external/sources/url_utils.py": {
        "business.foundation.primitives.source_ref",
    },
    "infrastructure/external/sources/errors/taxonomy.py": {
        "business.layers.signal.source_processing.error_taxonomy",
    },
}

SOURCE_STORAGE_BUSINESS_IMPORTS = {
    "infrastructure/storage/postgres/repository.py": {
        "business.foundation.models.source_error_normalization",
    },
}

RESEARCH_ADAPTER_BUSINESS_IMPORTS = {
    "infrastructure/research/artifact_port.py": {
        "business.research.ports.artifact_publication",
    },
    "infrastructure/research/artifact_publication.py": {
        "business.research.ports.artifact_publication",
    },
    "infrastructure/research/document_compiler.py": {
        "business.research.domain.common",
        "business.research.domain.document",
        "business.research.domain.paper",
        "business.research.ports.document_compiler",
        "business.research.ports.document_parser",
    },
    "infrastructure/research/filesystem_run_store.py": {
        "business.research.domain.run_disposition",
        "business.research.ports.run_store",
    },
    "infrastructure/research/github_repository.py": {
        "business.research.domain.code_repository",
    },
    "infrastructure/research/reader_repair_memory_side_effect.py": {
        "business.research.ports.repair_memory",
    },
    "infrastructure/research/candidate_worker.py": {
        "business.research.ports.reader_repair_candidate",
    },
    "infrastructure/research/source_provider.py": {
        "business.research.domain.paper",
    },
}


def test_infrastructure_does_not_import_business_or_interfaces() -> None:
    violations: list[str] = []
    for path in INFRASTRUCTURE_ROOT.rglob("*.py"):
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        allowed_imports = ALLOWED_BUSINESS_IMPORTS.get(relative_path, set())
        for imported in _imports_for_file(path):
            if imported in {"business", "interfaces"} or imported.startswith(("business.", "interfaces.")):
                if imported not in allowed_imports:
                    violations.append(f"{relative_path}: {imported}")

    assert violations == []


def test_source_adapter_business_imports_are_exact_contract_exceptions() -> None:
    actual = {
        path: imports
        for path, imports in ALLOWED_BUSINESS_IMPORTS.items()
        if path.startswith("infrastructure/external/sources/")
    }

    assert actual == SOURCE_ADAPTER_BUSINESS_IMPORTS


def test_source_storage_business_imports_are_exact_contract_exceptions() -> None:
    actual = {
        path: imports
        for path, imports in ALLOWED_BUSINESS_IMPORTS.items()
        if path in SOURCE_STORAGE_BUSINESS_IMPORTS
    }

    assert actual == SOURCE_STORAGE_BUSINESS_IMPORTS


def test_research_adapter_business_imports_are_exact_contract_exceptions() -> None:
    actual: dict[str, set[str]] = {}
    for path in (INFRASTRUCTURE_ROOT / "research").rglob("*.py"):
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        business_imports = {
            imported
            for imported in _imports_for_file(path)
            if imported == "business" or imported.startswith("business.")
        }
        if business_imports:
            actual[relative_path] = business_imports

    assert actual == RESEARCH_ADAPTER_BUSINESS_IMPORTS
    assert all(
        imported.startswith(
            ("business.research.domain.", "business.research.ports.")
        )
        for imports in actual.values()
        for imported in imports
    )


def _imports_for_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules
