from __future__ import annotations

from core.framework.agent_loop import AgentSpec


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
            "Plan the report structure and research focus using only the request. "
            "Do not fetch sources or infer facts. Return JSON only."
        ),
        input_keys=["request"],
        output_key="research_plan",
        allowed_tools=[],
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
        allowed_tools=[],
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
        goal="Create a source-grounded daily intelligence report draft.",
        instructions=(
            "Only use the provided research plan, analysis result, verified findings, "
            "and evidence bundle. Do not introduce outside facts or sources. Every "
            "section must stay evidence-bounded. Return JSON only."
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
        allowed_tools=[],
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
                                "required": ["title", "content", "sources"],
                                "properties": {
                                    "title": {"type": "string"},
                                    "content": {"type": "string"},
                                    "sources": {"type": "array", "items": {"type": "string"}},
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
            "rewrite the report. Return JSON only."
        ),
        input_keys=[
            "report_draft",
            "evidence_bundle",
            "candidate_claims",
            "verified_findings",
        ],
        output_key="verification_result",
        allowed_tools=[],
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
                    "required": [
                        "status",
                        "unsupported_claims",
                        "missing_citations",
                        "risk_level",
                        "reasons",
                    ],
                    "properties": {
                        "status": {"enum": ["pass", "needs_rewrite", "blocked"]},
                        "unsupported_claims": {"type": "array"},
                        "missing_citations": {"type": "array"},
                        "risk_level": {"enum": ["low", "medium", "high"]},
                        "reasons": {"type": "array", "items": {"type": "string"}},
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
        allowed_tools=[],
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
                                    "title": {"type": "string"},
                                    "content": {"type": "string"},
                                    "sources": {"type": "array", "items": {"type": "string"}},
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
