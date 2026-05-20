from __future__ import annotations

import pytest

from framework.governance.security import (
    EnvironmentSecretProvider,
    MappingSecretProvider,
    PermissionChecker,
    SandboxGuard,
    SandboxPolicy,
    SecurityRedactor,
)


def test_secret_providers_get_and_require_values() -> None:
    mapping = MappingSecretProvider({"API_TOKEN": "value"})
    env = EnvironmentSecretProvider({"PASSWORD": "secret"})

    assert mapping.get("API_TOKEN") == "value"
    assert mapping.require("API_TOKEN") == "value"
    assert env.require("PASSWORD") == "secret"
    with pytest.raises(KeyError):
        mapping.require("MISSING")


def test_security_redactor_uses_shared_redaction_defaults() -> None:
    redactor = SecurityRedactor()

    assert redactor.redact_mapping({"api_key": "secret"}) == {"api_key": "***REDACTED***"}
    assert redactor.redact_text("Bearer abcdefghijkl") == "***REDACTED***"


def test_permission_checker_supports_wildcards() -> None:
    checker = PermissionChecker({"alice": {"read:*"}, "root": {"*"}})

    assert checker.can("alice", "read", "artifact")
    assert not checker.can("alice", "write", "artifact")
    assert checker.can("root", "delete", "anything")
    with pytest.raises(PermissionError):
        checker.require("alice", "write", "artifact")


def test_sandbox_guard_reports_denied_operations() -> None:
    guard = SandboxGuard(SandboxPolicy(network=False, filesystem_write=True, subprocess=False))

    assert guard.check("network") == ["network access is not allowed"]
    assert guard.check({"type": "filesystem_write"}) == []
    assert guard.check({"kind": "subprocess"}) == ["subprocess execution is not allowed"]
