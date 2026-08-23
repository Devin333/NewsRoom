from __future__ import annotations

import pytest

from framework.harness import HarnessEventType, HarnessValidationError
from business.research.domain import ReaderIssue
from business.research.domain.reader_repair import ReaderRepairMemoryQuery
from business.research.reader_repair import ReaderRepairContextBuilder
from business.research.graphs.reader_repair import build_reader_repair_context_graph_identity
from tests.framework.harness.context.runtime_fakes import verified_context_assembler


def test_repair_context_pack_writes_context_snapshot_before_subagents() -> None:
    issue = ReaderIssue(
        issue_id="issue-context",
        paper_id="paper-1",
        issue_type="source_lineage_missing",
        error_signature="source-lineage",
        symptom="Source lineage is missing.",
        source_refs=["paper://paper-1/sec-1"],
        payload_ref="payload-before",
    )
    context_assembler, _, context_events = verified_context_assembler()
    builder = ReaderRepairContextBuilder(context_assembler)
    pack = builder.build_pack(
        issue=issue,
        query=ReaderRepairMemoryQuery.from_issue(issue),
        successful_cases=[],
        failed_cases=[],
        strategies=[],
    )

    result = builder.assemble_for_subagent(
        context_pack=pack,
        graph_identity=build_reader_repair_context_graph_identity(
            run_id="repair-run-context",
            stage_id="propose_repair_candidate",
        ),
        subagent_id="reader_repair_proposer",
        role="proposer",
        max_input_tokens=4096,
        evidence_memory_tokens=160,
    )

    assert result.context_envelope.snapshot_ref
    assert result.context_envelope.evidence_refs
    assert "hidden_prompt" not in str(result.context_envelope.stable_prefix)
    assert result.context_envelope.metadata["context_verification_classification"] == (
        "versioned_no_compaction_evidence"
    )
    assert result.compression_records == ()
    assert context_events.events[-1].event_type is HarnessEventType.CONTEXT_COMPACTION_PLANNED


def test_repair_protected_context_overflow_fails_closed() -> None:
    issue = ReaderIssue(
        issue_id="issue-context-overflow",
        paper_id="paper-1",
        issue_type="source_lineage_missing",
        error_signature="source-lineage-overflow",
        symptom="Source lineage is missing.",
        source_refs=["paper://paper-1/sec-1"],
        payload_ref="payload-before",
    )
    context_assembler, _, context_events = verified_context_assembler()
    builder = ReaderRepairContextBuilder(context_assembler)
    pack = builder.build_pack(
        issue=issue,
        query=ReaderRepairMemoryQuery.from_issue(issue),
        successful_cases=[],
        failed_cases=[],
        strategies=[],
    )

    with pytest.raises(HarnessValidationError, match="did not authorize"):
        builder.assemble_for_subagent(
            context_pack=pack,
            graph_identity=build_reader_repair_context_graph_identity(
                run_id="repair-run-context-overflow",
                stage_id="propose_repair_candidate",
            ),
            subagent_id="reader_repair_proposer",
            role="proposer",
            max_input_tokens=256,
            evidence_memory_tokens=900,
        )

    assert HarnessEventType.CONTEXT_COMPACTION_VERIFIED not in {
        event.event_type for event in context_events.events
    }
