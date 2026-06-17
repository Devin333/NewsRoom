from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INFRASTRUCTURE_ROOT = PROJECT_ROOT / "infrastructure"

# TODO(architecture-p2-memory-port-migration): remove these exceptions when
# infrastructure memory/vector/graph adapters use storage-facing port DTOs.
ALLOWED_BUSINESS_MEMORY_IMPORTS = {
    "infrastructure/storage/graph/postgres_graph_store.py": {"business.memory.graph_models"},
    "infrastructure/storage/memory/intelligence_vector_index.py": {
        "business.memory.intelligence_models",
    },
    "infrastructure/storage/postgres/memory_repository.py": {
        "business.memory.intelligence_builder",
        "business.memory.intelligence_models",
    },
    # Paper-chunk storage adapters persist the PaperChunk domain DTO directly,
    # same pattern as the memory adapters above (P2: migrate to storage-facing DTOs).
    "infrastructure/storage/postgres/paper_chunk_repository.py": {
        "business.research.document.models",
    },
    "infrastructure/storage/vector/paper_chunk_store.py": {
        "business.research.document.models",
    },
}


def test_infrastructure_does_not_import_business_or_interfaces() -> None:
    violations: list[str] = []
    for path in INFRASTRUCTURE_ROOT.rglob("*.py"):
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        allowed_imports = ALLOWED_BUSINESS_MEMORY_IMPORTS.get(relative_path, set())
        for imported in _imports_for_file(path):
            if imported in {"business", "interfaces"} or imported.startswith(("business.", "interfaces.")):
                if imported not in allowed_imports:
                    violations.append(f"{relative_path}: {imported}")

    assert violations == []


def _imports_for_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules
