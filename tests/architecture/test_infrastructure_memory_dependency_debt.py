from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INFRA_STORAGE_ROOT = PROJECT_ROOT / "infrastructure" / "storage"

# TODO(architecture-p2-memory-port-migration): remove this allowlist after
# infrastructure memory/vector/graph adapters depend on port DTOs instead of
# business memory models.
ALLOWED_BUSINESS_MEMORY_IMPORTS = {
    "infrastructure/storage/graph/ports.py": {"business.memory.graph_memory"},
    "infrastructure/storage/graph/postgres_graph_store.py": {"business.memory.graph_models"},
    "infrastructure/storage/memory/intelligence_vector_index.py": {
        "business.memory.intelligence_models",
    },
    "infrastructure/storage/postgres/memory_repository.py": {
        "business.memory.intelligence_builder",
        "business.memory.intelligence_models",
    },
}


def test_infrastructure_business_memory_imports_are_explicit_debt() -> None:
    unexpected: list[str] = []
    missing_expected: list[str] = []
    seen: dict[str, set[str]] = {}

    for path in INFRA_STORAGE_ROOT.rglob("*.py"):
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        imports = {
            imported
            for imported in _imports_for_file(path)
            if imported == "business.memory" or imported.startswith("business.memory.")
        }
        if not imports:
            continue
        seen[relative_path] = imports
        allowed = ALLOWED_BUSINESS_MEMORY_IMPORTS.get(relative_path, set())
        for imported in sorted(imports - allowed):
            unexpected.append(f"{relative_path}: {imported}")

    for relative_path, imports in ALLOWED_BUSINESS_MEMORY_IMPORTS.items():
        missing = imports - seen.get(relative_path, set())
        for imported in sorted(missing):
            missing_expected.append(f"{relative_path}: {imported}")

    assert unexpected == []
    assert missing_expected == []


def _imports_for_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules
