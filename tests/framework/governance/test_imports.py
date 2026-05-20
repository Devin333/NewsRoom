from __future__ import annotations


def test_governance_public_imports() -> None:
    from framework.governance import (
        AuditEvent,
        CostPolicy,
        ExecutionPolicy,
        GovernanceFinding,
        InMemoryAuditStore,
        MappingSecretProvider,
        PermissionChecker,
        QualityGate,
        ResourcePolicy,
        RetryPolicy,
        SafetyPolicy,
        SandboxGuard,
        SecurityRedactor,
        TimeoutPolicy,
    )

    assert AuditEvent
    assert CostPolicy
    assert ExecutionPolicy
    assert GovernanceFinding
    assert InMemoryAuditStore
    assert MappingSecretProvider
    assert PermissionChecker
    assert QualityGate
    assert ResourcePolicy
    assert RetryPolicy
    assert SafetyPolicy
    assert SandboxGuard
    assert SecurityRedactor
    assert TimeoutPolicy


def test_core_governance_compat_imports() -> None:
    from core.framework.governance import ExecutionPolicy

    assert ExecutionPolicy().can_execute({}) == (True, None)
