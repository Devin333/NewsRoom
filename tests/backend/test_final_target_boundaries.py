from __future__ import annotations

import ast
from pathlib import Path


def test_final_target_dependency_boundaries() -> None:
    root = Path(__file__).resolve().parents[2]

    foundation_imports = _imports_under(root / "backend" / "foundation")
    assert not any(
        name.startswith("backend.layers")
        or name.startswith("backend.boards")
        or name.startswith("infrastructure")
        for name in foundation_imports
    )

    layer_imports = _imports_under(root / "backend" / "layers")
    assert not any(
        name.startswith("backend.boards")
        or name.startswith("infrastructure.storage.postgres")
        or name.startswith("infrastructure.storage.redis")
        or name.startswith("infrastructure.storage.vector")
        for name in layer_imports
    )

    research_imports = _imports_under(root / "backend" / "research")
    assert not any(
        name.startswith("backend.boards")
        or name.startswith("interfaces")
        or name.startswith("infrastructure")
        for name in research_imports
    )

    assert not (root / "backend" / "boards").exists()


def _imports_under(path: Path) -> set[str]:
    imports: set[str] = set()
    for file_path in path.rglob("*.py"):
        if "__pycache__" in file_path.parts:
            continue
        module = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports
