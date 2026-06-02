"""Paper structure agent for semantic section extraction."""

from __future__ import annotations

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult
from business.boards.paper_radar.agents.roles import PAPER_ROLE_METADATA, PAPER_ROLE_SEMANTIC_SECTIONS
from business.boards.paper_radar.agents.utils.text_sections import build_semantic_sections


class PaperStructureAgent:
    """Convert page-level text and full-text excerpts into semantic sections."""

    agent_id = "paper-structure-agent"
    required_roles = (PAPER_ROLE_METADATA,)
    produced_role = PAPER_ROLE_SEMANTIC_SECTIONS

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        sections = build_semantic_sections(
            abstract=context.request.abstract,
            full_text=context.request.full_text,
            page_sections=context.request.page_sections,
        )
        section_types = {str(item.get("sectionType")) for item in sections}
        output = {
            "sections": sections,
            "sectionStats": {
                "hasMethod": "method" in section_types,
                "hasExperiment": bool({"experiment", "result"} & section_types),
                "hasLimitation": "limitation" in section_types,
                "sectionCount": len(sections),
            },
        }
        warnings = () if sections else ("no_semantic_sections_extracted",)
        return PaperAgentResult(
            agent_id=self.agent_id,
            role=self.produced_role,
            output=output,
            summary=f"Extracted {len(sections)} semantic section(s).",
            confidence=0.84 if sections else 0.2,
            warnings=warnings,
        )
