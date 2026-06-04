from __future__ import annotations

from business.research.domain import ReaderIssue
from business.research.domain.reader_repair import ReaderRepairMemoryQuery
from business.research.reader_repair import ReaderRepairContextBuilder


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
    builder = ReaderRepairContextBuilder()
    pack = builder.build_pack(
        issue=issue,
        query=ReaderRepairMemoryQuery.from_issue(issue),
        successful_cases=[],
        failed_cases=[],
        strategies=[],
    )

    result = builder.assemble_for_subagent(
        context_pack=pack,
        run_id="repair-run-context",
        step_id="propose_repair_candidate",
        subagent_id="reader_repair_proposer",
        role="proposer",
        max_input_tokens=256,
        evidence_memory_tokens=900,
    )

    assert result.context_envelope.snapshot_ref
    assert result.context_envelope.evidence_refs
    assert "hidden_prompt" not in str(result.context_envelope.stable_prefix)
    assert result.compression_records
    assert "paper://paper-1/sec-1" in result.compression_records[0]["preserved_refs"]
