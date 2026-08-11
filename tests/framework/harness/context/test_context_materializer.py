from __future__ import annotations

from dataclasses import replace

import pytest

from framework.harness import (
    ContextCompressionLevel,
    ContextGroupKind,
    ContextGroupMaterializer,
    ContextMaterializationRequest,
    ContextProtectionReason,
    ContextSegment,
    ContextSegmentType,
    ContextToolTransactionState,
    HarnessValidationError,
)


def _request(**overrides: object) -> ContextMaterializationRequest:
    values: dict[str, object] = {
        "run_id": "run-1",
        "step_id": "step-1",
        "task_binding_ref": "task://current",
        "policy_revision": "policy-v1",
        "physical_profile_revision": "profile-v1",
        "messages": (
            {"role": "user", "content_ref": "message://user-1", "turn_id": "turn-1"},
            {
                "role": "assistant",
                "content_ref": "message://assistant-1",
                "turn_id": "turn-2",
            },
        ),
    }
    values.update(overrides)
    return ContextMaterializationRequest(**values)  # type: ignore[arg-type]


def _segment(
    segment_type: ContextSegmentType,
    *,
    suffix: str,
    summary: str = "legacy summary body",
    metadata: dict | None = None,
) -> ContextSegment:
    return ContextSegment(
        segment_id=f"segment-{suffix}",
        segment_type=segment_type,
        content_ref=f"artifact://segment/{suffix}#sha256=abc",
        summary=summary,
        token_estimate=10,
        compression_level=ContextCompressionLevel.C1_CANONICAL_RECORD,
        provenance_refs=(f"source://{suffix}",),
        metadata=metadata or {},
    )


def test_materialization_is_stable_and_excludes_diagnostic_profile_overrides() -> None:
    materializer = ContextGroupMaterializer()
    first = materializer.materialize(
        _request(diagnostic_metadata={"context_profile": "forged-a"})
    )
    second = materializer.materialize(
        _request(diagnostic_metadata={"context_profile": "forged-b"})
    )

    assert first.snapshot_id == second.snapshot_id
    assert first.checksum == second.checksum
    assert first.physical_profile_revision == "profile-v1"
    with pytest.raises(HarnessValidationError, match="authority overrides"):
        materializer.materialize(
            _request(
                messages=(
                    {
                        "role": "user",
                        "content_ref": "message://user-1",
                        "physical_profile_revision": "forged-profile",
                    },
                )
            )
        )


def test_request_deep_copies_source_mappings_and_snapshot_refs_are_immutable() -> None:
    source = {"role": "user", "content_ref": "message://user-1"}
    request = _request(messages=(source,))
    source["content_ref"] = "message://mutated"
    snapshot = ContextGroupMaterializer().materialize(request)

    assert snapshot.groups[0].members[0].content_ref == "message://user-1"
    with pytest.raises(TypeError):
        snapshot.groups[0].semantic_metadata["mutate"] = True  # type: ignore[index]


@pytest.mark.parametrize(
    "messages,match",
    [
        (({"role": "assistant", "content_ref": "message://a"},), "start with a user"),
        (
            (
                {"role": "user", "content_ref": "message://u"},
                {"role": "user", "content_ref": "message://u2"},
            ),
            "roles must alternate",
        ),
        (
            (
                {"role": "user", "content_ref": "message://u"},
                {"role": "system", "content_ref": "message://s"},
            ),
            "system message must precede",
        ),
        (({"role": "user", "content": "raw body"},), "raw fields are unsupported"),
        (
            (
                {"role": "user", "content_ref": "message://u", "source_refs": "bad"},
            ),
            "list of strings",
        ),
        (
            (
                {
                    "role": "user",
                    "content_ref": "message://u",
                    "tool_calls": {},
                },
            ),
            "tool_calls must be a list",
        ),
        (
            (
                {
                    "role": "user",
                    "content_ref": "message://u",
                    "untracked_semantics": "ignored-before-validation",
                },
            ),
            "unsupported fields",
        ),
    ],
)
def test_materializer_rejects_ambiguous_message_shapes(
    messages: tuple[dict, ...],
    match: str,
) -> None:
    with pytest.raises(HarnessValidationError, match=match):
        ContextGroupMaterializer().materialize(_request(messages=messages))


def test_required_output_contract_is_structurally_enforced() -> None:
    materializer = ContextGroupMaterializer()
    with pytest.raises(HarnessValidationError, match="output contract"):
        materializer.materialize(_request(requires_output_contract=True))

    snapshot = materializer.materialize(
        _request(
            requires_output_contract=True,
            output_contract_ref="schema://answer-v1",
        )
    )
    contract = next(
        group for group in snapshot.groups if group.group_kind is ContextGroupKind.OUTPUT_CONTRACT
    )
    assert contract.members[0].content_ref == "schema://answer-v1"
    assert contract.protection_reasons == (ContextProtectionReason.OUTPUT_CONTRACT,)


def test_completed_tool_round_trip_is_atomic_and_allows_assistant_followup() -> None:
    snapshot = ContextGroupMaterializer().materialize(
        _request(
            messages=(
                {"role": "user", "content_ref": "message://u"},
                {
                    "role": "assistant",
                    "content_ref": "message://tool-request",
                    "tool_calls": (
                        {
                            "id": "call-1",
                            "name": "search",
                            "content_ref": "tool-call://1",
                        },
                    ),
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-1",
                    "content_ref": "tool-result://1",
                },
                {"role": "assistant", "content_ref": "message://final"},
            )
        )
    )
    transactions = [
        group
        for group in snapshot.groups
        if group.group_kind is ContextGroupKind.TOOL_TRANSACTION
    ]

    assert len(transactions) == 1
    assert transactions[0].tool_transaction_state is ContextToolTransactionState.COMPLETED
    assert [member.tool_call_id for member in transactions[0].members] == [
        "call-1",
        "call-1",
    ]
    assert len(transactions[0].members) == 2


def test_pending_tool_transaction_is_protected() -> None:
    snapshot = ContextGroupMaterializer().materialize(
        _request(
            messages=(
                {"role": "user", "content_ref": "message://u"},
                {
                    "role": "assistant",
                    "content_ref": "message://tool-request",
                    "tool_calls": ({"id": "call-1", "name": "search"},),
                },
            )
        )
    )
    transaction = snapshot.groups[-1]

    assert transaction.tool_transaction_state is ContextToolTransactionState.PENDING
    assert transaction.protection_reasons == (
        ContextProtectionReason.PENDING_TOOL_TRANSACTION,
    )


@pytest.mark.parametrize(
    "messages,match",
    [
        (
            (
                {"role": "user", "content_ref": "message://u"},
                {
                    "role": "tool",
                    "tool_call_id": "call-1",
                    "content_ref": "tool-result://1",
                },
            ),
            "must follow an assistant tool call",
        ),
        (
            (
                {"role": "user", "content_ref": "message://u"},
                {
                    "role": "assistant",
                    "content_ref": "message://tool-request",
                    "tool_calls": (
                        {"id": "call-1", "name": "search"},
                        {"id": "call-2", "name": "fetch"},
                    ),
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-1",
                    "content_ref": "tool-result://1",
                },
                {"role": "assistant", "content_ref": "message://final"},
            ),
            "partial tool results",
        ),
        (
            (
                {"role": "user", "content_ref": "message://u"},
                {
                    "role": "assistant",
                    "content_ref": "message://tool-request",
                    "tool_calls": ({"id": "call-1", "arguments": {"q": "raw"}},),
                },
            ),
            "raw fields are unsupported",
        ),
    ],
)
def test_materializer_rejects_invalid_tool_transactions(
    messages: tuple[dict, ...],
    match: str,
) -> None:
    with pytest.raises(HarnessValidationError, match=match):
        ContextGroupMaterializer().materialize(_request(messages=messages))


def test_evidence_materialization_preserves_lineage_citations_and_conflicts() -> None:
    snapshot = ContextGroupMaterializer().materialize(
        _request(
            evidence_items=(
                {
                    "evidence_id": "evidence-1",
                    "source_refs": ("source://paper-1",),
                    "span_refs": ("span://1", "span://2"),
                    "lineage_refs": ("lineage://extract-1",),
                    "required_citation_refs": ("citation://1",),
                    "conflict_refs": ("evidence://conflict-1",),
                },
            )
        )
    )
    evidence = next(
        group for group in snapshot.groups if group.group_kind is ContextGroupKind.EVIDENCE
    )

    assert [member.content_ref for member in evidence.members] == ["span://1", "span://2"]
    assert evidence.query_binding_ref == "task://current"
    assert evidence.required_citation_refs == ("citation://1",)
    assert evidence.protection_reasons == (ContextProtectionReason.REQUIRED_EVIDENCE,)
    assert evidence.semantic_metadata["lineage_refs"] == ["lineage://extract-1"]
    assert evidence.semantic_metadata["conflict_refs"] == ["evidence://conflict-1"]


@pytest.mark.parametrize("field", ["source_refs", "span_refs", "lineage_refs"])
def test_evidence_requires_typed_non_empty_provenance(field: str) -> None:
    evidence = {
        "evidence_id": "evidence-1",
        "source_refs": ("source://paper-1",),
        "span_refs": ("span://1",),
        "lineage_refs": ("lineage://extract-1",),
    }
    evidence[field] = "not-a-list"

    with pytest.raises(HarnessValidationError, match="list of strings"):
        ContextGroupMaterializer().materialize(
            _request(evidence_items=(evidence,))
        )


def test_trusted_groups_receive_only_harness_derived_protection_reasons() -> None:
    snapshot = ContextGroupMaterializer().materialize(
        _request(
            messages=(
                {"role": "system", "content_ref": "policy://safety"},
                {"role": "user", "content_ref": "message://u"},
            ),
            output_contract_ref="schema://answer-v1",
            retry_state_ref="run-state://retry-2",
            control_decision_refs=("decision://route-1",),
            authorized_tools=(
                {
                    "tool_id": "search",
                    "schema_ref": "schema://tool/search-v1",
                    "authorization_ref": "authorization://run-1/search",
                    "required": True,
                    "reachable": True,
                },
            ),
        )
    )
    protections = {
        group.group_kind: set(group.protection_reasons) for group in snapshot.groups
    }

    assert ContextProtectionReason.SAFETY_CONSTRAINT in protections[
        ContextGroupKind.SYSTEM_INSTRUCTION
    ]
    assert ContextProtectionReason.OUTPUT_CONTRACT in protections[
        ContextGroupKind.OUTPUT_CONTRACT
    ]
    assert ContextProtectionReason.RETRY_REPLAN_STATE in protections[
        ContextGroupKind.RUN_STATE
    ]
    assert ContextProtectionReason.CONTROL_DECISION in protections[
        ContextGroupKind.AUTHORIZED_TOOL_SCHEMA
    ]


def test_legacy_segments_are_grouped_by_type_without_using_summary_body() -> None:
    segments = tuple(
        _segment(segment_type, suffix=str(index))
        for index, segment_type in enumerate(ContextSegmentType)
    )
    request = _request(messages=(), segments=segments)
    first = ContextGroupMaterializer().materialize(request)
    changed_summary = replace(segments[-1], summary="different untrusted body")
    second = ContextGroupMaterializer().materialize(
        replace(request, segments=(*segments[:-1], changed_summary))
    )

    assert first.snapshot_id == second.snapshot_id
    assert "legacy summary body" not in str(first.to_dict())
    assert [group.group_kind for group in first.groups] == [
        ContextGroupKind.SYSTEM_INSTRUCTION,
        ContextGroupKind.WORKFLOW_CONTRACT,
        ContextGroupKind.WORKFLOW_CONTRACT,
        ContextGroupKind.RUN_STATE,
        ContextGroupKind.EVIDENCE,
        ContextGroupKind.CURRENT_TASK,
    ]
