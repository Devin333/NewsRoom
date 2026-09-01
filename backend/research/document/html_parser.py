from __future__ import annotations

import re
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser

from backend.foundation import build_stable_id
from backend.research.domain.common import SourceLineage
from backend.research.domain.document import ResearchDocument, ResearchFigure, ResearchReference, ResearchSection, ResearchTable


class HtmlDocumentParser:
    """Small dependency-free HTML document adapter for paper pages."""

    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
        if not isinstance(source_bytes, bytes):
            raise TypeError("source_bytes must be bytes")
        source_hash = sha256(source_bytes).hexdigest()
        parser = _PaperHtmlParser()
        parser.feed(source_bytes.decode("utf-8", errors="replace"))
        parser.close()
        source_ref = f"paper://{paper_id}/html"
        sections: list[ResearchSection] = []
        if parser.title:
            sections.append(ResearchSection(
                section_id=build_stable_id("research_section", paper_id, "html", "title"),
                title="Title",
                level=1,
                text=parser.title,
                source_ref=f"{source_ref}#title",
                metadata={"section_type": "title"},
            ))
        for index, item in enumerate(parser.sections):
            title, text, level = item
            if not text:
                continue
            sections.append(ResearchSection(
                section_id=build_stable_id("research_section", paper_id, "html", str(index), title),
                title=title or f"Section {index + 1}",
                level=max(1, min(level, 6)),
                text=text,
                source_ref=f"{source_ref}#section={index + 1}",
                metadata={"source_locator": f"{source_ref}#section={index + 1}"},
            ))
        if not sections and parser.body_text:
            sections.append(ResearchSection(
                section_id=build_stable_id("research_section", paper_id, "html", "body"),
                title="Document",
                level=1,
                text=parser.body_text,
                source_ref=source_ref,
            ))
        tables = [
            ResearchTable(
                table_id=build_stable_id("research_table", paper_id, str(index)),
                caption=caption or f"Table {index + 1}",
                source_ref=f"{source_ref}#table={index + 1}",
                columns=columns,
                rows=rows,
            )
            for index, (caption, columns, rows) in enumerate(parser.tables)
        ]
        figures = [
            ResearchFigure(
                figure_id=build_stable_id("research_figure", paper_id, str(index)),
                caption=caption or f"Figure {index + 1}",
                source_ref=f"{source_ref}#figure={index + 1}",
                image_ref=image,
            )
            for index, (caption, image) in enumerate(parser.figures)
        ]
        return ResearchDocument(
            paper_id=paper_id,
            source_hash=source_hash,
            sections=sections,
            tables=tables,
            figures=figures,
            references=[
                ResearchReference(
                    reference_id=build_stable_id("research_reference", paper_id, str(index)),
                    title=reference,
                    source_ref=f"{source_ref}#reference={index + 1}",
                )
                for index, reference in enumerate(parser.references)
            ],
            lineage=SourceLineage(source_refs=[source_ref], source_hash=source_hash),
            metadata={
                "parse_source": "html",
                "parser_backend": "stdlib_html",
                "degraded": not bool(sections),
                "html_title": parser.title,
            },
        )


class _PaperHtmlParser(HTMLParser):
    _SECTION_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
    _SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "header", "footer"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.sections: list[tuple[str, str, int]] = []
        self.tables: list[tuple[str, list[str], list[dict[str, str]]]] = []
        self.figures: list[tuple[str, str | None]] = []
        self.references: list[str] = []
        self._tag_stack: list[str] = []
        self._skip_depth = 0
        self._current_heading: tuple[str, int] | None = None
        self._current_text: list[str] = []
        self._body_text: list[str] = []
        self._table_rows: list[list[str]] | None = None
        self._table_caption = ""
        self._table_cell: list[str] | None = None
        self._figure_caption = ""
        self._figure_src: str | None = None
        self._reference_depth = 0

    @property
    def body_text(self) -> str:
        return _clean(" ".join(self._body_text))

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        self._tag_stack.append(tag)
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._current_text = []
        elif tag in self._SECTION_TAGS:
            self._flush_heading()
            self._current_heading = ("", self._SECTION_TAGS[tag])
            self._current_text = []
        elif tag == "p":
            self._current_text = []
        elif tag == "table":
            self._table_rows = []
            self._table_caption = ""
        elif tag == "tr" and self._table_rows is not None:
            self._table_rows.append([])
        elif tag in {"th", "td"} and self._table_rows is not None:
            self._table_cell = []
        elif tag == "caption" and self._table_rows is not None:
            self._current_text = []
        elif tag == "figure":
            self._figure_caption = ""
            self._figure_src = None
        elif tag == "img":
            attrs_map = dict(attrs)
            self._figure_src = attrs_map.get("src")
        elif tag == "figcaption":
            self._current_text = []
        elif tag in {"ol", "ul"} and "reference" in " ".join(value or "" for key, value in attrs if key == "class").casefold():
            self._reference_depth += 1
        elif tag == "li" and self._reference_depth:
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self._skip_depth and tag in self._SKIP_TAGS:
            self._skip_depth -= 1
            if self._tag_stack:
                self._tag_stack.pop()
            return
        if self._skip_depth:
            if self._tag_stack:
                self._tag_stack.pop()
            return
        text = _clean(" ".join(self._current_text))
        if tag == "title" and text:
            self.title = text
        elif tag in self._SECTION_TAGS:
            if self._current_heading is not None:
                heading, level = self._current_heading
                self.sections.append((heading or text, "", level))
                self._current_heading = None
        elif tag == "p" and text:
            self._append_to_section(text)
        elif tag == "caption" and self._table_rows is not None:
            self._table_caption = text
        elif tag in {"th", "td"} and self._table_rows is not None and self._table_cell is not None:
            if self._table_rows:
                self._table_rows[-1].append(_clean(" ".join(self._table_cell)))
            self._table_cell = None
        elif tag == "table" and self._table_rows is not None:
            rows = [row for row in self._table_rows if any(row)]
            columns = rows[0] if rows else []
            data_rows = rows[1:] if len(rows) > 1 else []
            normalized = [{columns[i] if i < len(columns) and columns[i] else f"column_{i + 1}": value for i, value in enumerate(row)} for row in data_rows]
            self.tables.append((self._table_caption, columns, normalized))
            self._table_rows = None
        elif tag == "figcaption":
            self._figure_caption = text
        elif tag == "figure":
            self.figures.append((self._figure_caption, self._figure_src))
        elif tag == "li" and self._reference_depth and text:
            self.references.append(text)
        elif tag in {"ol", "ul"} and self._reference_depth:
            self._reference_depth -= 1
        self._current_text = []
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = _clean(data)
        if not text:
            return
        if self._table_cell is not None:
            self._table_cell.append(text)
        else:
            self._current_text.append(text)
            if self._current_heading is None and self._table_rows is None:
                self._body_text.append(text)

    def _flush_heading(self) -> None:
        if self._current_heading is None:
            return
        heading, level = self._current_heading
        text = _clean(" ".join(self._current_text))
        self.sections.append((heading or text, "", level))
        self._current_heading = None

    def _append_to_section(self, text: str) -> None:
        if self.sections:
            title, body, level = self.sections[-1]
            self.sections[-1] = (title, _clean(f"{body} {text}"), level)
        else:
            self.sections.append(("Document", text, 1))


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(str(value or ""))).strip()


__all__ = ["HtmlDocumentParser"]
