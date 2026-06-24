from __future__ import annotations

import re
from hashlib import sha256
from typing import Any

from business.foundation import build_stable_id
from business.research.domain.document import ResearchDocument, ResearchEquation, ResearchTable
from business.research.document.models import ChunkType, PaperChunk, ParseSource, SectionRole
from business.research.document.section_detector import classify_section_role, is_abstract_section
from business.research.document.special_element_scanner import ScannedElements, scan_special_elements

# Roles that support proposition decomposition (PRD §5)
_PROPOSITION_ROLES: frozenset[str] = frozenset(["related_work", "experiment", "conclusion"])

_PARAGRAPH_SEP = re.compile(r"\n\n+")
_SENTENCE_END = re.compile(r"(?<=[.!?。！？])\s+")
_LATEX_FORMULA = re.compile(r"\\begin\{(?:equation|align|gather)[^}]*\}.*?\\end\{[^}]+\}", re.DOTALL)
_INLINE_FORMULA = re.compile(r"\$\$[^$]+\$\$|\$[^$\n]+\$")
_FIGURE_REF = re.compile(r"图\s*(\w+)|[Ff]ig(?:ure)?[.s]?\s*(\w+)")
_LOCATOR_PAGE_RE = re.compile(r"(?:#|&)page=(\d+)")

# Minimum sections to count as "structure detected" (PRD §3)
_MIN_STRUCTURED_SECTIONS = 3


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PARAGRAPH_SEP.split(text) if p.strip()]


def _trailing_sentences(text: str, n: int = 1) -> str:
    sentences = _SENTENCE_END.split(text.strip())
    return " ".join(sentences[-n:]) if sentences else ""


def _extract_formula_latex(text: str) -> str:
    m = _LATEX_FORMULA.search(text) or _INLINE_FORMULA.search(text)
    return m.group(0).strip() if m else ""


def _find_figure_ref(text: str) -> tuple[bool, str]:
    m = _FIGURE_REF.search(text)
    if not m:
        return False, ""
    return True, (m.group(1) or m.group(2) or "").strip()


def _table_to_text(tbl: ResearchTable) -> str:
    lines = [f"[Table {tbl.table_id}: {tbl.caption}]"]
    if tbl.columns:
        lines.append(" | ".join(tbl.columns))
    for row in tbl.rows[:20]:
        lines.append(" | ".join(str(v) for v in row.values()))
    return "\n".join(lines)


def _formula_to_text(eq: ResearchEquation, parent: PaperChunk | None) -> str:
    lines = [
        f"[Equation {eq.equation_id}]",
        "LaTeX:",
        eq.latex,
    ]
    if parent is not None:
        lines.extend([
            "",
            "Context:",
            _context_excerpt(parent.content),
        ])
        if parent.section_title:
            lines.extend(["", f"Section: {parent.section_title}"])
    source_locator = eq.metadata.get("source_locator")
    if source_locator:
        lines.extend(["", f"Source: {source_locator}"])
    return "\n".join(lines)


def _context_excerpt(text: str, *, max_chars: int = 900) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip() + "..."


def _normalize_formula_text(text: str) -> str:
    stripped = text.strip()
    for prefix, suffix in (("\\[", "\\]"), ("$$", "$$"), ("$", "$")):
        if stripped.startswith(prefix) and stripped.endswith(suffix):
            stripped = stripped[len(prefix):-len(suffix)]
            break
    return re.sub(r"\s+", "", stripped).casefold()


def _locator_page(locator: Any) -> int | None:
    if not locator:
        return None
    match = _LOCATOR_PAGE_RE.search(str(locator))
    return int(match.group(1)) if match else None


def _find_formula_parent(eq: ResearchEquation, chunks: list[PaperChunk]) -> tuple[PaperChunk | None, str]:
    paragraph_chunks = [
        chunk for chunk in chunks
        if chunk.chunk_type == "paragraph" and not chunk.metadata.get("is_parent")
    ]
    if not paragraph_chunks:
        return None, "none"

    eq_latex = _normalize_formula_text(eq.latex)
    for chunk in paragraph_chunks:
        if eq_latex and (
            eq_latex == _normalize_formula_text(chunk.formula_latex)
            or eq_latex in _normalize_formula_text(chunk.content)
        ):
            return chunk, "latex_text"

    eq_page = eq.page or _locator_page(eq.metadata.get("source_locator"))
    if eq_page is not None:
        for chunk in paragraph_chunks:
            if _locator_page(chunk.metadata.get("source_locator")) == eq_page:
                return chunk, "page_locator"

    return paragraph_chunks[0], "first_paragraph_fallback"


def _stable_chunk_id(paper_id: str, *parts: str) -> str:
    return build_stable_id("chunk", paper_id, *parts)


def _normalize_semantic_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.casefold()).strip()
    return normalized


def _content_hash(text: str) -> str:
    normalized = _normalize_semantic_text(text)
    return sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _semantic_key(
    *,
    paper_id: str,
    chunk_type: ChunkType,
    section_title: str,
    source_locator: str,
    semantic_text: str,
) -> tuple[str, str, dict[str, str]]:
    title_key = _normalize_semantic_text(section_title)
    content_hash = _content_hash(semantic_text)
    parts = {
        "chunk_type": chunk_type,
        "section_title": title_key,
        "source_locator": source_locator,
        "content_hash": content_hash,
    }
    return (
        build_stable_id(
            "chunk_semantic",
            paper_id,
            chunk_type,
            title_key,
            source_locator,
            content_hash,
        ),
        content_hash,
        parts,
    )


def _chunk_metadata(
    *,
    paper_id: str,
    chunk_type: ChunkType,
    section_title: str,
    source_ref: str,
    semantic_text: str,
    source_locator: str | None = None,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(base or {})
    locator = str(source_locator or metadata.get("source_locator") or source_ref)
    semantic_key, content_hash, parts = _semantic_key(
        paper_id=paper_id,
        chunk_type=chunk_type,
        section_title=section_title,
        source_locator=locator,
        semantic_text=semantic_text,
    )
    metadata.update({
        "source_ref": source_ref,
        "source_locator": locator,
        "semantic_key": semantic_key,
        "semantic_key_parts": parts,
        "content_hash": content_hash,
    })
    return metadata


class PaperDocumentChunker:
    """
    Converts a ResearchDocument into a three-level PaperChunk hierarchy:
      abstract  → abstract chunk (+ propositions async)
      section   → parent chunk (chapter level)
      paragraph → child chunk  (retrieval unit, with 1-sentence overlap)

    Special elements (formula triplets, figure+caption, tables) are bound
    into their surrounding paragraph chunks and also emitted as standalone chunks.
    """

    def chunk(self, doc: ResearchDocument, parse_source: ParseSource) -> list[PaperChunk]:
        elements = scan_special_elements(doc)
        non_abstract = [s for s in doc.sections if not is_abstract_section(s.title)]
        structure_detected = len(non_abstract) >= _MIN_STRUCTURED_SECTIONS

        chunks: list[PaperChunk] = []
        if not structure_detected:
            chunks = self._fallback_fixed_token_chunks(doc, parse_source)
            self._add_formula_chunks(doc, parse_source, structure_detected, chunks)
            self._add_figure_chunks(doc, parse_source, structure_detected, chunks)
            self._add_table_chunks(doc, parse_source, structure_detected, chunks)
            return chunks

        self._add_abstract_chunk(doc, parse_source, structure_detected, chunks)
        self._add_section_chunks(doc, parse_source, structure_detected, non_abstract, elements, chunks)
        self._add_formula_chunks(doc, parse_source, structure_detected, chunks)
        self._add_figure_chunks(doc, parse_source, structure_detected, chunks)
        self._add_table_chunks(doc, parse_source, structure_detected, chunks)

        return chunks

    # ── private helpers ──────────────────────────────────────────────────────

    def _add_abstract_chunk(self, doc, parse_source, structure_detected, out):
        abstract = next((s for s in doc.sections if is_abstract_section(s.title)), None)
        if not abstract or not abstract.text.strip():
            return
        out.append(PaperChunk(
            chunk_id=_stable_chunk_id(doc.paper_id, "abstract"),
            paper_id=doc.paper_id,
            parse_source=parse_source,
            structure_detected=structure_detected,
            chunk_type="abstract",
            section_title=abstract.title,
            section_role=["background"],
            section_index=0,
            propositions_generated=False,
            content=abstract.text,
            metadata=_chunk_metadata(
                paper_id=doc.paper_id,
                chunk_type="abstract",
                section_title=abstract.title,
                source_ref=abstract.source_ref,
                source_locator=abstract.metadata.get("source_locator"),
                semantic_text=abstract.text,
            ),
        ))

    def _add_section_chunks(self, doc, parse_source, structure_detected, sections, elements, out):
        for idx, section in enumerate(sections):
            if not section.text.strip():
                continue  # skip blank sections — no chunk to emit
            snippet = " ".join(section.text.split()[:60])
            roles: list[SectionRole] = classify_section_role(section.title, snippet)
            cross_refs = elements.section_cross_refs.get(section.section_id, [])
            need_propositions = any(r in _PROPOSITION_ROLES for r in roles)

            # section-level parent chunk
            parent_id = _stable_chunk_id(doc.paper_id, "sec", section.section_id)
            out.append(PaperChunk(
                chunk_id=parent_id,
                paper_id=doc.paper_id,
                parse_source=parse_source,
                structure_detected=structure_detected,
                chunk_type="paragraph",
                section_title=section.title,
                section_role=roles,
                section_index=idx,
                references=cross_refs,
                content=section.text,
                metadata=_chunk_metadata(
                    paper_id=doc.paper_id,
                    chunk_type="paragraph",
                    section_title=section.title,
                    source_ref=section.source_ref,
                    source_locator=section.metadata.get("source_locator"),
                    semantic_text=section.text,
                    base={"is_parent": True, "level": section.level},
                ),
            ))

            # paragraph-level child chunks
            paragraphs = _split_paragraphs(section.text)
            for para_idx, raw_para in enumerate(paragraphs):
                para_text = raw_para
                # prepend 1-sentence overlap from previous paragraph
                if para_idx > 0:
                    overlap = _trailing_sentences(paragraphs[para_idx - 1], 1)
                    if overlap and not para_text.startswith(overlap):
                        para_text = overlap + "\n" + para_text

                has_formula = bool(_LATEX_FORMULA.search(para_text) or _INLINE_FORMULA.search(para_text))
                formula_latex = _extract_formula_latex(para_text) if has_formula else ""

                has_figure, fig_key = _find_figure_ref(para_text)
                figure_id = ""
                if has_figure and fig_key:
                    figure_id = next(
                        (fid for fid in elements.figures if fig_key.lower() in fid.lower()), ""
                    )
                    if figure_id:
                        fig = elements.figures[figure_id]
                        para_text = para_text + f"\n[{fig.figure_id}: {fig.caption}]"

                chunk_type: ChunkType = "paragraph"

                out.append(PaperChunk(
                    chunk_id=_stable_chunk_id(doc.paper_id, section.section_id, str(para_idx)),
                    paper_id=doc.paper_id,
                    parse_source=parse_source,
                    structure_detected=structure_detected,
                    chunk_type=chunk_type,
                    parent_chunk_id=parent_id,
                    section_title=section.title,
                    section_role=roles,
                    section_index=idx,
                    has_formula=has_formula,
                    formula_latex=formula_latex,
                    has_figure=has_figure,
                    figure_id=figure_id,
                    references=cross_refs,
                    propositions_generated=False if need_propositions else True,
                    content=para_text,
                    metadata=_chunk_metadata(
                        paper_id=doc.paper_id,
                        chunk_type="paragraph",
                        section_title=section.title,
                        source_ref=section.source_ref,
                        source_locator=section.metadata.get("source_locator"),
                        semantic_text=raw_para,
                        base={
                            "is_parent": False,
                            "para_index": para_idx,
                            "needs_proposition_decomposition": need_propositions,
                        },
                    ),
                ))

    def _add_formula_chunks(self, doc, parse_source, structure_detected, out):
        for eq in doc.equations:
            parent, match_strategy = _find_formula_parent(eq, out)
            section_title = parent.section_title if parent else "formula"
            section_role = parent.section_role if parent else []
            section_index = parent.section_index if parent else 0
            formula_text = _formula_to_text(eq, parent)
            out.append(PaperChunk(
                chunk_id=_stable_chunk_id(doc.paper_id, "eq", eq.equation_id),
                paper_id=doc.paper_id,
                parse_source=parse_source,
                structure_detected=structure_detected,
                chunk_type="formula",
                parent_chunk_id=parent.chunk_id if parent else None,
                section_title=section_title,
                section_role=section_role,
                section_index=section_index,
                has_formula=True,
                formula_latex=eq.latex,
                content=formula_text,
                metadata=_chunk_metadata(
                    paper_id=doc.paper_id,
                    chunk_type="formula",
                    section_title=section_title,
                    source_ref=eq.source_ref,
                    source_locator=eq.metadata.get("source_locator"),
                    semantic_text=f"{eq.equation_id}\n{eq.latex}",
                    base={
                        **eq.metadata,
                        "equation_id": eq.equation_id,
                        "page": eq.page,
                        "formula_parent_match_strategy": match_strategy,
                    },
                ),
            ))

    def _add_figure_chunks(self, doc, parse_source, structure_detected, out):
        for fig in doc.figures:
            figure_text = f"{fig.figure_id}\n{fig.caption}"
            out.append(PaperChunk(
                chunk_id=_stable_chunk_id(doc.paper_id, "fig", fig.figure_id),
                paper_id=doc.paper_id,
                parse_source=parse_source,
                structure_detected=structure_detected,
                chunk_type="figure",
                has_figure=True,
                figure_id=fig.figure_id,
                content=f"[{fig.figure_id}: {fig.caption}]",
                metadata=_chunk_metadata(
                    paper_id=doc.paper_id,
                    chunk_type="figure",
                    section_title="figure",
                    source_ref=fig.source_ref,
                    source_locator=fig.metadata.get("source_locator"),
                    semantic_text=figure_text,
                    base={
                        **fig.metadata,
                        "image_ref": fig.image_ref or "",
                    },
                ),
            ))

    def _add_table_chunks(self, doc, parse_source, structure_detected, out):
        for tbl in doc.tables:
            table_text = _table_to_text(tbl)
            out.append(PaperChunk(
                chunk_id=_stable_chunk_id(doc.paper_id, "tbl", tbl.table_id),
                paper_id=doc.paper_id,
                parse_source=parse_source,
                structure_detected=structure_detected,
                chunk_type="table",
                has_table=True,
                content=table_text,
                metadata=_chunk_metadata(
                    paper_id=doc.paper_id,
                    chunk_type="table",
                    section_title="table",
                    source_ref=tbl.source_ref,
                    source_locator=tbl.metadata.get("source_locator"),
                    semantic_text=table_text,
                    base={**tbl.metadata, "table_id": tbl.table_id},
                ),
            ))

    def _fallback_fixed_token_chunks(
        self, doc: ResearchDocument, parse_source: ParseSource, token_limit: int = 1500
    ) -> list[PaperChunk]:
        """Fixed token-window chunking for poorly structured documents (PRD §3 fallback)."""
        full_text = "\n\n".join(s.text for s in doc.sections)
        words = full_text.split()
        chunks: list[PaperChunk] = []
        source_ref = (
            doc.lineage.source_refs[0]
            if doc.lineage.source_refs
            else f"paper://{doc.paper_id}"
        )
        for chunk_idx in range(0, len(words), token_limit):
            content = " ".join(words[chunk_idx : chunk_idx + token_limit])
            chunks.append(PaperChunk(
                chunk_id=_stable_chunk_id(doc.paper_id, "fallback", str(chunk_idx // token_limit)),
                paper_id=doc.paper_id,
                parse_source=parse_source,
                structure_detected=False,
                chunk_type="paragraph",
                content=content,
                metadata=_chunk_metadata(
                    paper_id=doc.paper_id,
                    chunk_type="paragraph",
                    section_title="fallback",
                    source_ref=source_ref,
                    semantic_text=content,
                    base={"fallback": True, "chunk_index": chunk_idx // token_limit},
                ),
            ))
        return chunks


__all__ = ["PaperDocumentChunker"]
