from __future__ import annotations

from business.research.graphs.contracts import (
    RESEARCH_ARTIFACT_NOT_REQUIRED_EVIDENCE_REF,
    RESEARCH_ARTIFACT_TERMINAL_POLICY_ID,
    RESEARCH_ARTIFACT_TERMINAL_POLICY_VERSION,
    RESEARCH_DYNAMIC_PAPER_ANALYSIS_GRAPH_ID,
    RESEARCH_PAPER_ANALYSIS_GRAPH_ID,
    RESEARCH_PAPER_ANALYSIS_GRAPH_VERSION,
    build_research_artifact_terminal_policy,
)
from business.research.graphs.paper_analysis import (
    build_dynamic_paper_analysis_graph_definition,
    build_paper_analysis_graph_definition,
)


__all__ = [
    "RESEARCH_ARTIFACT_NOT_REQUIRED_EVIDENCE_REF",
    "RESEARCH_ARTIFACT_TERMINAL_POLICY_ID",
    "RESEARCH_ARTIFACT_TERMINAL_POLICY_VERSION",
    "RESEARCH_DYNAMIC_PAPER_ANALYSIS_GRAPH_ID",
    "RESEARCH_PAPER_ANALYSIS_GRAPH_ID",
    "RESEARCH_PAPER_ANALYSIS_GRAPH_VERSION",
    "build_dynamic_paper_analysis_graph_definition",
    "build_paper_analysis_graph_definition",
    "build_research_artifact_terminal_policy",
]
