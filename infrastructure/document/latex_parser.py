from __future__ import annotations

import io
import re
import tarfile
from hashlib import sha256
from typing import Any

from business.foundation import build_stable_id
from business.research.domain.common import SourceLineage
from business.research.domain.document import (
    ResearchDocument,
    ResearchEquation,
    ResearchFigure,
    ResearchSection,
    ResearchTable,
)

_SECTION_RE = re.compile(
    r"\\(section|subsection|subsubsection)\*?\{([^}]+)\}", re.MULTILINE
)
_EQUATION_ENV = re.compile(
    r"\\begin\{(equation|align|gather)\*?\}(.*?)\\end\{\1\*?\}", re.DOTALL
)
_INLINE_EQ = re.compile(r"\$\$(.+?)\$\$|\$([^$\n]+)\$", re.DOTALL)
_FIGURE_ENV = re.compile(
    r"\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}", re.DOTALL
)
_TABLE_ENV = re.compile(
    r"\\begin\{table\*?\}(.*?)\\end\{table\*?\}", re.DOTALL
)
_CAPTION_RE = re.compile(r"\\caption\{([^}]+)\}")
_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
_COMMENT_RE = re.compile(r"%[^\n]*")
_COMMAND_RE = re.compile(r"\\(?:textbf|textit|emph|text|mathrm|mathbf|cite|ref|url)\{([^}]*)\}")


def _strip_comments(src: str) -> str:
    return _COMMENT_RE.sub("", src)


def _flatten(src: str) -> str:
    return _COMMAND_RE.sub(r"\1", src)


def _find_main_tex(tf: tarfile.TarFile) -> str | None:
    """Return content of main .tex file (largest, or one with \\begin{document})."""
    candidates: list[tuple[int, str, str]] = []
    for member in tf.getmembers():
        if not member.name.endswith(".tex"):
            continue
        f = tf.extractfile(member)
        if f is None:
            continue
        content = f.read().decode("utf-8", errors="replace")
        if r"\begin{document}" in content:
            candidates.append((len(content), member.name, content))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][2]


class LatexDocumentParser:
    """Parse arXiv LaTeX tarball bytes into a ResearchDocument."""

    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
        src = self._extract_tex(source_bytes)
        if src is None:
            raise ValueError(f"no .tex file with \\begin{{document}} found for {paper_id}")

        src = _strip_comments(src)
        body = self._extract_body(src)
        source_hash = sha256(source_bytes).hexdigest()
        source_ref = f"arxiv://{paper_id}/latex"

        sections = self._parse_sections(body, paper_id, source_ref)
        equations = self._parse_equations(body, paper_id, source_ref)
        figures = self._parse_figures(body, paper_id, source_ref)
        tables = self._parse_tables(body, paper_id, source_ref)

        return ResearchDocument(
            paper_id=paper_id,
            source_hash=source_hash,
            sections=sections,
            equations=equations,
            figures=figures,
            tables=tables,
            lineage=SourceLineage(
                source_refs=[source_ref],
                source_hash=source_hash,
            ),
            metadata={"parse_source": "latex"},
        )

    # ── private ──────────────────────────────────────────────────────────────

    def _extract_tex(self, source_bytes: bytes) -> str | None:
        try:
            with tarfile.open(fileobj=io.BytesIO(source_bytes), mode="r:*") as tf:
                return _find_main_tex(tf)
        except tarfile.TarError:
            # single .tex file uploaded directly
            return source_bytes.decode("utf-8", errors="replace")

    def _extract_body(self, src: str) -> str:
        m = re.search(r"\\begin\{document\}(.*?)(?:\\end\{document\}|$)", src, re.DOTALL)
        return m.group(1) if m else src

    def _parse_sections(
        self, body: str, paper_id: str, source_ref: str
    ) -> list[ResearchSection]:
        sections: list[ResearchSection] = []
        _LEVEL = {"section": 1, "subsection": 2, "subsubsection": 3}

        matches = list(_SECTION_RE.finditer(body))
        for i, m in enumerate(matches):
            level = _LEVEL.get(m.group(1), 1)
            title = _flatten(m.group(2)).strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            text = _flatten(body[start:end]).strip()
            # strip nested environments to get prose only
            text = re.sub(r"\\begin\{[^}]+\}.*?\\end\{[^}]+\}", "", text, flags=re.DOTALL)
            text = re.sub(r"\s{3,}", "\n\n", text).strip()

            section_id = build_stable_id("sec", paper_id, title, str(i))
            sections.append(ResearchSection(
                section_id=section_id,
                title=title,
                level=level,
                text=text,
                source_ref=source_ref,
            ))
        return sections

    def _parse_equations(
        self, body: str, paper_id: str, source_ref: str
    ) -> list[ResearchEquation]:
        equations: list[ResearchEquation] = []
        seen: set[str] = set()
        for i, m in enumerate(_EQUATION_ENV.finditer(body)):
            latex = m.group(0).strip()
            label_m = _LABEL_RE.search(latex)
            eq_id = build_stable_id("eq", paper_id, label_m.group(1) if label_m else str(i))
            if eq_id in seen:
                continue
            seen.add(eq_id)
            equations.append(ResearchEquation(
                equation_id=eq_id,
                latex=latex,
                source_ref=source_ref,
            ))
        return equations

    def _parse_figures(
        self, body: str, paper_id: str, source_ref: str
    ) -> list[ResearchFigure]:
        figures: list[ResearchFigure] = []
        for i, m in enumerate(_FIGURE_ENV.finditer(body)):
            env = m.group(1)
            caption_m = _CAPTION_RE.search(env)
            if not caption_m:
                continue
            caption = _flatten(caption_m.group(1)).strip()
            label_m = _LABEL_RE.search(env)
            fig_id = build_stable_id("fig", paper_id, label_m.group(1) if label_m else str(i))
            figures.append(ResearchFigure(
                figure_id=fig_id,
                caption=caption,
                source_ref=source_ref,
            ))
        return figures

    def _parse_tables(
        self, body: str, paper_id: str, source_ref: str
    ) -> list[ResearchTable]:
        tables: list[ResearchTable] = []
        for i, m in enumerate(_TABLE_ENV.finditer(body)):
            env = m.group(1)
            caption_m = _CAPTION_RE.search(env)
            if not caption_m:
                continue
            caption = _flatten(caption_m.group(1)).strip()
            label_m = _LABEL_RE.search(env)
            tbl_id = build_stable_id("tbl", paper_id, label_m.group(1) if label_m else str(i))
            tables.append(ResearchTable(
                table_id=tbl_id,
                caption=caption,
                source_ref=source_ref,
            ))
        return tables


__all__ = ["LatexDocumentParser"]
