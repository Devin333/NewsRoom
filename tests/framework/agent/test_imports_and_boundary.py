import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = PROJECT_ROOT / "framework" / "agent"


def test_framework_agent_public_imports() -> None:
    from framework.agent import AgentLoop, AgentRunner, AgentSpec, MessageHistory, SubAgentRegistry

    assert AgentLoop is not None
    assert AgentRunner is not None
    assert AgentSpec is not None
    assert MessageHistory is not None
    assert SubAgentRegistry is not None


def test_framework_agent_does_not_import_core_or_business_boundaries() -> None:
    forbidden = (
        "storage",
        "backend",
        "interfaces",
        "workflows",
        "domain",
        "evidence",
        "quality",
    )
    violations: list[str] = []
    for path in AGENT_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imported_modules(tree):
            if any(imported == item or imported.startswith(f"{item}.") for item in forbidden):
                violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {imported}")

    assert violations == []


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules
