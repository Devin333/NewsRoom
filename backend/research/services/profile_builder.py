from __future__ import annotations

from backend.research.domain.analysis import ResearchAnalysis, ThreeMinuteRead
from backend.research.domain.evidence import ResearchEvidencePack


class ResearchProfileBuilder:
    def build_analysis(
        self,
        *,
        paper_id: str,
        summary: ThreeMinuteRead,
        evidence_pack: ResearchEvidencePack,
        contributions: list[str] | None = None,
        methods: list[str] | None = None,
        experiments: list[str] | None = None,
        limitations: list[str] | None = None,
    ) -> ResearchAnalysis:
        return ResearchAnalysis(
            paper_id=paper_id,
            summary=summary,
            contributions=contributions or [],
            methods=methods or [],
            experiments=experiments or [],
            limitations=limitations or [],
            evidence_pack_id=evidence_pack.pack_id,
            claims=[],
            quality={"evidence_item_count": len(evidence_pack.items)},
        )


__all__ = ["ResearchProfileBuilder"]
