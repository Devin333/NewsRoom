from __future__ import annotations

from framework.agent import AgentSpec
from business.boards.cross_board.workflows.daily_intelligence.agent_output_budget import (
    daily_agent_validation_policy,
)


PLANNER_AGENT_ID = "daily.planner"
ANALYST_AGENT_ID = "daily.analyst"
WRITER_AGENT_ID = "daily.writer"
VERIFIER_AGENT_ID = "daily.verifier"
EDITOR_AGENT_ID = "daily.editor"


def build_planner_agent() -> AgentSpec:
    return AgentSpec(
        agent_id=PLANNER_AGENT_ID,
        name="Daily Intelligence Planner",
        role="PlannerAgent",
        goal="Create a source-bounded research plan for the requested daily intelligence topic.",
        instructions=(
            "Plan the report structure and research focus using only the request "
            "and the provided evidence/source context. You may inspect source "
            "metadata from the provided evidence bundle, but do not fetch sources "
            "or infer facts. Return JSON only."
        ),
        input_keys=["request", "evidence_bundle", "source_errors", "source_pipeline_metrics"],
        output_key="research_plan",
        validation_policy=daily_agent_validation_policy(),
        allowed_tools=["daily.source_metadata"],
        output_schema={
            "type": "object",
            "required": ["research_plan"],
            "properties": {
                "research_plan": {
                    "type": "object",
                    "required": ["topic", "sections", "constraints"],
                    "properties": {
                        "topic": {"type": "string"},
                        "sections": {"type": "array", "items": {"type": "string"}},
                        "constraints": {"type": "object"},
                    },
                },
                "planner_notes": {"type": "object"},
            },
        },
    )


def build_analyst_agent() -> AgentSpec:
    return AgentSpec(
        agent_id=ANALYST_AGENT_ID,
        name="Daily Intelligence Analyst",
        role="AnalystAgent",
        goal="Transform the evidence bundle into structured findings, trend signals, and risk notes.",
        instructions=(
            "Only use the provided evidence bundle and research plan. Do not introduce "
            "outside facts or sources. Mark uncertain or inferential points explicitly. "
            "Return JSON only."
        ),
        input_keys=["request", "research_plan", "evidence_bundle", "source_errors", "source_pipeline_metrics"],
        output_key="analysis_result",
        validation_policy=daily_agent_validation_policy(),
        allowed_tools=["daily.evidence_search", "daily.source_metadata"],
        output_schema={
            "type": "object",
            "required": ["analysis_result"],
            "properties": {
                "analysis_result": {
                    "type": "object",
                    "required": ["findings", "trend_signals", "risk_notes", "uncertainty_notes"],
                    "properties": {
                        "findings": {"type": "array", "items": {"type": "object"}},
                        "trend_signals": {"type": "array", "items": {"type": "object"}},
                        "risk_notes": {"type": "array", "items": {"type": "string"}},
                        "uncertainty_notes": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "analyst_notes": {"type": "object"},
            },
        },
    )


def build_writer_agent() -> AgentSpec:
    return AgentSpec(
        agent_id=WRITER_AGENT_ID,
        name="Daily Intelligence Writer",
        role="WriterAgent",
        goal="Create evidence-bounded section cards for the daily intelligence report draft.",

        instructions=(
            "Only use the provided research plan, analysis result, verified findings, "
            "and evidence bundle. Do not introduce outside facts or sources. Return "
            "JSON only. Produce evidence-bounded section cards, not a narrative report. "
            "Each section must represent only directly supported claims from the evidence "
            "bundle. Do not add recommendations, market implications, conclusions, "
            "meta-summary lines, cross-source synthesis, or claims about trends unless "
            "they appear explicitly in the evidence. Each section must include "
            "section_id, title, content, sources, and claim_grounding. The content must "
            "be a compact restatement of the same claims listed in claim_grounding, not "
            "new prose beyond them. Every claim_grounding entry must map one explicit "
            "claim to source_urls and evidence_ids when available."
        ),
        input_keys=[
            "request",
            "research_plan",
            "analysis_result",
            "verified_findings",
            "evidence_bundle",
            "source_errors",
            "source_pipeline_metrics",
        ],
        output_key="report_draft",
        validation_policy=daily_agent_validation_policy(),
        allowed_tools=["daily.evidence_search", "daily.section_draft"],
        output_schema={
            "type": "object",
            "required": ["report_draft"],
            "properties": {
                "report_draft": {
                    "type": "object",
                    "required": ["title", "sections", "metadata"],
                    "properties": {
                        "title": {"type": "string"},
                        "sections": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["section_id", "title", "content", "sources", "claim_grounding"],
                                "properties": {
                                    "section_id": {"type": "string"},
                                    "title": {"type": "string"},
                                    "content": {"type": "string"},
                                    "sources": {"type": "array", "items": {"type": "string"}},
                                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                                    "claim_grounding": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "required": ["claim_id", "text", "evidence_ids", "source_urls"],
                                            "properties": {
                                                "claim_id": {"type": "string"},
                                                "text": {"type": "string"},
                                                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                                                "source_urls": {"type": "array", "items": {"type": "string"}},
                                            },
                                        },
                                    },
                                },
                            },
                        },
                        "metadata": {"type": "object"},
                    },
                },
                "writer_notes": {"type": "object"},
            },
        },
    )


def build_verifier_agent() -> AgentSpec:
    return AgentSpec(
        agent_id=VERIFIER_AGENT_ID,
        name="Daily Intelligence Verifier",
        role="VerifierAgent",
        goal="Verify that the report draft is supported by the evidence bundle.",
        instructions=(
            "Check citations, unsupported claims, and source coverage. Do not "
            "rewrite the report. Return explicit claim-level grounding in "
            "verification_result.grounded_claims, including claim IDs, section IDs, "
            "support status, source URLs, evidence IDs when available, and reasons. "
            "Never invent, normalize, reformat, or partially rewrite evidence IDs. "
            "Only copy evidence_ids exactly from the provided report_draft claim_grounding, "
            "candidate_claims, verified_findings, or evidence_bundle. If an evidence ID "
            "cannot be copied exactly from inputs, leave evidence_ids empty instead of "
            "guessing. Return JSON only."
        ),
        input_keys=[
            "report_draft",
            "evidence_bundle",
            "candidate_claims",
            "verified_findings",
        ],
        output_key="verification_result",
        validation_policy=daily_agent_validation_policy(),
        allowed_tools=["daily.citation_validate", "daily.evidence_search"],
        output_schema={
            "type": "object",
            "required": [
                "citation_check_result",
                "support_matrix",
                "verification_result",
            ],
            "properties": {
                "citation_check_result": {"type": "object"},
                "support_matrix": {"type": "object"},
                "verification_result": {
                    "type": "object",
                    "required": ["status", "unsupported_claims", "missing_citations", "risk_level", "reasons", "grounded_claims"],
                    "properties": {
                        "status": {"enum": ["pass", "needs_rewrite", "blocked"]},
                        "unsupported_claims": {"type": "array"},
                        "missing_citations": {"type": "array"},
                        "risk_level": {"enum": ["low", "medium", "high"]},
                        "reasons": {"type": "array", "items": {"type": "string"}},
                        "grounded_claims": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": [
                                    "claim_id",
                                    "section_id",
                                    "status",
                                    "evidence_ids",
                                    "source_urls",
                                    "reason"
                                ],
                                "properties": {
                                    "claim_id": {"type": "string"},
                                    "section_id": {"type": "string"},
                                    "status": {
                                        "enum": ["supported", "unsupported", "rejected", "uncertain"]
                                    },
                                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                                    "source_urls": {"type": "array", "items": {"type": "string"}},
                                    "reason": {"type": "string"},
                                },
                            },
                        },
                    },
                },
                "verifier_notes": {"type": "object"},
            },
        },
    )


def build_editor_agent() -> AgentSpec:
    return AgentSpec(
        agent_id=EDITOR_AGENT_ID,
        name="Daily Intelligence Editor",
        role="EditorAgent",
        goal=(
            "Decide whether the report can pass, needs rewrite, needs human "
            "review, or should be blocked."
        ),
        instructions=(
            "Use verification results and evidence. If a rewrite is required, "
            "edited_report_draft must only cite source URLs from the provided "
            "evidence bundle. Do not publish, write artifacts, or collect "
            "sources. Return JSON only."
        ),
        input_keys=[
            "report_draft",
            "verification_result",
            "citation_check_result",
            "support_matrix",
            "evidence_bundle",
        ],
        output_key="editor_review",
        validation_policy=daily_agent_validation_policy(),
        allowed_tools=["daily.citation_validate", "daily.section_draft"],
        output_schema={
            "type": "object",
            "required": ["editor_review"],
            "properties": {
                "editor_review": {
                    "type": "object",
                    "required": [
                        "decision",
                        "quality_score",
                        "reasons",
                        "rewrite_instructions",
                    ],
                    "properties": {
                        "decision": {
                            "enum": [
                                "pass",
                                "rewrite_required",
                                "human_review_required",
                                "block",
                            ]
                        },
                        "quality_score": {"type": "number"},
                        "reasons": {"type": "array", "items": {"type": "string"}},
                        "rewrite_instructions": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
                "edited_report_draft": {
                    "type": ["object", "null"],
                    "properties": {
                        "title": {"type": "string"},
                        "sections": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "section_id": {"type": "string"},
                                    "title": {"type": "string"},
                                    "content": {"type": "string"},
                                    "sources": {"type": "array", "items": {"type": "string"}},
                                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                                    "claim_grounding": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "required": ["claim_id", "text", "evidence_ids", "source_urls"],
                                            "properties": {
                                                "claim_id": {"type": "string"},
                                                "text": {"type": "string"},
                                                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                                                "source_urls": {"type": "array", "items": {"type": "string"}},
                                            },
                                        },
                                    },
                                },
                            },
                        },
                        "metadata": {"type": "object"},
                    },
                },
                "editor_notes": {"type": "object"},
            },
        },
    )
