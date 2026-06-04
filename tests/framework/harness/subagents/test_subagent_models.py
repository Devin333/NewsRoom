from __future__ import annotations

import pytest

from framework.harness import (
    ContextEnvelope,
    HarnessValidationError,
    SubAgentContextEnvelope,
    SubAgentResult,
    fake_subagent_spec,
)


def test_subagent_spec_requires_explicit_tools_and_memory_namespaces() -> None:
    with pytest.raises(HarnessValidationError):
        fake_subagent_spec(allowed_tools=())

    with pytest.raises(HarnessValidationError):
        fake_subagent_spec(allowed_memory_namespaces=())


def test_context_envelope_rejects_parent_raw_messages() -> None:
    spec = fake_subagent_spec()

    with pytest.raises(HarnessValidationError):
        SubAgentContextEnvelope(
            child_run_id="child",
            parent_run_id="parent",
            subagent_id=spec.subagent_id,
            role=spec.role,
            allowed_input_refs=("input://1",),
            context_pack={"parent_raw_messages": ["hidden"]},
            memory_context_refs=(),
            tool_policy_ref="tool-policy://child",
            budget_snapshot={},
        )


def test_subagent_result_rejects_flow_control_fields() -> None:
    with pytest.raises(HarnessValidationError):
        SubAgentResult(
            invocation_id="inv",
            child_run_id="child",
            subagent_id="critic",
            status="succeeded",
            output={"next_step": "publish"},
        )


def test_subagent_context_only_contains_envelope_not_parent_raw_context() -> None:
    envelope = ContextEnvelope(envelope_id="context://safe", stable_prefix={"policy": "ok"})

    assert "parent_raw_messages" not in envelope.to_dict()
