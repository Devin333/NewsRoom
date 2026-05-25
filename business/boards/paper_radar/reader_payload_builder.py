from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from business.boards.paper_radar.public_mapper import sanitize_public_payload


@dataclass(frozen=True)
class PaperSection:
    id: str
    paperId: str
    title: str
    level: int
    pageStart: int | None
    pageEnd: int | None
    textExcerpt: str
    summary: str | None
    sectionType: str

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "paperId": self.paperId,
            "title": self.title,
            "level": self.level,
            "textExcerpt": self.textExcerpt,
            "sectionType": self.sectionType,
        }
        if self.pageStart is not None:
            payload["pageStart"] = self.pageStart
        if self.pageEnd is not None:
            payload["pageEnd"] = self.pageEnd
        if self.summary:
            payload["summary"] = self.summary
        return payload


@dataclass(frozen=True)
class PaperReaderQuality:
    paperId: str
    pdfAvailable: bool
    textExtracted: bool
    summaryAvailable: bool
    implementationVerified: bool
    benchmarkVerified: bool
    evidenceCoverage: float
    lastUpdatedAt: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "paperId": self.paperId,
            "pdfAvailable": self.pdfAvailable,
            "textExtracted": self.textExtracted,
            "summaryAvailable": self.summaryAvailable,
            "implementationVerified": self.implementationVerified,
            "benchmarkVerified": self.benchmarkVerified,
            "evidenceCoverage": self.evidenceCoverage,
            "lastUpdatedAt": self.lastUpdatedAt,
        }


@dataclass(frozen=True)
class PaperReaderPayload:
    paper: Any
    sections: tuple[PaperSection, ...]
    aiSummary: Any | None
    readerNotes: tuple[Mapping[str, Any], ...]
    relatedPapers: tuple[Mapping[str, Any], ...]
    relatedProjects: tuple[Mapping[str, Any], ...]
    relatedNews: tuple[Mapping[str, Any], ...]
    quality: PaperReaderQuality

    def to_dict(self) -> dict[str, Any]:
        return sanitize_public_payload(
            {
                "paper": self.paper.to_dict(),
                "sections": [section.to_dict() for section in self.sections],
                "aiSummary": self.aiSummary.to_dict() if self.aiSummary is not None else None,
                "readerNotes": list(self.readerNotes),
                "relatedPapers": list(self.relatedPapers),
                "relatedProjects": list(self.relatedProjects),
                "relatedNews": list(self.relatedNews),
                "quality": self.quality.to_dict(),
            }
        )


def build_reader_payload(paper: Any, *, ai_summary: Any | None) -> PaperReaderPayload:
    sections = (
        PaperSection(
            id=f"{paper.id}:abstract",
            paperId=paper.id,
            title="Abstract",
            level=1,
            pageStart=None,
            pageEnd=None,
            textExcerpt=paper.abstractSnippet,
            summary=ai_summary.summary if ai_summary is not None else None,
            sectionType="abstract",
        ),
    )
    quality = PaperReaderQuality(
        paperId=paper.id,
        pdfAvailable=bool(paper.pdfUrl),
        textExtracted=False,
        summaryAvailable=ai_summary is not None,
        implementationVerified=bool(paper.implementations),
        benchmarkVerified=bool(paper.benchmarks),
        evidenceCoverage=1.0 if getattr(paper, "evidenceRefs", ()) else 0.0,
        lastUpdatedAt=paper.publishedAt,
    )
    return PaperReaderPayload(
        paper=paper,
        sections=sections,
        aiSummary=ai_summary,
        readerNotes=(),
        relatedPapers=(),
        relatedProjects=(),
        relatedNews=(),
        quality=quality,
    )
