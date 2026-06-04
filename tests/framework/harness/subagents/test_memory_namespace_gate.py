from __future__ import annotations

from framework.harness import SubAgentMemoryNamespaceGate, fake_subagent_spec


def test_subagent_cannot_access_unauthorized_memory_namespace() -> None:
    spec = fake_subagent_spec(allowed_memory_namespaces=("research.public",))
    result = SubAgentMemoryNamespaceGate().evaluate(spec, ("research.private",))

    assert result.passed is False
    assert result.details["denied"] == ["research.private"]


def test_subagent_authorized_memory_namespace_passes() -> None:
    spec = fake_subagent_spec(allowed_memory_namespaces=("research.public",))
    result = SubAgentMemoryNamespaceGate().evaluate(spec, ("research.public",))

    assert result.passed is True
