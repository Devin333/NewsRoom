from __future__ import annotations

from business.research.domain.document import (
    ResearchDocument,
    ResearchEquation,
    ResearchFigure,
    ResearchSection,
    ResearchTable,
)
from business.research.domain.common import SourceLineage


def make_doc(
    paper_id: str = "paper-1",
    *,
    sections: list[ResearchSection] | None = None,
) -> ResearchDocument:
    return ResearchDocument(
        paper_id=paper_id,
        source_hash="sha256-test",
        sections=sections or [],
        lineage=SourceLineage(source_refs=[f"paper://{paper_id}"], source_hash="sha256-test"),
    )


def make_section(
    section_id: str,
    title: str,
    text: str,
    level: int = 1,
    source_ref: str = "paper://paper-1",
) -> ResearchSection:
    return ResearchSection(
        section_id=section_id,
        title=title,
        level=level,
        text=text,
        source_ref=source_ref,
    )


def make_figure(figure_id: str, caption: str, source_ref: str = "paper://paper-1") -> ResearchFigure:
    return ResearchFigure(figure_id=figure_id, caption=caption, source_ref=source_ref)


def make_table(
    table_id: str, caption: str, columns: list[str] | None = None, source_ref: str = "paper://paper-1"
) -> ResearchTable:
    return ResearchTable(
        table_id=table_id, caption=caption, columns=columns or [], source_ref=source_ref
    )


def make_equation(equation_id: str, latex: str, source_ref: str = "paper://paper-1") -> ResearchEquation:
    return ResearchEquation(equation_id=equation_id, latex=latex, source_ref=source_ref)
