from __future__ import annotations

import re
from dataclasses import dataclass, field

from business.research.domain.document import ResearchDocument, ResearchEquation, ResearchFigure, ResearchTable

# Cross-section reference patterns (Chinese + English)
_CROSS_REF_PATTERNS = [
    re.compile(r"(?:如|见|参见|详见)第\s*(\d+)\s*[节章]"),
    re.compile(r"(?:see|as\s+in|refer\s+to)\s+[Ss]ection\s+(\d+)", re.IGNORECASE),
    re.compile(r"附录\s*([A-Z])", re.IGNORECASE),
    re.compile(r"[Aa]ppendix\s+([A-Z])"),
]
_FORMULA_REF_PATTERNS = [
    re.compile(r"公式\s*[（(](\d+)[)）]"),
    re.compile(r"[Ee]q(?:uation)?\.?\s*[（(](\d+)[)）]"),
]
_VARIABLE_DEF_PATTERN = re.compile(
    r"([\wα-ωΑ-Ω_]+)\s*(?:表示|代表|is|denotes?|represents?)\s*(.{5,80})"
)


@dataclass
class ScannedElements:
    equations: dict[str, ResearchEquation] = field(default_factory=dict)
    figures: dict[str, ResearchFigure] = field(default_factory=dict)
    tables: dict[str, ResearchTable] = field(default_factory=dict)
    section_cross_refs: dict[str, list[str]] = field(default_factory=dict)  # section_id -> ref labels
    variable_definitions: dict[str, str] = field(default_factory=dict)       # var -> definition


def scan_special_elements(doc: ResearchDocument) -> ScannedElements:
    result = ScannedElements(
        equations={eq.equation_id: eq for eq in doc.equations},
        figures={fig.figure_id: fig for fig in doc.figures},
        tables={tbl.table_id: tbl for tbl in doc.tables},
    )
    for section in doc.sections:
        # variable definitions
        for m in _VARIABLE_DEF_PATTERN.finditer(section.text):
            result.variable_definitions[m.group(1)] = m.group(2).strip()
        # cross-section refs
        refs: list[str] = []
        for pattern in _CROSS_REF_PATTERNS:
            refs.extend(m.group(1) for m in pattern.finditer(section.text))
        for pattern in _FORMULA_REF_PATTERNS:
            refs.extend(f"eq:{m.group(1)}" for m in pattern.finditer(section.text))
        if refs:
            result.section_cross_refs[section.section_id] = refs
    return result


__all__ = ["ScannedElements", "scan_special_elements"]
