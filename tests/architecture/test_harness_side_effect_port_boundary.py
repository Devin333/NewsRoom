from __future__ import annotations

from dataclasses import fields

from framework.harness.mcp.policy import MCPApprovalStatus, MCPToolRequest
from framework.harness.memory.ports import MemoryPort, MemoryWriteStatus
from framework.harness.ports import HarnessMemoryPort
from framework.harness.side_effects.registry import HarnessSideEffectHandler


def test_candidate_memory_ports_expose_no_direct_commit_capability() -> None:
    assert not hasattr(MemoryPort, "commit_write")
    assert not hasattr(HarnessMemoryPort, "commit_write")
    assert {status.value for status in MemoryWriteStatus} == {"proposed"}
    assert hasattr(HarnessSideEffectHandler, "commit")


def test_legacy_mcp_request_cannot_carry_caller_approval() -> None:
    assert "approved" not in {field.name for field in fields(MCPToolRequest)}
    assert {status.value for status in MCPApprovalStatus} == {
        "not_required",
        "required",
    }
