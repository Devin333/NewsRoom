"""Adapter for Ask-this-paper style answers over shared paper sessions."""

from __future__ import annotations

from collections.abc import Mapping

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult
from business.boards.paper_radar.agents.roles import (
    PAPER_ROLE_EVIDENCE_VERIFICATION,
    PAPER_ROLE_EXPERIMENT_RESULT,
    PAPER_ROLE_FINAL_PROFILE,
    PAPER_ROLE_MEMORY_RECORDS,
    PAPER_ROLE_READER_ANSWER,
    PAPER_ROLE_SEMANTIC_SECTIONS,
)
from business.boards.paper_radar.agents.utils.evidence import latest_output, sequence


class PaperReaderAgentAdapter:
    """Answer paper-reader questions from final profile and session evidence."""

    agent_id = "paper-reader-agent-adapter"
    required_roles = (
        PAPER_ROLE_FINAL_PROFILE,
        PAPER_ROLE_SEMANTIC_SECTIONS,
        PAPER_ROLE_EVIDENCE_VERIFICATION,
        PAPER_ROLE_EXPERIMENT_RESULT,
        PAPER_ROLE_MEMORY_RECORDS,
    )
    produced_role = PAPER_ROLE_READER_ANSWER

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        final_profile = latest_output(context.shared_items, PAPER_ROLE_FINAL_PROFILE)
        experiment = latest_output(context.shared_items, PAPER_ROLE_EXPERIMENT_RESULT)
        sections = latest_output(context.shared_items, PAPER_ROLE_SEMANTIC_SECTIONS)
        memory = latest_output(context.shared_items, PAPER_ROLE_MEMORY_RECORDS)
        answer = _answer(final_profile, experiment, memory, context.session_context_text)
        citations = _citations(experiment, sections, memory, context.session_context_text)
        output = {"answer": answer, "citations": citations, "evidence": citations}
        return PaperAgentResult(
            agent_id=self.agent_id,
            role=self.produced_role,
            output=output,
            summary=answer[:240],
            confidence=0.76 if final_profile else 0.58 if memory or context.session_context_text else 0.42,
        )


def _answer(
    final_profile: Mapping[str, object],
    experiment: Mapping[str, object],
    memory: Mapping[str, object],
    session_context_text: str | None,
) -> str:
    summary = final_profile.get("evidenceSummary")
    if summary:
        return str(summary)
    memory_summary = _memory_summary(memory)
    if memory_summary:
        return memory_summary
    if session_context_text:
        return "The shared session snapshot contains relevant paper analysis evidence."
    benchmarks = sequence(experiment.get("benchmarks"))
    if benchmarks:
        return f"The paper reports {len(benchmarks)} benchmark result(s)."
    return "The shared session does not contain enough evidence for a detailed answer."


def _citations(
    experiment: Mapping[str, object],
    sections: Mapping[str, object],
    memory: Mapping[str, object],
    session_context_text: str | None,
) -> list[Mapping[str, object]]:
    citations = []
    for benchmark in sequence(experiment.get("benchmarks")):
        if isinstance(benchmark, Mapping) and benchmark.get("evidence"):
            citations.append({"kind": "benchmark", "claimId": benchmark.get("claimId"), "evidence": benchmark.get("evidence")})
    for section in sequence(sections.get("sections"))[:3]:
        if isinstance(section, Mapping):
            citations.append({"kind": "section", "sectionId": section.get("sectionId"), "title": section.get("title")})
    for record in sequence(memory.get("memoryRecords"))[:3]:
        if isinstance(record, Mapping):
            citations.append({"kind": "memory", "summary": record.get("summary"), "refs": record.get("refs")})
    if session_context_text:
        citations.append({"kind": "session_snapshot", "evidence": session_context_text[:500]})
    return citations


def _memory_summary(memory: Mapping[str, object]) -> str | None:
    for record in sequence(memory.get("memoryRecords")):
        if isinstance(record, Mapping) and record.get("summary"):
            return str(record["summary"])
    return None
