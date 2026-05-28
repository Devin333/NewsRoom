from __future__ import annotations

import gzip
import hashlib
import html
import io
import json
import os
import re
import shutil
import tarfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZipFile

from business.boards.paper_radar.visual_compiler.base import PaperCompileDraft, PaperCompilerError
from business.boards.paper_radar.visual_compiler.models import (
    PAPER_DOCUMENT_SCHEMA_VERSION,
    PaperAssetManifest,
    PaperBlock,
    PaperCompileInfo,
    PaperDocument,
    PaperSourceRegion,
    PaperVisualAsset,
)
from infrastructure.external.sources.arxiv import ArxivSourceConnector, ArxivSourcePackage, normalize_arxiv_id


ARXIV_SOURCE_MAX_BYTES_ENV = "NEWSROOM_ARXIV_SOURCE_MAX_BYTES"
DEFAULT_ARXIV_SOURCE_MAX_BYTES = 120_000_000

_TITLE_PATTERN = re.compile(r"\\title\s*\{(?P<body>.*?)\}", re.DOTALL)
_INPUT_PATTERN = re.compile(r"\\(?:input|include)\s*\{(?P<path>[^}]+)\}")
_BEGIN_DOCUMENT_PATTERN = re.compile(r"\\begin\s*\{document\}")
_END_DOCUMENT_PATTERN = re.compile(r"\\end\s*\{document\}")
_BEGIN_ABSTRACT_PATTERN = re.compile(r"\\begin\s*\{abstract\}")
_END_ABSTRACT_PATTERN = re.compile(r"\\end\s*\{abstract\}")
_SECTION_COMMANDS = {
    "part": 0,
    "chapter": 0,
    "section": 1,
    "subsection": 2,
    "subsubsection": 3,
    "paragraph": 4,
}
_SECTION_PATTERN = re.compile(r"\\(?P<command>part|chapter|section|subsection|subsubsection|paragraph)\*?\s*(?:\[[^\]]*\])?\s*\{(?P<title>.*?)\}", re.DOTALL)
_FOLLOWING_LABEL_PATTERN = re.compile(r"(?:\s*\\label\s*\{[^}]+\})+")
_ENV_START_PATTERN = re.compile(r"\\begin\s*\{(?P<name>[A-Za-z*]+)\}")
_ENV_END_TEMPLATE = r"\\end\s*\{{{name}\}}"
_CAPTION_PATTERN = re.compile(r"\\(?:caption|captionof)\s*(?:\{(?P<captionof>figure|table)\})?\s*(?:\[[^\]]*\])?\s*\{(?P<body>.*?)\}", re.DOTALL)
_LABEL_PATTERN = re.compile(r"\\label\s*\{(?P<label>[^}]+)\}")
_INCLUDE_GRAPHICS_PATTERN = re.compile(r"\\includegraphics(?:\s*\[[^\]]*\])?\s*\{(?P<path>[^}]+)\}", re.DOTALL)
_DISPLAY_MATH_PATTERN = re.compile(r"\\\[(?P<body>.*?)\\\]|\\\((?P<inline>.*?)\\\)", re.DOTALL)
_BLOCK_MATH_ENVS = {
    "equation",
    "equation*",
    "align",
    "align*",
    "aligned",
    "gather",
    "gather*",
    "multline",
    "multline*",
}
_FIGURE_ENVS = {"figure", "figure*", "wrapfigure"}
_TABLE_ENVS = {"table", "table*", "wraptable"}
_SKIP_ENVS = {"algorithm", "algorithmic"}
_TEXT_COMMAND_NAMES = {
    "textbf",
    "textit",
    "emph",
    "mathbf",
    "mathrm",
    "mathcal",
    "mathbb",
    "textrm",
    "text",
    "underline",
    "sout",
    "small",
    "large",
    "Large",
    "LARGE",
    "footnotesize",
    "scriptsize",
}
_COMMAND_WITH_TEXT_ARG = re.compile(
    r"\\(?:textbf|textit|emph|mathbf|mathrm|mathcal|mathbb|textrm|text|underline|sout|small|large|Large|LARGE|footnotesize|scriptsize)(?![A-Za-z])\s*\{(?P<body>.*?)\}",
    re.DOTALL,
)
_CITE_COMMAND_PATTERN = re.compile(r"~?\\(?:cite|citep|citet|citealp|citeauthor|ref|autoref|eqref|url)\*?(?:\[[^\]]*\]){0,2}\{(?P<body>[^}]*)\}")
_DOLLAR_BLOCK_MATH_PATTERN = re.compile(r"\$\$(?P<body>.*?)\$\$", re.DOTALL)
_INLINE_MATH_PATTERN = re.compile(r"\$(?P<body>(?:\\.|[^$]){1,240}?)\$")
_LATEX_COMMAND_PATTERN = re.compile(r"\\[A-Za-z]+\*?(?:\s*\[[^\]]*\])?(?:\s*\{[^{}]*\})?")
_COMMENT_PATTERN = re.compile(r"(?<!\\)%.*")
_WHITESPACE_PATTERN = re.compile(r"[ \t\r\f\v]+")
_MULTI_NEWLINE_PATTERN = re.compile(r"\n{3,}")
_PUNCT_SPACE_PATTERN = re.compile(r"\s+([,.;:!?])")
_REF_PREFIX_PATTERN = re.compile(r"^(?P<kind>fig|figure|tab|table|eq|equation|sec|section|app|appendix)[:._-]?", re.IGNORECASE)
_TABULAR_ENV_PATTERN = re.compile(
    r"\\begin\s*\{(?P<env>tabularx|tabular|array)\}\s*(?:\{[^{}]*\})?\s*\{(?P<cols>[^{}]*)\}(?P<body>.*?)\\end\s*\{(?P=env)\}",
    re.DOTALL,
)
_ROWCOLORS_PATTERN = re.compile(r"\\rowcolors\s*\{(?P<start>\d+)\}\s*\{(?P<odd>[^{}]*)\}\s*\{(?P<even>[^{}]*)\}")
_BIBLIOGRAPHY_PATTERN = re.compile(r"\\bibliography\s*\{(?P<body>[^{}]+)\}")
_BIB_ENTRY_PATTERN = re.compile(r"@(?P<kind>[A-Za-z]+)\s*\{\s*(?P<key>[^,\s]+)\s*,(?P<body>.*?)(?=\n\s*@|\Z)", re.DOTALL)
_BIB_FIELD_PATTERN = re.compile(r"(?P<name>[A-Za-z][A-Za-z0-9_-]*)\s*=\s*(?P<value>\{(?:[^{}]|\{[^{}]*\})*\}|\"(?:[^\"\\]|\\.)*\"|[^,\n]+)\s*,?", re.DOTALL)
_INLINE_TOKEN_PATTERN = re.compile(
    r"(?P<math>\$(?:\\.|[^$]){1,240}?\$)"
    r"|(?P<cite>~?\\(?:cite|citep|citet|citealp|citeauthor)\*?(?:\[[^\]]*\]){0,2}\{[^{}]*\})"
    r"|(?P<ref>~?\\(?:ref|autoref|eqref)\*?(?:\[[^\]]*\]){0,2}\{[^{}]*\})"
)
_TABLE_ASSET_CSS = """
html {
  background: #fff;
  color: #111827;
}

body {
  margin: 18px;
  font-family: Georgia, "Times New Roman", serif;
}

.paperCompiledTable {
  width: max-content;
  min-width: min(100%, 620px);
  margin: 0 auto;
  border-collapse: collapse;
  font-size: 14px;
  line-height: 1.38;
}

.paperTableCell {
  padding: 6px 12px;
  border: 0;
  vertical-align: middle;
  white-space: nowrap;
}

th.paperTableCell {
  font-weight: 700;
}

.rule-toprule > .paperTableCell {
  border-top: 2px solid #101826;
}

.rule-midrule > .paperTableCell,
.rule-cmidrule > .paperTableCell {
  border-top: 1.4px solid #313b4d;
}

.rule-bottomrule > .paperTableCell {
  border-top: 1.8px solid #101826;
}

.align-left {
  text-align: left;
}

.align-center {
  text-align: center;
}

.align-right {
  text-align: right;
}

.paperTableColorGray > .paperTableCell,
.paperTableCell.paperTableColorGray {
  background: #d8dce2;
}

.paperTableColorRed {
  color: #b42318;
}

.paperTableColorBlue {
  color: #1457b8;
}

.paperTableColorNeutral {
  color: #475467;
}

.paperTableMath {
  font-family: "Times New Roman", Georgia, serif;
  font-style: italic;
}
""".strip()


@dataclass(frozen=True)
class ArxivSourceCompileAttempt:
    available: bool
    draft: PaperCompileDraft | None = None
    diagnostics: tuple[Mapping[str, Any], ...] = ()


class ArxivSourcePaperCompiler:
    provider_name = "arxiv-source-tex-v1"

    def __init__(
        self,
        *,
        source_connector: ArxivSourceConnector | None = None,
        source_fetcher: Callable[[str, int], bytes | ArxivSourcePackage | None] | None = None,
        dpi: int = 220,
        max_source_bytes: int | None = None,
        max_visual_assets: int = 80,
    ) -> None:
        self.source_connector = source_connector or ArxivSourceConnector()
        self.source_fetcher = source_fetcher
        self.dpi = max(72, int(dpi))
        self.max_source_bytes = max_source_bytes or _max_source_bytes_from_env()
        self.max_visual_assets = max(1, int(max_visual_assets))

    def try_compile(
        self,
        *,
        paper: Mapping[str, Any],
        output_dir: Path,
        source_pdf_url: str | None = None,
        pdf_bytes: bytes | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> ArxivSourceCompileAttempt:
        arxiv_id = _arxiv_id_from_paper(paper)
        if not arxiv_id:
            return ArxivSourceCompileAttempt(
                available=False,
                diagnostics=(
                    {
                        "severity": "info",
                        "code": "arxiv_source_id_missing",
                        "message": "paper has no arXiv id for source package lookup",
                    },
                ),
            )
        try:
            package = self._fetch_source(arxiv_id)
        except Exception as exc:
            return ArxivSourceCompileAttempt(
                available=False,
                diagnostics=(
                    {
                        "severity": "warning",
                        "code": "arxiv_source_fetch_failed",
                        "message": str(exc),
                    },
                ),
            )
        try:
            return ArxivSourceCompileAttempt(
                available=True,
                draft=self.compile_source_package(
                    package=package,
                    paper=paper,
                    output_dir=output_dir,
                    source_pdf_url=source_pdf_url,
                    pdf_bytes=pdf_bytes,
                    started_at=started_at,
                    finished_at=finished_at,
                ),
            )
        except PaperCompilerError as exc:
            diagnostics = (
                {
                    "severity": "warning",
                    "code": exc.code,
                    "message": str(exc),
                },
                *exc.diagnostics,
            )
            return ArxivSourceCompileAttempt(available=True, draft=None, diagnostics=diagnostics)

    def compile_source_package(
        self,
        *,
        package: bytes | ArxivSourcePackage,
        paper: Mapping[str, Any],
        output_dir: Path,
        source_pdf_url: str | None = None,
        pdf_bytes: bytes | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> PaperCompileDraft:
        payload = package.content if isinstance(package, ArxivSourcePackage) else package
        if not payload:
            raise PaperCompilerError("arXiv source package is empty", code="arxiv_source_empty")
        started = _coerce_datetime(started_at)
        finished = _coerce_datetime(finished_at)
        paper_id = _text(paper.get("id"))
        if not paper_id:
            raise PaperCompilerError("paper id is required", code="paper_id_missing")
        arxiv_id = _arxiv_id_from_paper(paper) or (package.arxiv_id if isinstance(package, ArxivSourcePackage) else None)
        source_hash = hashlib.sha256(payload).hexdigest()

        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        source_dir = output_dir / "source"
        assets_dir = output_dir / "assets"
        pages_dir = output_dir / "pages"
        _replace_dir(source_dir)
        _replace_dir(assets_dir)
        _replace_dir(pages_dir)
        (source_dir / "source-package.bin").write_bytes(payload)
        source_pdf_file_name = None
        if pdf_bytes:
            source_pdf_path = output_dir / "source.pdf"
            source_pdf_path.write_bytes(pdf_bytes)
            source_pdf_file_name = source_pdf_path.name

        extracted_dir = source_dir / "extract"
        extracted_dir.mkdir(parents=True, exist_ok=True)
        _extract_source_payload(payload, extracted_dir)
        tex_root = _find_top_level_tex(extracted_dir)
        if tex_root is None:
            raise PaperCompilerError(
                "arXiv source package did not contain a compilable TeX root",
                code="arxiv_source_tex_missing",
            )

        expander = _TexExpander(extracted_dir)
        expanded = expander.expand(tex_root)
        body_tex = _document_body(expanded)
        if not body_tex.strip():
            raise PaperCompilerError("TeX source produced no document body", code="arxiv_source_body_empty")
        title = _clean_text(_extract_command_body(expanded, _TITLE_PATTERN)) or _text(paper.get("title")) or _text(paper.get("titleZh")) or "Untitled Paper"
        parser = _TexDocumentParser(
            paper_id=paper_id,
            root_dir=extracted_dir,
            output_dir=output_dir,
            source_hash=source_hash,
            dpi=self.dpi,
            max_visual_assets=self.max_visual_assets,
        )
        if pdf_bytes:
            parser.render_pdf_pages(pdf_bytes=pdf_bytes)
        parsed = parser.parse(body_tex)
        blocks = parsed.blocks
        assets = parsed.assets
        diagnostics = [
            {
                "severity": "info",
                "code": "arxiv_source_used",
                "message": "compiled paper body from arXiv TeX source package",
                "arxivId": arxiv_id,
                "topLevelTex": tex_root.resolve().relative_to(extracted_dir.resolve()).as_posix(),
            },
            *parsed.diagnostics,
        ]
        if not any(block.text.strip() or block.assetId for block in blocks):
            raise PaperCompilerError("TeX source produced no readable blocks", code="arxiv_source_no_blocks", diagnostics=diagnostics)
        outline = tuple(_outline_from_blocks(blocks))
        document = PaperDocument(
            paperId=paper_id,
            schemaVersion=PAPER_DOCUMENT_SCHEMA_VERSION,
            status="needs_review",
            title=title,
            compiledAt=_iso(finished),
            sourceHash=source_hash,
            paper=_public_paper_metadata(paper),
            outline=outline,
            blocks=tuple(blocks),
            auxiliary={
                **_auxiliary_metadata(paper),
                "sourceCompiler": self.provider_name,
                "sourceMapping": "synthetic",
                "references": parser.references(),
                "arxivSource": {
                    "arxivId": arxiv_id,
                    "packageChecksum": source_hash,
                    "topLevelTex": tex_root.resolve().relative_to(extracted_dir.resolve()).as_posix(),
                },
            },
        )
        manifest = PaperAssetManifest(
            paperId=paper_id,
            schemaVersion=PAPER_DOCUMENT_SCHEMA_VERSION,
            createdAt=_iso(finished),
            sourceHash=source_hash,
            assets=tuple(assets),
            sourcePdfFileName=source_pdf_file_name,
            provider=self.provider_name,
        )
        compile_info = PaperCompileInfo(
            paperId=paper_id,
            status="needs_review",
            provider=self.provider_name,
            sourceHash=source_hash,
            startedAt=_iso(started),
            finishedAt=_iso(finished),
            sourcePdfUrl=source_pdf_url,
            pageCount=len({asset.pageNumber for asset in assets if asset.kind == "page"}),
            blockCount=len(blocks),
            assetCount=len(assets),
            diagnostics=tuple(diagnostics),
        )
        return PaperCompileDraft(document=document, manifest=manifest, compile_info=compile_info)

    def _fetch_source(self, arxiv_id: str) -> ArxivSourcePackage | bytes:
        normalized_id = normalize_arxiv_id(arxiv_id)
        if self.source_fetcher is not None:
            package = self.source_fetcher(normalized_id, self.max_source_bytes)
            if package is None:
                raise ValueError("arXiv source fetcher returned no package")
            return package
        return self.source_connector.fetch_source_package(normalized_id, max_bytes=self.max_source_bytes)


class SourceFirstPaperCompiler:
    provider_name = "source-first-paper-compiler-v1"

    def __init__(
        self,
        *,
        source_compiler: ArxivSourcePaperCompiler,
        fallback_compiler: Any,
    ) -> None:
        self.source_compiler = source_compiler
        self.fallback_compiler = fallback_compiler

    def compile(
        self,
        *,
        pdf_bytes: bytes,
        paper: Mapping[str, Any],
        output_dir: Path,
        source_pdf_url: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> PaperCompileDraft:
        attempt = self.source_compiler.try_compile(
            paper=paper,
            output_dir=output_dir,
            source_pdf_url=source_pdf_url,
            pdf_bytes=pdf_bytes,
            started_at=started_at,
            finished_at=finished_at,
        )
        if attempt.draft is not None:
            return attempt.draft
        draft = self.fallback_compiler.compile(
            pdf_bytes=pdf_bytes,
            paper=paper,
            output_dir=output_dir,
            source_pdf_url=source_pdf_url,
            started_at=started_at,
            finished_at=finished_at,
        )
        diagnostics = (
            *attempt.diagnostics,
            {
                "severity": "info",
                "code": "source_first_fallback_used",
                "message": "arXiv source compiler was unavailable or failed; used PDF fallback compiler",
            },
            *draft.compile_info.diagnostics,
        )
        return PaperCompileDraft(
            document=draft.document,
            manifest=draft.manifest,
            compile_info=PaperCompileInfo(
                paperId=draft.compile_info.paperId,
                status=draft.compile_info.status,
                provider=f"{self.source_compiler.provider_name}+fallback:{draft.compile_info.provider}",
                sourceHash=draft.compile_info.sourceHash,
                startedAt=draft.compile_info.startedAt,
                finishedAt=draft.compile_info.finishedAt,
                sourcePdfUrl=draft.compile_info.sourcePdfUrl,
                pageCount=draft.compile_info.pageCount,
                blockCount=draft.compile_info.blockCount,
                assetCount=draft.compile_info.assetCount,
                diagnostics=tuple(diagnostics),
            ),
        )

    def render_source_preview(self, **kwargs: Any) -> Path:
        return self.fallback_compiler.render_source_preview(**kwargs)


@dataclass(frozen=True)
class _ParseResult:
    blocks: tuple[PaperBlock, ...]
    assets: tuple[PaperVisualAsset, ...]
    diagnostics: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class _RenderedTable:
    model: Mapping[str, Any]
    html: str
    asset_html: str
    text: str
    asset: PaperVisualAsset


@dataclass
class _LabelTarget:
    label: str
    kind: str
    display: str
    block_id: str
    section_id: str | None = None


@dataclass
class _PendingInlineBlock:
    block_index: int
    latex: str
    kind: str


@dataclass
class _PendingCaptionBlock:
    block_index: int
    latex: str


@dataclass
class _InlineChunk:
    kind: str
    text: str
    span: dict[str, Any] | None = None
    raw: str = ""


@dataclass(frozen=True)
class _CaptionCommand:
    start: int
    end: int
    body: str
    kind: str | None = None


@dataclass(frozen=True)
class _EnvironmentSpan:
    name: str
    start: int
    body_start: int
    body_end: int
    end: int


@dataclass(frozen=True)
class _VisualTexObject:
    kind: str
    body_tex: str
    caption_tex: str | None
    label: str | None
    start: int
    end: int


class _TexDocumentParser:
    def __init__(
        self,
        *,
        paper_id: str,
        root_dir: Path,
        output_dir: Path,
        source_hash: str,
        dpi: int,
        max_visual_assets: int,
    ) -> None:
        self.paper_id = paper_id
        self.root_dir = root_dir.resolve()
        self.output_dir = output_dir.resolve()
        self.assets_dir = self.output_dir / "assets"
        self.pages_dir = self.output_dir / "pages"
        self.source_hash = source_hash
        self.dpi = dpi
        self.max_visual_assets = max_visual_assets
        self.blocks: list[PaperBlock] = []
        self.assets: list[PaperVisualAsset] = []
        self.diagnostics: list[Mapping[str, Any]] = []
        self.section_id: str | None = None
        self.figure_counter = 0
        self.table_counter = 0
        self.equation_counter = 0
        self.synthetic_page = 1
        self.section_counters: list[int] = []
        self.labels: dict[str, _LabelTarget] = {}
        self.pending_inline_blocks: list[_PendingInlineBlock] = []
        self.pending_caption_blocks: list[_PendingCaptionBlock] = []
        self.bib_entries: dict[str, Mapping[str, Any]] = {}
        self.reference_numbers: dict[str, int] = {}

    def render_pdf_pages(self, *, pdf_bytes: bytes) -> None:
        try:
            import fitz  # type: ignore[import-not-found]
        except ImportError:
            return
        try:
            pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception:
            return
        try:
            for page_index, page in enumerate(pdf):
                page_number = page_index + 1
                page_file = self.pages_dir / f"page-{page_number:04d}.png"
                pixmap = page.get_pixmap(matrix=fitz.Matrix(144 / 72, 144 / 72), alpha=False)
                pixmap.save(str(page_file))
                self.assets.append(
                    _asset_from_png(
                        paper_id=self.paper_id,
                        kind="page",
                        file_path=page_file,
                        file_name=page_file.relative_to(self.output_dir).as_posix(),
                        page_number=page_number,
                        label=f"Page {page_number}",
                        caption="",
                        source=PaperSourceRegion(
                            pageNumber=page_number,
                            bbox=(0.0, 0.0, float(page.rect.width), float(page.rect.height)),
                            pageWidth=float(page.rect.width),
                            pageHeight=float(page.rect.height),
                        ),
                        pixmap=pixmap,
                        metadata={
                            "sourceProvider": "arxiv-source",
                            "sourceKind": "pdf-page-preview",
                            "dpi": 144,
                        },
                    )
                )
        finally:
            pdf.close()

    def parse(self, tex: str) -> _ParseResult:
        cleaned = _strip_comments(tex)
        self.bib_entries = _parse_bibliography_entries(cleaned, self.root_dir)
        cleaned = _remove_preamble_noise(cleaned)
        self._parse_segment(cleaned)
        self._resolve_inline_blocks()
        self._resolve_caption_blocks()
        return _ParseResult(blocks=tuple(self.blocks), assets=tuple(self.assets), diagnostics=tuple(self.diagnostics))

    def _parse_segment(self, tex: str) -> None:
        position = 0
        while position < len(tex):
            next_match = self._next_special(tex, position)
            if next_match is None:
                self._emit_text(tex[position:])
                return
            start, end, kind, payload = next_match
            self._emit_text(tex[position:start])
            if kind == "section":
                command, title, raw = payload
                self._emit_heading(command, title, raw)
            elif kind == "abstract":
                self._emit_heading("section", "Abstract", "\\begin{abstract}")
                self._parse_segment(payload)
            elif kind == "equation":
                self._emit_equation(payload)
            elif kind == "figure":
                self._emit_figure(payload)
            elif kind == "table":
                self._emit_table(payload)
            elif kind == "skip":
                self.diagnostics.append(
                    {
                        "severity": "info",
                        "code": "tex_environment_skipped",
                        "message": "unsupported TeX environment skipped from body stream",
                    }
                )
            position = end

    def _next_special(self, tex: str, position: int) -> tuple[int, int, str, Any] | None:
        candidates: list[tuple[int, int, str, Any]] = []
        section = _SECTION_PATTERN.search(tex, position)
        if section:
            raw_end = section.end()
            following_label = _FOLLOWING_LABEL_PATTERN.match(tex, raw_end)
            if following_label:
                raw_end = following_label.end()
            candidates.append((section.start(), raw_end, "section", (section.group("command"), section.group("title"), tex[section.start() : raw_end])))
        abstract = _BEGIN_ABSTRACT_PATTERN.search(tex, position)
        if abstract:
            end_match = _END_ABSTRACT_PATTERN.search(tex, abstract.end())
            if end_match:
                candidates.append((abstract.start(), end_match.end(), "abstract", tex[abstract.end() : end_match.start()]))
        display = _DISPLAY_MATH_PATTERN.search(tex, position)
        if display:
            body = display.group("body") if display.group("body") is not None else display.group("inline")
            candidates.append((display.start(), display.end(), "equation", body))
        dollar = _DOLLAR_BLOCK_MATH_PATTERN.search(tex, position)
        if dollar:
            candidates.append((dollar.start(), dollar.end(), "equation", dollar.group("body")))
        env = _ENV_START_PATTERN.search(tex, position)
        while env:
            name = env.group("name")
            end_pattern = re.compile(_ENV_END_TEMPLATE.format(name=re.escape(name)))
            end_match = end_pattern.search(tex, env.end())
            if end_match:
                body = tex[env.end() : end_match.start()]
                kind = "equation" if name in _BLOCK_MATH_ENVS else "figure" if name in _FIGURE_ENVS else "table" if name in _TABLE_ENVS else "skip" if name in _SKIP_ENVS else None
                if kind:
                    candidates.append((env.start(), end_match.end(), kind, body))
                    break
            env = _ENV_START_PATTERN.search(tex, env.end())
        return min(candidates, key=lambda item: item[0]) if candidates else None

    def _emit_heading(self, command: str, title_tex: str, raw: str) -> None:
        title = _clean_text(title_tex)
        if not title:
            return
        level = _SECTION_COMMANDS.get(command, 1)
        section_number = self._next_section_number(level) if title.casefold() != "abstract" else ""
        block_id = _stable_id(self.paper_id, "heading", str(len(self.blocks)), title)
        self.section_id = block_id
        label_key = _label_from_tex(raw)
        if label_key:
            self.labels[label_key] = _LabelTarget(
                label=label_key,
                kind="section",
                display=f"Section {section_number}" if section_number else title,
                block_id=block_id,
                section_id=block_id,
            )
        self.blocks.append(
            PaperBlock(
                id=block_id,
                paperId=self.paper_id,
                type="heading",
                text=title,
                level=level,
                pageNumber=self.synthetic_page,
                sectionId=block_id,
                source=_synthetic_source(self.synthetic_page, len(self.blocks)),
                metadata={
                    "sourceProvider": "arxiv-source",
                    "sourceKind": "tex-source",
                    "sourceMapping": "synthetic",
                    "latexCommand": command,
                    "latexLabel": label_key,
                    "sectionNumber": section_number,
                    "latex": raw[:800],
                },
            )
        )

    def _emit_text(self, tex: str) -> None:
        for paragraph_tex in _paragraph_chunks(tex):
            paragraph = _clean_text_preserving_inline(paragraph_tex)
            if not paragraph or _is_structural_noise(paragraph):
                continue
            block_id = _stable_id(self.paper_id, "paragraph", str(len(self.blocks)), paragraph[:120])
            block_index = len(self.blocks)
            self.blocks.append(
                PaperBlock(
                    id=block_id,
                    paperId=self.paper_id,
                    type="paragraph",
                    text=paragraph,
                    pageNumber=self.synthetic_page,
                    sectionId=self.section_id,
                    source=_synthetic_source(self.synthetic_page, len(self.blocks)),
                    metadata={
                        "sourceProvider": "arxiv-source",
                        "sourceKind": "tex-source",
                        "sourceMapping": "synthetic",
                        "texKind": "paragraph",
                        "latex": paragraph_tex.strip()[:1200],
                    },
                )
            )
            self.pending_inline_blocks.append(_PendingInlineBlock(block_index=block_index, latex=paragraph_tex, kind="paragraph"))

    def _emit_equation(self, body_tex: str) -> None:
        equation = _clean_equation_text(body_tex)
        if not equation:
            return
        self.equation_counter += 1
        block_id = _stable_id(self.paper_id, "equation", str(self.equation_counter), equation)
        label_key = _label_from_tex(body_tex)
        if label_key:
            self.labels[label_key] = _LabelTarget(
                label=label_key,
                kind="equation",
                display=f"Equation {self.equation_counter}",
                block_id=block_id,
                section_id=self.section_id,
            )
        self.blocks.append(
            PaperBlock(
                id=block_id,
                paperId=self.paper_id,
                type="equation",
                text=equation,
                pageNumber=self.synthetic_page,
                sectionId=self.section_id,
                label=f"Equation {self.equation_counter}",
                source=_synthetic_source(self.synthetic_page, len(self.blocks)),
                metadata={
                    "sourceProvider": "arxiv-source",
                    "sourceKind": "tex-source",
                    "sourceMapping": "synthetic",
                    "texKind": "equation",
                    "latexLabel": label_key,
                    "latex": equation,
                },
            )
        )

    def _emit_figure(self, body_tex: str) -> None:
        objects = _visual_objects_from_figure_env(body_tex)
        if len(objects) > 1:
            self._emit_visual_objects(objects)
            return
        if len(objects) == 1:
            obj = objects[0]
            if obj.kind == "table":
                self._emit_table(obj.body_tex, caption_tex=obj.caption_tex, label_key=obj.label)
                return
            body_tex = obj.body_tex
            caption_tex = obj.caption_tex
            label_key = obj.label
        else:
            caption_tex = _caption_body_from_tex(body_tex)
            label_key = _label_from_tex(body_tex)
        caption = _clean_caption_tex(caption_tex)
        include_paths = _includegraphics_paths(body_tex)
        if not include_paths:
            self.diagnostics.append(
                {
                    "severity": "warning",
                    "code": "tex_figure_without_graphics",
                    "message": "figure environment had no includegraphics path",
                    "caption": caption,
                    "label": label_key,
                }
            )
            return
        self.figure_counter += 1
        display_label = _numbered_label("Figure", self.figure_counter)
        if not caption:
            caption = display_label
        primary_path = self._resolve_graphic_path(include_paths[0])
        if primary_path is None:
            self.diagnostics.append(
                {
                    "severity": "error",
                    "code": "tex_figure_asset_missing",
                    "message": "figure graphic file referenced by TeX was not found",
                    "path": include_paths[0],
                    "label": display_label,
                }
            )
            return
        asset = self._render_visual_asset(
            source_path=primary_path,
            kind="figure",
            label=display_label,
            caption=caption,
            latex=body_tex,
            counter=self.figure_counter,
            include_paths=include_paths,
        )
        if asset is None:
            return
        block_id = _stable_id(self.paper_id, "figure-block", display_label, asset.assetId)
        if label_key:
            self.labels[label_key] = _LabelTarget(
                label=label_key,
                kind="figure",
                display=display_label,
                block_id=block_id,
                section_id=self.section_id,
            )
        block_index = len(self.blocks)
        self.blocks.append(
            PaperBlock(
                id=block_id,
                paperId=self.paper_id,
                type="figure",
                text=caption,
                pageNumber=asset.pageNumber,
                sectionId=self.section_id,
                assetId=asset.assetId,
                label=display_label,
                caption=caption,
                source=asset.source,
                metadata={
                    "sourceProvider": "arxiv-source",
                    "sourceKind": "tex-source",
                    "sourceMapping": "asset",
                    "texKind": "figure",
                    "latexLabel": label_key,
                    "latex": body_tex.strip()[:1600],
                    "includegraphics": include_paths,
                    "captionLatex": (caption_tex or "").strip()[:1200],
                },
            )
        )
        if caption_tex:
            self.pending_caption_blocks.append(_PendingCaptionBlock(block_index=block_index, latex=caption_tex))

    def _emit_visual_objects(self, objects: Sequence[_VisualTexObject]) -> None:
        for obj in objects:
            if obj.kind == "figure":
                self._emit_figure(obj.body_tex)
            elif obj.kind == "table":
                self._emit_table(obj.body_tex, caption_tex=obj.caption_tex, label_key=obj.label)

    def _emit_table(self, body_tex: str, *, caption_tex: str | None = None, label_key: str | None = None) -> None:
        effective_caption_tex = caption_tex if caption_tex is not None else _caption_body_from_tex(body_tex)
        caption = _clean_caption_tex(effective_caption_tex)
        label_key = label_key or _label_from_tex(body_tex)
        self.table_counter += 1
        display_label = _numbered_label("Table", self.table_counter)
        if not caption:
            caption = display_label
        rendered = self._render_table_asset(
            body_tex=body_tex,
            label=display_label,
            caption=caption,
            counter=self.table_counter,
        )
        if rendered is None:
            return
        asset = rendered.asset
        block_id = _stable_id(self.paper_id, "table-block", display_label, asset.assetId)
        if label_key:
            self.labels[label_key] = _LabelTarget(
                label=label_key,
                kind="table",
                display=display_label,
                block_id=block_id,
                section_id=self.section_id,
            )
        block_index = len(self.blocks)
        self.blocks.append(
            PaperBlock(
                id=block_id,
                paperId=self.paper_id,
                type="table",
                text=caption,
                pageNumber=asset.pageNumber,
                sectionId=self.section_id,
                assetId=asset.assetId,
                label=display_label,
                caption=caption,
                source=asset.source,
                metadata={
                    "sourceProvider": "arxiv-source",
                    "sourceKind": "tex-source",
                    "sourceMapping": "synthetic",
                    "texKind": "table",
                    "latexLabel": label_key,
                    "latex": body_tex.strip()[:2400],
                    "tableText": rendered.text[:2400],
                    "tableHtml": rendered.html,
                    "tableModel": rendered.model,
                    "captionLatex": (effective_caption_tex or "").strip()[:1200],
                },
            )
        )
        if effective_caption_tex:
            self.pending_caption_blocks.append(_PendingCaptionBlock(block_index=block_index, latex=effective_caption_tex))

    def _next_section_number(self, level: int) -> str:
        normalized_level = max(1, min(int(level), 6))
        while len(self.section_counters) < normalized_level:
            self.section_counters.append(0)
        self.section_counters = self.section_counters[:normalized_level]
        self.section_counters[normalized_level - 1] += 1
        return ".".join(str(item) for item in self.section_counters if item > 0)

    def _resolve_inline_blocks(self) -> None:
        next_blocks = list(self.blocks)
        for pending in self.pending_inline_blocks:
            if pending.block_index >= len(next_blocks):
                continue
            block = next_blocks[pending.block_index]
            parsed = self._inline_model_from_tex(pending.latex)
            if not parsed["text"].strip():
                continue
            metadata = dict(block.metadata)
            metadata["inlineSpans"] = parsed["spans"]
            metadata["inlineText"] = parsed["text"]
            next_blocks[pending.block_index] = PaperBlock(
                id=block.id,
                paperId=block.paperId,
                type=block.type,
                text=parsed["text"],
                level=block.level,
                pageNumber=block.pageNumber,
                sectionId=block.sectionId,
                assetId=block.assetId,
                label=block.label,
                caption=block.caption,
                source=block.source,
                metadata=metadata,
            )
        self.blocks = next_blocks

    def _resolve_caption_blocks(self) -> None:
        next_blocks = list(self.blocks)
        for pending in self.pending_caption_blocks:
            if pending.block_index >= len(next_blocks):
                continue
            block = next_blocks[pending.block_index]
            parsed = self._inline_model_from_tex(pending.latex, plain_math_text=True)
            parsed_text = str(parsed.get("text") or "").strip()
            if not parsed_text:
                continue
            metadata = dict(block.metadata)
            spans = parsed.get("spans")
            metadata["captionInlineSpans"] = spans if isinstance(spans, list) else []
            next_blocks[pending.block_index] = PaperBlock(
                id=block.id,
                paperId=block.paperId,
                type=block.type,
                text=parsed_text,
                level=block.level,
                pageNumber=block.pageNumber,
                sectionId=block.sectionId,
                assetId=block.assetId,
                label=block.label,
                caption=parsed_text,
                source=block.source,
                metadata=metadata,
            )
        self.blocks = next_blocks

    def _inline_model_from_tex(self, tex: str, *, plain_math_text: bool = False) -> Mapping[str, Any]:
        chunks: list[_InlineChunk] = []

        def append_text(raw: str) -> None:
            cleaned = _clean_text_preserving_inline(raw, strip_inline_tokens=False)
            if cleaned:
                chunks.append(_InlineChunk(kind="text", text=cleaned, raw=raw))

        position = 0
        for match in _INLINE_TOKEN_PATTERN.finditer(tex):
            append_text(tex[position:match.start()])
            token_text = ""
            token_span: dict[str, Any] | None = None
            if match.group("math"):
                raw = match.group("math")
                latex = raw[1:-1].strip()
                token_text = _inline_math_text(latex) if plain_math_text else _inline_math_fallback_text(latex)
                token_span = {
                    "type": "math",
                    "text": token_text,
                    "latex": latex,
                    "displayMode": False,
                }
            elif match.group("ref"):
                raw = match.group("ref")
                key = _command_body(raw)
                command = _latex_command_name(raw)
                target = self.labels.get(key)
                suffix_start = match.end()
                suffix = ""
                if suffix_start < len(tex) and tex[suffix_start] == "(":
                    suffix_match = re.match(r"\([A-Za-z0-9]+\)", tex[suffix_start:])
                    if suffix_match:
                        suffix = suffix_match.group(0)
                token_text = _reference_display_text(command, key, target) + suffix
                if target is None:
                    self.diagnostics.append(
                        {
                            "severity": "warning",
                            "code": "tex_reference_missing",
                            "message": "TeX reference target was not found",
                            "label": key,
                        }
                    )
                token_span = {
                    "type": "ref",
                    "text": token_text,
                    "label": key,
                    "refKind": target.kind if target else _reference_kind_from_key(command, key),
                    "targetBlockId": target.block_id if target else None,
                    "sectionId": target.section_id if target else None,
                    "display": token_text,
                }
            elif match.group("cite"):
                raw = match.group("cite")
                keys = [item.strip() for item in _command_body(raw).split(",") if item.strip()]
                citations: list[dict[str, Any]] = []
                for key in keys:
                    entry = self.bib_entries.get(key)
                    if entry is None:
                        self.diagnostics.append(
                            {
                                "severity": "warning",
                                "code": "tex_citation_missing",
                                "message": "BibTeX citation entry was not found",
                                "citationKey": key,
                            }
                        )
                        citations.append(
                            {
                                "key": key,
                                "number": None,
                                "referenceId": None,
                                "missing": True,
                            }
                        )
                        continue
                    number = self._reference_number_for_key(key)
                    citations.append(
                        {
                            "key": key,
                            "number": number,
                            "referenceId": _reference_id(key),
                        }
                    )
                token_text = _citation_display(citations)
                token_span = {
                    "type": "citation",
                    "text": token_text,
                    "citations": citations,
                }
            if token_span is not None:
                chunks.append(_InlineChunk(kind=str(token_span["type"]), text=token_text, span=token_span, raw=match.group(0)))
            position = match.end()
            if match.group("ref") and position < len(tex) and tex[position] == "(":
                suffix_match = re.match(r"\([A-Za-z0-9]+\)", tex[position:])
                if suffix_match:
                    position += len(suffix_match.group(0))
        append_text(tex[position:])
        chunks = _dedupe_reference_context(chunks)
        text, spans = _materialize_inline_chunks(chunks)
        return {"text": text, "spans": spans}

    def _reference_number_for_key(self, key: str) -> int:
        if key not in self.reference_numbers:
            self.reference_numbers[key] = len(self.reference_numbers) + 1
        return self.reference_numbers[key]

    def references(self) -> tuple[Mapping[str, Any], ...]:
        ordered = sorted(self.reference_numbers.items(), key=lambda item: item[1])
        references: list[Mapping[str, Any]] = []
        for key, number in ordered:
            entry = self.bib_entries.get(key, {})
            references.append(_reference_payload(key, number, entry))
        return tuple(references)

    def _resolve_graphic_path(self, value: str) -> Path | None:
        normalized = value.strip().strip("{}")
        candidates = [normalized]
        if not Path(normalized).suffix:
            candidates.extend(f"{normalized}{suffix}" for suffix in (".pdf", ".png", ".jpg", ".jpeg"))
        for candidate in candidates:
            path = _safe_join(self.root_dir, candidate)
            if path is not None and path.exists() and path.is_file():
                return path
        return None

    def _render_visual_asset(
        self,
        *,
        source_path: Path,
        kind: str,
        label: str,
        caption: str,
        latex: str,
        counter: int,
        include_paths: Sequence[str],
    ) -> PaperVisualAsset | None:
        if len([asset for asset in self.assets if asset.kind in {"figure", "table"}]) >= self.max_visual_assets:
            self.diagnostics.append(
                {
                    "severity": "warning",
                    "code": "tex_visual_asset_limit_reached",
                    "message": "maximum visual asset count reached for arXiv source compilation",
                    "limit": self.max_visual_assets,
                }
            )
            return None
        try:
            png_path, pixmap = _render_source_image_to_png(
                source_path=source_path,
                output_path=self.assets_dir / f"{_safe_name(kind)}-{counter:04d}-{_stable_id(label, source_path.name)[:10]}.png",
                dpi=self.dpi,
            )
        except Exception as exc:
            self.diagnostics.append(
                {
                    "severity": "error",
                    "code": "tex_visual_asset_render_failed",
                    "message": str(exc),
                    "path": source_path.relative_to(self.root_dir).as_posix(),
                    "label": label,
                }
            )
            return None
        page_number = self.synthetic_page
        source = PaperSourceRegion(
            pageNumber=page_number,
            bbox=(0.0, 0.0, float(pixmap.width), float(pixmap.height)),
            pageWidth=float(pixmap.width),
            pageHeight=float(pixmap.height),
        )
        asset = _asset_from_png(
            paper_id=self.paper_id,
            kind=kind,
            file_path=png_path,
            file_name=png_path.relative_to(self.output_dir).as_posix(),
            page_number=page_number,
            label=label,
            caption=caption,
            source=source,
            pixmap=pixmap,
            metadata={
                "sourceProvider": "arxiv-source",
                "sourceFile": source_path.relative_to(self.root_dir).as_posix(),
                "includegraphics": list(include_paths),
                "latex": latex.strip()[:1600],
                "dpi": self.dpi,
            },
        )
        self.assets.append(asset)
        return asset

    def _render_table_asset(
        self,
        *,
        body_tex: str,
        label: str,
        caption: str,
        counter: int,
    ) -> _RenderedTable | None:
        table_model = _table_model_from_tex(body_tex)
        if table_model is None:
            self.diagnostics.append(
                {
                    "severity": "error",
                    "code": "tex_table_parse_failed",
                    "message": "table environment did not contain a parseable tabular body",
                    "label": label,
                }
            )
            return None
        table_text = _table_model_text(table_model)
        table_html = _table_model_html(table_model, label=label)
        table_asset_html = _table_asset_html(table_html)
        try:
            asset = _asset_from_text_file(
                paper_id=self.paper_id,
                kind="table",
                file_path=self.assets_dir / f"table-{counter:04d}-{_stable_id(label, caption)[:10]}.html",
                content=table_asset_html,
                mime_type="text/html; charset=utf-8",
                width=_table_model_width(table_model),
                height=_table_model_height(table_model),
                page_number=self.synthetic_page,
                label=label,
                caption=caption,
                source=PaperSourceRegion(
                    pageNumber=self.synthetic_page,
                    bbox=(0.0, 0.0, float(_table_model_width(table_model)), float(_table_model_height(table_model))),
                    pageWidth=float(_table_model_width(table_model)),
                    pageHeight=float(_table_model_height(table_model)),
                ),
                output_dir=self.output_dir,
                metadata={
                    "sourceProvider": "arxiv-source",
                    "sourceKind": "tex-table-html",
                    "sourceMapping": "synthetic",
                    "latex": body_tex.strip()[:2400],
                    "tableText": table_text[:2400],
                    "tableModel": table_model,
                    "tableHtml": table_html,
                },
            )
        except Exception as exc:
            self.diagnostics.append(
                {
                    "severity": "error",
                    "code": "tex_table_asset_render_failed",
                    "message": str(exc),
                    "label": label,
                }
            )
            return None
        self.assets.append(asset)
        return _RenderedTable(model=table_model, html=table_html, asset_html=table_asset_html, text=table_text, asset=asset)


class _TexExpander:
    def __init__(self, root_dir: Path, *, max_depth: int = 24) -> None:
        self.root_dir = root_dir.resolve()
        self.max_depth = max_depth
        self._seen: set[Path] = set()

    def expand(self, root: Path) -> str:
        return self._expand_file(root.resolve(), depth=0)

    def _expand_file(self, path: Path, *, depth: int) -> str:
        if depth > self.max_depth:
            raise PaperCompilerError("TeX input nesting is too deep", code="tex_input_depth_exceeded")
        if self.root_dir not in path.parents and path != self.root_dir:
            raise PaperCompilerError("TeX input path escapes source directory", code="tex_input_path_escape")
        if path in self._seen:
            return ""
        self._seen.add(path)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1")

        def replace_input(match: re.Match[str]) -> str:
            raw = match.group("path").strip()
            child = _safe_join(path.parent, raw)
            if child is None:
                return ""
            if child.suffix == "":
                child = child.with_suffix(".tex")
            if not child.exists():
                child = _safe_join(self.root_dir, raw)
                if child is not None and child.suffix == "":
                    child = child.with_suffix(".tex")
            if child is None or not child.exists():
                return ""
            return self._expand_file(child, depth=depth + 1)

        return _INPUT_PATTERN.sub(replace_input, text)


def _extract_source_payload(payload: bytes, output_dir: Path) -> None:
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
            _safe_extract_tar(archive, output_dir)
        return
    except tarfile.TarError:
        pass
    if _looks_like_gzip(payload):
        try:
            decompressed = gzip.decompress(payload)
        except OSError:
            decompressed = b""
        try:
            with tarfile.open(fileobj=io.BytesIO(decompressed), mode="r:*") as archive:
                _safe_extract_tar(archive, output_dir)
            return
        except tarfile.TarError:
            pass
        if decompressed:
            (output_dir / "source.tex").write_bytes(decompressed)
            return
    try:
        with ZipFile(io.BytesIO(payload)) as archive:
            _safe_extract_zip(archive, output_dir)
        return
    except Exception:
        pass
    text_prefix = payload[:4096].decode("utf-8", errors="ignore")
    if "\\documentclass" in text_prefix or "\\begin{document}" in text_prefix:
        (output_dir / "source.tex").write_bytes(payload)
        return
    raise PaperCompilerError("unsupported arXiv source package format", code="arxiv_source_format_unsupported")


def _safe_extract_tar(archive: tarfile.TarFile, output_dir: Path) -> None:
    root = output_dir.resolve()
    for member in archive.getmembers():
        if not member.isfile() and not member.isdir():
            continue
        target = (output_dir / member.name).resolve()
        if root not in target.parents and target != root:
            raise PaperCompilerError("arXiv source archive contains unsafe paths", code="arxiv_source_path_escape")
    archive.extractall(output_dir, filter="data")


def _safe_extract_zip(archive: ZipFile, output_dir: Path) -> None:
    root = output_dir.resolve()
    for member in archive.infolist():
        target = (output_dir / member.filename).resolve()
        if root not in target.parents and target != root:
            raise PaperCompilerError("arXiv source archive contains unsafe paths", code="arxiv_source_path_escape")
    archive.extractall(output_dir)


def _find_top_level_tex(root: Path) -> Path | None:
    readme = root / "00README.json"
    if readme.exists():
        try:
            payload = json.loads(readme.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        for source in payload.get("sources") or []:
            if isinstance(source, Mapping) and source.get("usage") == "toplevel":
                path = _safe_join(root, str(source.get("filename") or ""))
                if path is not None and path.exists():
                    return path
    tex_files = sorted(root.rglob("*.tex"), key=lambda item: (item.name != "main.tex", item.name != "arxiv.tex", len(item.parts), item.name))
    document_files = []
    for path in tex_files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "\\begin{document}" in text:
            document_files.append(path)
    return document_files[0] if document_files else (tex_files[0] if tex_files else None)


def _document_body(tex: str) -> str:
    start = _BEGIN_DOCUMENT_PATTERN.search(tex)
    end = _END_DOCUMENT_PATTERN.search(tex)
    if start and end and end.start() > start.end():
        return tex[start.end() : end.start()]
    if start:
        return tex[start.end() :]
    return tex


def _extract_command_body(tex: str, pattern: re.Pattern[str]) -> str:
    match = pattern.search(tex)
    return match.group("body") if match else ""


def _remove_preamble_noise(tex: str) -> str:
    result = tex
    block_patterns = [
        r"\\footnotetext\s*\{.*?\}",
    ]
    line_patterns = [
        r"\\maketitle\b",
        r"\\bibliographystyle\s*\{[^}]*\}",
        r"\\bibliography\s*\{[^}]*\}",
        r"\\newpage\b",
        r"\\clearpage\b",
        r"\\appendix\b",
        r"\\vspace\s*\{[^}]*\}",
        r"\\hspace\s*\{[^}]*\}",
        r"\\centering\b",
        r"\\small\b",
        r"\\renewcommand[^\n]*",
        r"\\setcounter\s*\{[^}]*\}\s*\{[^}]*\}",
    ]
    for pattern in block_patterns:
        result = re.sub(pattern, "\n", result, flags=re.DOTALL)
    for pattern in line_patterns:
        result = re.sub(pattern, "\n", result)
    return result


def _paragraph_chunks(tex: str) -> list[str]:
    normalized = tex.replace("\\\\", "\n")
    normalized = re.sub(r"\\(?:noindent|indent)\b", "\n", normalized)
    normalized = _MULTI_NEWLINE_PATTERN.sub("\n\n", normalized)
    return [chunk.strip() for chunk in re.split(r"\n\s*\n", normalized) if chunk.strip()]


def _caption_from_tex(tex: str) -> str | None:
    return _clean_caption_tex(_caption_body_from_tex(tex))


def _caption_body_from_tex(tex: str) -> str | None:
    caption = _first_caption_command(tex)
    return caption.body if caption else None


def _clean_caption_tex(caption_tex: str | None) -> str | None:
    cleaned = _clean_text(caption_tex)
    return cleaned or None


def _label_from_tex(tex: str) -> str | None:
    match = _LABEL_PATTERN.search(tex)
    return match.group("label").strip() if match else None


def _includegraphics_paths(tex: str) -> list[str]:
    return [match.group("path").strip() for match in _INCLUDE_GRAPHICS_PATTERN.finditer(tex) if match.group("path").strip()]


def _visual_objects_from_figure_env(body_tex: str) -> list[_VisualTexObject]:
    spans = _top_level_environment_spans(body_tex, {"minipage"})
    if not spans:
        return _visual_objects_from_tex(body_tex, default_kind="figure", offset=0)
    objects: list[_VisualTexObject] = []
    for span in spans:
        child_body = body_tex[span.body_start : span.body_end]
        objects.extend(_visual_objects_from_tex(child_body, default_kind="figure", offset=span.start))
    if objects:
        return objects
    return _visual_objects_from_tex(body_tex, default_kind="figure", offset=0)


def _visual_objects_from_tex(tex: str, *, default_kind: str, offset: int) -> list[_VisualTexObject]:
    captions = _caption_commands_from_tex(tex)
    if not captions:
        obj = _visual_object_from_tex(tex, default_kind=default_kind, start=offset, end=offset + len(tex))
        return [obj] if obj is not None else []
    objects: list[_VisualTexObject] = []
    for index, caption in enumerate(captions):
        segment_start = 0 if index == 0 else caption.start
        segment_end = captions[index + 1].start if index + 1 < len(captions) else len(tex)
        segment = tex[segment_start:segment_end]
        obj = _visual_object_from_tex(segment, default_kind=default_kind, start=offset + segment_start, end=offset + segment_end)
        if obj is not None:
            objects.append(obj)
    return objects


def _visual_object_from_tex(tex: str, *, default_kind: str, start: int, end: int) -> _VisualTexObject | None:
    caption = _first_caption_command(tex)
    kind = caption.kind if caption and caption.kind else default_kind
    if kind not in {"figure", "table"}:
        kind = default_kind
    has_graphics = bool(_includegraphics_paths(tex))
    has_tabular = _TABULAR_ENV_PATTERN.search(tex) is not None
    if kind == "figure" and not has_graphics and has_tabular:
        kind = "table"
    if kind == "table" and not has_tabular and has_graphics:
        kind = "figure"
    if kind == "figure" and not has_graphics:
        return None
    if kind == "table" and not has_tabular:
        return None
    return _VisualTexObject(
        kind=kind,
        body_tex=tex,
        caption_tex=caption.body if caption else None,
        label=_label_from_tex(tex),
        start=start,
        end=end,
    )


def _top_level_environment_spans(tex: str, names: set[str]) -> list[_EnvironmentSpan]:
    spans: list[_EnvironmentSpan] = []
    position = 0
    while position < len(tex):
        match = _ENV_START_PATTERN.search(tex, position)
        if not match:
            break
        name = match.group("name")
        span = _environment_span_at(tex, match.start(), name)
        if span is None:
            position = match.end()
            continue
        if name in names:
            spans.append(span)
        position = span.end
    return spans


def _environment_span_at(tex: str, start: int, name: str) -> _EnvironmentSpan | None:
    begin_match = re.match(rf"\\begin\s*\{{{re.escape(name)}\}}", tex[start:])
    if not begin_match:
        return None
    body_start = start + begin_match.end()
    token_pattern = re.compile(rf"\\(?P<kind>begin|end)\s*\{{{re.escape(name)}\}}")
    depth = 1
    for match in token_pattern.finditer(tex, body_start):
        if match.group("kind") == "begin":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return _EnvironmentSpan(
                    name=name,
                    start=start,
                    body_start=body_start,
                    body_end=match.start(),
                    end=match.end(),
                )
    return None


def _first_caption_command(tex: str) -> _CaptionCommand | None:
    captions = _caption_commands_from_tex(tex, limit=1)
    return captions[0] if captions else None


def _caption_commands_from_tex(tex: str, *, limit: int | None = None) -> list[_CaptionCommand]:
    captions: list[_CaptionCommand] = []
    position = 0
    while True:
        match = re.search(r"\\(?P<command>captionof|caption)\b", tex[position:])
        if not match:
            return captions
        command_start = position + match.start()
        cursor = position + match.end()
        caption_kind: str | None = None
        if match.group("command") == "captionof":
            cursor = _skip_tex_space(tex, cursor)
            if cursor >= len(tex) or tex[cursor] != "{":
                position = cursor
                continue
            parsed_kind = _balanced_group(tex, cursor)
            if parsed_kind is None:
                position = cursor + 1
                continue
            caption_kind = parsed_kind[0].strip().casefold()
            cursor = parsed_kind[1]
        cursor = _skip_tex_space(tex, cursor)
        if cursor < len(tex) and tex[cursor] == "[":
            optional_end = _balanced_optional_group(tex, cursor)
            if optional_end is not None:
                cursor = _skip_tex_space(tex, optional_end)
        if cursor >= len(tex) or tex[cursor] != "{":
            position = cursor
            continue
        parsed_body = _balanced_group(tex, cursor)
        if parsed_body is None:
            position = cursor + 1
            continue
        body, end = parsed_body
        captions.append(_CaptionCommand(start=command_start, end=end, body=body, kind=caption_kind))
        if limit is not None and len(captions) >= limit:
            return captions
        position = end


def _balanced_group(tex: str, start: int) -> tuple[str, int] | None:
    if start >= len(tex) or tex[start] != "{":
        return None
    depth = 0
    body_start = start + 1
    index = start
    while index < len(tex):
        char = tex[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return tex[body_start:index], index + 1
        index += 1
    return None


def _balanced_optional_group(tex: str, start: int) -> int | None:
    if start >= len(tex) or tex[start] != "[":
        return None
    depth = 0
    index = start
    while index < len(tex):
        char = tex[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def _skip_tex_space(tex: str, position: int) -> int:
    while position < len(tex) and tex[position].isspace():
        position += 1
    return position


def _display_label(label: str | None, *, kind: str, fallback_index: int) -> str:
    if label:
        tail = _REF_PREFIX_PATTERN.sub("", label).strip()
        tail = tail.replace("_", " ").replace("-", " ").strip()
        if tail:
            if tail.isdigit() or re.fullmatch(r"[A-Za-z]?\d+[A-Za-z]?", tail):
                return f"{kind} {tail}"
            return f"{kind} {tail}"
    return f"{kind} {fallback_index}"


def _numbered_label(kind: str, index: int) -> str:
    return f"{kind} {index}"


def _clean_equation_text(tex: str) -> str:
    text = tex.strip()
    text = re.sub(r"\\label\s*\{[^}]*\}", "", text)
    text = re.sub(r"\\tag\s*\{[^}]*\}", "", text)
    text = _strip_comments(text)
    text = _WHITESPACE_PATTERN.sub(" ", text)
    text = re.sub(r"\n\s*", " ", text)
    return text.strip(" \n\t,")


def _clean_text(tex: str | None) -> str:
    if not tex:
        return ""
    text = _strip_comments(tex)
    text = _replace_caption_commands(text, lambda body: _clean_text(body))
    text = _LABEL_PATTERN.sub("", text)
    text = _INCLUDE_GRAPHICS_PATTERN.sub("", text)
    text = re.sub(r"\\(?:begin|end)\s*\{[^}]+\}", "\n", text)
    text = _CITE_COMMAND_PATTERN.sub(lambda match: _citation_replacement(match.group(0), match.group("body")), text)
    previous = None
    while previous != text:
        previous = text
        text = _replace_text_commands(text)
    text = _INLINE_MATH_PATTERN.sub(lambda match: f" {_inline_math_text(match.group('body'))} ", text)
    text = _DOLLAR_BLOCK_MATH_PATTERN.sub(" ", text)
    text = _DISPLAY_MATH_PATTERN.sub(" ", text)
    text = _latex_text_replacements(text)
    replacements = {
        r"\textasciitilde": "~",
        r"\times": "x",
        r"\pm": "+/-",
        r"\leq": "<=",
        r"\geq": ">=",
        r"\rightarrow": "->",
        r"\leftarrow": "<-",
        r"\uparrow": "up",
        r"\downarrow": "down",
        r"\dag": "dagger",
        r"\dagger": "dagger",
        r"\etal": "et al.",
        r"\eg": "e.g.",
        r"\ie": "i.e.",
        r"\etc": "etc.",
        r"\methodname": "GoToHunt",
    }
    for key, value in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(key, value)
    text = _LATEX_COMMAND_PATTERN.sub("", text)
    text = re.sub(r"[{}]", "", text)
    text = text.replace("\u00a0", " ")
    text = _WHITESPACE_PATTERN.sub(" ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = _PUNCT_SPACE_PATTERN.sub(r"\1", text)
    return text.strip()


def _clean_text_preserving_inline(tex: str | None, *, strip_inline_tokens: bool = True) -> str:
    if not tex:
        return ""
    text = _strip_comments(tex)
    text = _replace_caption_commands(text, lambda body: _clean_text_preserving_inline(body, strip_inline_tokens=strip_inline_tokens))
    text = _LABEL_PATTERN.sub("", text)
    text = _INCLUDE_GRAPHICS_PATTERN.sub("", text)
    text = re.sub(r"\\(?:begin|end)\s*\{[^}]+\}", "\n", text)
    if strip_inline_tokens:
        text = _INLINE_TOKEN_PATTERN.sub(lambda match: _inline_token_fallback_text(match.group(0)), text)
    text = _replace_text_commands(text)
    text = _latex_text_replacements(text)
    text = _LATEX_COMMAND_PATTERN.sub("", text)
    text = re.sub(r"[{}]", "", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"~+", " ", text)
    text = _WHITESPACE_PATTERN.sub(" ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = _PUNCT_SPACE_PATTERN.sub(r"\1", text)
    return text.strip()


def _inline_token_fallback_text(raw: str) -> str:
    if raw.startswith("$") and raw.endswith("$"):
        return _inline_math_fallback_text(raw[1:-1])
    command = _latex_command_name(raw)
    body = _command_body(raw)
    if command in {"cite", "citep", "citet", "citealp", "citeauthor"}:
        keys = [key.strip() for key in body.split(",") if key.strip()]
        return _citation_display([{"number": index + 1} for index, _key in enumerate(keys)]) if keys else ""
    if command in {"ref", "autoref", "eqref"}:
        return _reference_display_text(command, body, None)
    return body


def _replace_text_commands(value: str) -> str:
    text = value
    previous = None
    while previous != text:
        previous = text
        text = _strip_text_wrapping_commands_once(text)
    return text


def _latex_text_replacements(value: str) -> str:
    text = value
    text = text.replace("``", '"').replace("''", '"')
    text = text.replace("---", "-").replace("--", "-").replace("\u2014", "-").replace("\u2013", "-").replace("\u2212", "-")
    text = text.replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\\%", "%").replace("\\&", "&").replace("\\_", "_").replace("\\#", "#")
    text = text.replace("\\$", "$").replace("\\{", "{").replace("\\}", "}")
    text = _replace_latex_spacing_commands(text)
    replacements = {
        r"\textasciitilde": "~",
        r"\times": "x",
        r"\pm": "+/-",
        r"\leq": "<=",
        r"\geq": ">=",
        r"\rightarrow": "->",
        r"\leftarrow": "<-",
        r"\uparrow": "up",
        r"\downarrow": "down",
        r"\dag": "dagger",
        r"\dagger": "dagger",
        r"\etal": "et al.",
        r"\eg": "e.g.",
        r"\ie": "i.e.",
        r"\etc": "etc.",
        r"\methodname": "GoToHunt",
    }
    for key, value in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(key, value)
    return text


def _strip_text_wrapping_commands_once(value: str) -> str:
    output: list[str] = []
    position = 0
    while position < len(value):
        match = re.search(r"\\(?P<name>[A-Za-z]+)\*?", value[position:])
        if not match:
            output.append(value[position:])
            break
        command_start = position + match.start()
        command_end = position + match.end()
        name = match.group("name")
        output.append(value[position:command_start])
        if name in {"textcolor", "color"}:
            cursor = _skip_tex_space(value, command_end)
            color_group = _balanced_group(value, cursor) if cursor < len(value) and value[cursor] == "{" else None
            if color_group is None:
                output.append(value[command_start:command_end])
                position = command_end
                continue
            cursor = _skip_tex_space(value, color_group[1])
            body_group = _balanced_group(value, cursor) if cursor < len(value) and value[cursor] == "{" else None
            if body_group is None:
                output.append(value[command_start:command_end])
                position = command_end
                continue
            output.append(body_group[0])
            position = body_group[1]
            continue
        if name in _TEXT_COMMAND_NAMES:
            cursor = _skip_tex_space(value, command_end)
            body_group = _balanced_group(value, cursor) if cursor < len(value) and value[cursor] == "{" else None
            if body_group is None:
                output.append(value[command_start:command_end])
                position = command_end
                continue
            output.append(body_group[0])
            position = body_group[1]
            continue
        output.append(value[command_start:command_end])
        position = command_end
    return "".join(output)


def _replace_latex_spacing_commands(value: str) -> str:
    text = value
    text = re.sub(r"\\[,;:!]", " ", text)
    text = text.replace(r"\ ", " ")
    text = text.replace(r"~", " ")
    text = re.sub(r"\\(?:quad|qquad|enspace|thinspace|medspace|thickspace|hspace|vspace)\*?(?:\s*\{[^{}]*\})?", " ", text)
    return text


def _replace_caption_commands(value: str, replacement: Callable[[str], str]) -> str:
    text = value
    output: list[str] = []
    position = 0
    while position < len(text):
        caption = _first_caption_command(text[position:])
        if caption is None:
            output.append(text[position:])
            break
        start = position + caption.start
        end = position + caption.end
        output.append(text[position:start])
        output.append(replacement(caption.body))
        position = end
    return "".join(output)


def _needs_join_space(left: str, right: str) -> bool:
    left_tail = left[-1:] if left else ""
    right_head = right[:1] if right else ""
    if not left_tail or not right_head:
        return False
    if left_tail.isspace() or right_head.isspace():
        return False
    if right_head in ",.;:!?)]}":
        return False
    if left_tail in "([{":
        return False
    return True


def _inline_math_fallback_text(latex: str) -> str:
    normalized = _clean_equation_text(latex)
    return normalized or latex.strip()


def _command_body(raw: str) -> str:
    match = re.search(r"\{(?P<body>[^{}]*)\}\s*$", raw)
    return match.group("body").strip() if match else ""


def _latex_command_name(raw: str) -> str:
    match = re.search(r"\\(?P<name>[A-Za-z]+)\*?", raw)
    return match.group("name") if match else ""


def _reference_display_text(command: str, key: str, target: _LabelTarget | None) -> str:
    if target is not None:
        if command == "eqref" and not target.display.startswith("("):
            return f"({target.display})" if target.kind == "equation" else target.display
        return target.display
    kind = _reference_kind_from_key(command, key)
    tail = _REF_PREFIX_PATTERN.sub("", key).replace("_", " ").replace("-", " ").strip()
    if command == "eqref":
        return f"({tail or key})"
    if kind == "figure":
        return f"Figure {tail}" if tail else key
    if kind == "table":
        return f"Table {tail}" if tail else key
    if kind == "section":
        return f"Section {tail}" if tail else key
    if kind == "equation":
        return f"Equation {tail}" if tail else key
    return tail or key


def _reference_kind_from_key(command: str, key: str) -> str:
    if command == "eqref":
        return "equation"
    normalized = key.casefold()
    if normalized.startswith(("fig:", "figure:", "fig_", "figure_")):
        return "figure"
    if normalized.startswith(("tab:", "table:", "tab_", "table_")):
        return "table"
    if normalized.startswith(("sec:", "section:", "sec_", "section_")):
        return "section"
    if normalized.startswith(("eq:", "equation:", "eq_", "equation_")):
        return "equation"
    return "reference"


def _citation_display(citations: Sequence[Mapping[str, Any]]) -> str:
    if any(item.get("missing") for item in citations):
        return "[?]"
    numbers = sorted({int(item["number"]) for item in citations if isinstance(item.get("number"), int) or str(item.get("number") or "").isdigit()})
    if not numbers:
        return "[?]"
    ranges: list[str] = []
    index = 0
    while index < len(numbers):
        start = numbers[index]
        end = start
        while index + 1 < len(numbers) and numbers[index + 1] == end + 1:
            index += 1
            end = numbers[index]
        if end - start >= 2:
            ranges.append(f"{start}-{end}")
        elif end > start:
            ranges.extend(str(number) for number in range(start, end + 1))
        else:
            ranges.append(str(start))
        index += 1
    return "[" + ", ".join(ranges) + "]"


def _dedupe_reference_context(chunks: Sequence[_InlineChunk]) -> list[_InlineChunk]:
    next_chunks = [
        _InlineChunk(kind=chunk.kind, text=chunk.text, span=dict(chunk.span) if chunk.span else None, raw=chunk.raw)
        for chunk in chunks
        if chunk.text
    ]
    for index, chunk in enumerate(next_chunks):
        if chunk.kind != "ref" or not chunk.span:
            continue
        ref_kind = str(chunk.span.get("refKind") or "")
        display = str(chunk.span.get("display") or chunk.text)
        if ref_kind not in {"figure", "table", "section", "equation"}:
            continue
        previous = _previous_text_chunk(next_chunks, index)
        if previous is None:
            continue
        prefix = {
            "figure": "Figure",
            "table": "Table",
            "section": "Section",
            "equation": "Equation",
        }[ref_kind]
        plural = f"{prefix}s"
        pattern = re.compile(rf"(?P<head>(?:^|[\s(\[])(?:{re.escape(prefix)}|{re.escape(plural)}))\s*$", re.IGNORECASE)
        if pattern.search(previous.text) and display.casefold().startswith(prefix.casefold()):
            previous.text = pattern.sub(
                lambda match: match.group("head")[:-len(prefix)] if match.group("head").casefold().endswith(prefix.casefold()) else match.group("head")[:-len(plural)],
                previous.text,
            ).rstrip()
            previous.text = re.sub(r"\s+$", "", previous.text)
    return [chunk for chunk in next_chunks if chunk.text]


def _previous_text_chunk(chunks: Sequence[_InlineChunk], index: int) -> _InlineChunk | None:
    for previous_index in range(index - 1, -1, -1):
        if chunks[previous_index].kind == "text":
            return chunks[previous_index]
        if chunks[previous_index].text.strip():
            return None
    return None


def _materialize_inline_chunks(chunks: Sequence[_InlineChunk]) -> tuple[str, list[dict[str, Any]]]:
    spans: list[dict[str, Any]] = []
    output: list[str] = []
    for chunk in chunks:
        text = _normalize_inline_text(chunk.text)
        if not text:
            continue
        if output and _needs_join_space(output[-1], text):
            output.append(" ")
        start = len("".join(output))
        output.append(text)
        span = dict(chunk.span) if chunk.span else {"type": "text"}
        span["text"] = text
        span["start"] = start
        span["end"] = start + len(text)
        spans.append(span)
    text = _normalize_inline_text("".join(output))
    return text, _normalize_inline_spans(spans, text)


def _normalize_inline_text(value: str) -> str:
    text = value.replace("\u00a0", " ")
    text = _WHITESPACE_PATTERN.sub(" ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    return text.strip()


def _normalize_inline_spans(spans: Sequence[Mapping[str, Any]], text: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    cursor = 0
    for span in spans:
        span_text = str(span.get("text") or "")
        if not span_text:
            continue
        start = text.find(span_text, cursor)
        if start < 0:
            start = cursor
        end = min(len(text), start + len(span_text))
        cursor = end
        payload = dict(span)
        payload["start"] = start
        payload["end"] = end
        payload["text"] = text[start:end] or span_text
        normalized.append(payload)
    return normalized


def _citation_replacement(raw: str, body: str) -> str:
    if "\\url" in raw:
        return body
    if "\\ref" in raw or "\\autoref" in raw:
        tail = _REF_PREFIX_PATTERN.sub("", body).replace("_", " ").replace("-", " ").strip()
        return tail or body
    if "\\eqref" in raw:
        return f"({body})"
    keys = [key.strip() for key in body.split(",") if key.strip()]
    if not keys:
        return ""
    return "[" + ", ".join(keys[:3]) + (", ..." if len(keys) > 3 else "") + "]"


def _inline_math_text(body: str) -> str:
    text = _clean_equation_text(body)
    replacements = {
        r"\alpha": "alpha",
        r"\beta": "beta",
        r"\gamma": "gamma",
        r"\delta": "delta",
        r"\epsilon": "epsilon",
        r"\varepsilon": "epsilon",
        r"\lambda": "lambda",
        r"\mu": "mu",
        r"\sigma": "sigma",
        r"\tau": "tau",
        r"\theta": "theta",
        r"\phi": "phi",
        r"\psi": "psi",
        r"\omega": "omega",
        r"\Delta": "Delta",
        r"\Sigma": "Sigma",
        r"\mathcal": "",
        r"\mathbf": "",
        r"\mathrm": "",
        r"\text": "",
        r"\dag": "dagger",
        r"\dagger": "dagger",
        r"\uparrow": "up",
        r"\downarrow": "down",
        r"\pm": "+/-",
        r"\times": "x",
        r"\leq": "<=",
        r"\geq": ">=",
    }
    for key, value in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(key, value)
    text = re.sub(r"\^\s*\{?\s*dagger\s*\}?", "dagger", text)
    text = re.sub(r"\^\s*\{?\s*([A-Za-z0-9+\-/]+)\s*\}?", r"^\1", text)
    text = re.sub(r"_\s*\{?\s*([A-Za-z0-9+\-/]+)\s*\}?", r"_\1", text)
    text = _LATEX_COMMAND_PATTERN.sub("", text)
    text = re.sub(r"[{}]", "", text)
    text = _WHITESPACE_PATTERN.sub(" ", text).strip(" ,.;")
    return text


def _table_plain_text(tex: str) -> str:
    text = tex
    text = _CAPTION_PATTERN.sub("", text)
    text = _LABEL_PATTERN.sub("", text)
    text = re.sub(r"\\(?:toprule|midrule|bottomrule|cmidrule(?:\([^)]*\))?\{[^}]*\}|hline|rowcolor\{[^}]*\}|rowcolors\{[^}]*\}\{[^}]*\}\{[^}]*\})", "\n", text)
    text = re.sub(r"\\(?:resizebox|makecell|multicolumn|multirow)\s*(?:\[[^\]]*\])?\s*(?:\{[^{}]*\}){1,3}", " ", text)
    text = re.sub(r"\\begin\s*\{(?:tabular|tabularx|array|center|minipage)\}(?:\{[^}]*\})?", "\n", text)
    text = re.sub(r"\\end\s*\{(?:tabular|tabularx|array|center|minipage)\}", "\n", text)
    text = text.replace("&", " | ")
    text = text.replace("\\\\", "\n")
    lines = []
    for line in text.splitlines():
        cleaned = _clean_text(line)
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def _table_model_from_tex(tex: str) -> Mapping[str, Any] | None:
    tabular = _TABULAR_ENV_PATTERN.search(tex)
    if not tabular:
        return None
    column_spec = tabular.group("cols").strip()
    body = tabular.group("body")
    rowcolors = _rowcolors_from_tex(tex)
    rows: list[dict[str, Any]] = []
    pending_rules: list[str] = []
    for raw_row in _split_table_rows(body):
        row_tex = raw_row.strip()
        if not row_tex:
            continue
        leading = True
        while leading:
            leading = False
            for command, style in (("\\toprule", "toprule"), ("\\midrule", "midrule"), ("\\bottomrule", "bottomrule"), ("\\hline", "hline")):
                if row_tex.startswith(command):
                    pending_rules.append(style)
                    row_tex = row_tex[len(command):].strip()
                    leading = True
            cmidrule_match = re.match(r"\\cmidrule(?:\([^)]*\))?\{[^{}]*\}", row_tex)
            if cmidrule_match:
                pending_rules.append("cmidrule")
                row_tex = row_tex[cmidrule_match.end():].strip()
                leading = True
        row_color = None
        rowcolor_match = re.match(r"\\rowcolor\s*\{(?P<color>[^{}]*)\}", row_tex)
        if rowcolor_match:
            row_color = _latex_color_class(rowcolor_match.group("color"))
            row_tex = row_tex[rowcolor_match.end():].strip()
        if not row_tex:
            continue
        cells = [_cell_model_from_tex(cell) for cell in _split_table_cells(row_tex)]
        if not any(cell["text"] or cell["html"] for cell in cells):
            continue
        rows.append(
            {
                "cells": cells,
                "rulesBefore": pending_rules,
                "rowColor": row_color,
                "zebra": _zebra_row_class(len(rows), rowcolors),
            }
        )
        pending_rules = []
    if pending_rules and rows:
        rows[-1]["rulesAfter"] = pending_rules
    if not rows:
        return None
    return {
        "version": 1,
        "columnSpec": column_spec,
        "alignments": _column_alignments(column_spec),
        "rowcolors": rowcolors,
        "rows": rows,
    }


def _split_table_rows(body: str) -> list[str]:
    rows: list[str] = []
    current: list[str] = []
    depth = 0
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body) and body[index + 1] == "\\" and depth == 0:
            rows.append("".join(current))
            current = []
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
        current.append(char)
        index += 1
    if current:
        rows.append("".join(current))
    return rows


def _split_table_cells(row: str) -> list[str]:
    cells: list[str] = []
    current: list[str] = []
    depth = 0
    for char in row:
        if char == "&" and depth == 0:
            cells.append("".join(current).strip())
            current = []
            continue
        if char == "{":
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
        current.append(char)
    cells.append("".join(current).strip())
    return cells


def _cell_model_from_tex(cell_tex: str) -> dict[str, Any]:
    cell = cell_tex.strip()
    colspan = 1
    rowspan = 1
    align = None
    classes: list[str] = []
    multicolumn = re.fullmatch(r"\\multicolumn\s*\{(?P<span>\d+)\}\s*\{(?P<align>[^{}]*)\}\s*\{(?P<body>.*)\}", cell, re.DOTALL)
    if multicolumn:
        colspan = max(1, int(multicolumn.group("span")))
        align = _alignment_from_spec(multicolumn.group("align"))
        cell = multicolumn.group("body").strip()
    multirow = re.fullmatch(r"\\multirow\s*\{(?P<span>-?\d+)\}\s*\{[^{}]*\}\s*\{(?P<body>.*)\}", cell, re.DOTALL)
    if multirow:
        rowspan = max(1, abs(int(multirow.group("span"))))
        cell = multirow.group("body").strip()
    cellcolor = re.match(r"\\cellcolor\s*\{(?P<color>[^{}]*)\}(?P<body>.*)", cell, re.DOTALL)
    if cellcolor:
        color_class = _latex_color_class(cellcolor.group("color"))
        if color_class:
            classes.append(color_class)
        cell = cellcolor.group("body").strip()
    html_value = _latex_inline_html(cell)
    text_value = _clean_text(cell)
    return {
        "text": text_value,
        "html": html_value,
        "colspan": colspan,
        "rowspan": rowspan,
        "align": align,
        "classes": classes,
    }


def _latex_inline_html(tex: str) -> str:
    text = tex.strip()
    text = _CITE_COMMAND_PATTERN.sub(lambda match: html.escape(_citation_replacement(match.group(0), match.group("body"))), text)
    text = _replace_inline_command(text, "textbf", "strong")
    text = _replace_inline_command(text, "bf", "strong")
    text = _replace_inline_command(text, "textit", "em")
    text = _replace_inline_command(text, "it", "em")
    text = _replace_inline_command(text, "underline", "u")
    text = _replace_inline_command(text, "sout", "s")
    text = _replace_color_commands(text)
    text = _replace_scoped_color_declarations(text)
    text = _replace_makecell(text)
    text = _INLINE_MATH_PATTERN.sub(lambda match: f"<span class=\"paperTableMath\">{html.escape(_clean_equation_text(match.group('body')))}</span>", text)
    text = text.replace("\\\\", "<br />")
    replacements = {
        r"\uparrow": "&uarr;",
        r"\downarrow": "&darr;",
        r"\dag": "&dagger;",
        r"\dagger": "&dagger;",
        r"\%": "%",
        r"\&": "&",
        r"\_": "_",
        r"\#": "#",
    }
    for key, value in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(key, value if value.startswith("&") else html.escape(value))
    text = _LATEX_COMMAND_PATTERN.sub("", text)
    text = text.replace("{", "").replace("}", "")
    return _sanitize_table_inline_html(text).strip()


def _replace_inline_command(value: str, command: str, tag: str) -> str:
    pattern = re.compile(rf"\\{command}\s*\{{(?P<body>[^{{}}]*(?:\{{[^{{}}]*\}}[^{{}}]*)*)\}}", re.DOTALL)
    previous = None
    text = value
    while previous != text:
        previous = text
        text = pattern.sub(lambda match: f"<{tag}>{_latex_inline_html(match.group('body'))}</{tag}>", text)
    return text


def _replace_color_commands(value: str) -> str:
    text = value
    pattern = re.compile(r"\\(?:textcolor|color)\s*\{(?P<color>[^{}]*)\}\s*\{(?P<body>[^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", re.DOTALL)
    previous = None
    while previous != text:
        previous = text
        text = pattern.sub(
            lambda match: f"<span class=\"{html.escape(_latex_color_class(match.group('color')) or 'paperTableColorNeutral')}\">{_latex_inline_html(match.group('body'))}</span>",
            text,
        )
    return text


def _replace_scoped_color_declarations(value: str) -> str:
    text = value
    scoped_pattern = re.compile(
        r"\{\s*\\color\s*\{(?P<color>[^{}]*)\}\s*(?P<body>[^{}]*(?:\{[^{}]*\}[^{}]*)*)\}",
        re.DOTALL,
    )
    declaration_pattern = re.compile(r"^\\color\s*\{(?P<color>[^{}]*)\}\s*(?P<body>.+)$", re.DOTALL)

    def render(color: str, body: str) -> str:
        css_class = html.escape(_latex_color_class(color) or "paperTableColorNeutral")
        return f"<span class=\"{css_class}\">{_latex_inline_html(body)}</span>"

    previous = None
    while previous != text:
        previous = text
        text = scoped_pattern.sub(lambda match: render(match.group("color"), match.group("body")), text)

    declaration = declaration_pattern.match(text.strip())
    if declaration:
        return render(declaration.group("color"), declaration.group("body"))
    return text


def _replace_makecell(value: str) -> str:
    pattern = re.compile(r"\\makecell(?:\[[^\]]*\])?\s*\{(?P<body>[^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", re.DOTALL)
    return pattern.sub(lambda match: _latex_inline_html(match.group("body")).replace("\\\\", "<br />"), value)


def _sanitize_table_inline_html(value: str) -> str:
    allowed_patterns = (
        re.compile(r"</?(?:strong|em|u|s)>", re.IGNORECASE),
        re.compile(r"<br\s*/?>", re.IGNORECASE),
        re.compile(r"<span class=\"paperTable(?:Math|ColorRed|ColorBlue|ColorGray|ColorNeutral)\">", re.IGNORECASE),
        re.compile(r"</span>", re.IGNORECASE),
    )
    entity_pattern = re.compile(r"&(?:uarr|darr|dagger|amp|lt|gt|quot|#39);")
    tokens: dict[str, str] = {}

    def protect(pattern: re.Pattern[str], text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            token = f"@@PVC_HTML_{len(tokens)}@@"
            tokens[token] = match.group(0)
            return token

        return pattern.sub(replace, text)

    text = value
    for pattern in allowed_patterns:
        text = protect(pattern, text)
    text = protect(entity_pattern, text)
    text = html.escape(text)
    for token, original in tokens.items():
        text = text.replace(token, original)
    return text


def _rowcolors_from_tex(tex: str) -> Mapping[str, Any] | None:
    match = _ROWCOLORS_PATTERN.search(tex)
    if not match:
        return None
    return {
        "start": int(match.group("start")),
        "odd": _latex_color_class(match.group("odd")),
        "even": _latex_color_class(match.group("even")),
    }


def _zebra_row_class(index: int, rowcolors: Mapping[str, Any] | None) -> str | None:
    if not rowcolors:
        return None
    start = int(rowcolors.get("start") or 0)
    if start <= 0 or index + 1 < start:
        return None
    key = "odd" if (index + 1 - start) % 2 == 0 else "even"
    value = rowcolors.get(key)
    return str(value) if value else None


def _latex_color_class(value: str | None) -> str | None:
    normalized = (value or "").strip().casefold()
    if not normalized or normalized in {"white", "none"}:
        return None
    if "red" in normalized:
        return "paperTableColorRed"
    if "blue" in normalized:
        return "paperTableColorBlue"
    if "gray" in normalized or "grey" in normalized or "uoftcoolgray" in normalized:
        return "paperTableColorGray"
    return "paperTableColorNeutral"


def _column_alignments(spec: str) -> list[str]:
    alignments: list[str] = []
    for char in spec:
        if char in {"l", "c", "r"}:
            alignments.append({"l": "left", "c": "center", "r": "right"}[char])
    return alignments


def _alignment_from_spec(spec: str) -> str | None:
    alignments = _column_alignments(spec)
    return alignments[0] if alignments else None


def _table_model_text(model: Mapping[str, Any]) -> str:
    lines: list[str] = []
    for row in model.get("rows", []):
        if not isinstance(row, Mapping):
            continue
        cells = [
            str(cell.get("text") or "").strip()
            for cell in row.get("cells", [])
            if isinstance(cell, Mapping) and str(cell.get("text") or "").strip()
        ]
        if cells:
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _table_model_html(model: Mapping[str, Any], *, label: str) -> str:
    alignments = [str(item) for item in model.get("alignments", [])]
    rows_html: list[str] = []
    for row in model.get("rows", []):
        if not isinstance(row, Mapping):
            continue
        row_classes = ["paperTableRow"]
        row_classes.extend(f"rule-{rule}" for rule in row.get("rulesBefore", []) if isinstance(rule, str))
        row_color = row.get("rowColor") or row.get("zebra")
        if isinstance(row_color, str) and row_color:
            row_classes.append(row_color)
        cells_html: list[str] = []
        for cell_index, cell in enumerate(row.get("cells", [])):
            if not isinstance(cell, Mapping):
                continue
            tag = "th" if not rows_html else "td"
            align = cell.get("align") or (alignments[cell_index] if cell_index < len(alignments) else None)
            classes = ["paperTableCell"]
            if align in {"left", "center", "right"}:
                classes.append(f"align-{align}")
            classes.extend(str(item) for item in cell.get("classes", []) if isinstance(item, str) and item)
            attrs = [f'class="{" ".join(html.escape(item) for item in classes)}"']
            colspan = int(cell.get("colspan") or 1)
            rowspan = int(cell.get("rowspan") or 1)
            if colspan > 1:
                attrs.append(f'colspan="{colspan}"')
            if rowspan > 1:
                attrs.append(f'rowspan="{rowspan}"')
            value = str(cell.get("html") or html.escape(str(cell.get("text") or "")))
            cells_html.append(f"<{tag} {' '.join(attrs)}>{value}</{tag}>")
        rows_html.append(f"<tr class=\"{' '.join(html.escape(item) for item in row_classes)}\">{''.join(cells_html)}</tr>")
    return f"<table class=\"paperCompiledTable\" aria-label=\"{html.escape(label)}\"><tbody>{''.join(rows_html)}</tbody></table>"


def _table_asset_html(table_html: str) -> str:
    return "\n".join(
        (
            "<!doctype html>",
            "<html>",
            "<head>",
            "<meta charset=\"utf-8\" />",
            "<style>",
            _TABLE_ASSET_CSS,
            "</style>",
            "</head>",
            "<body>",
            table_html,
            "</body>",
            "</html>",
        )
    )


def _table_model_width(model: Mapping[str, Any]) -> int:
    column_count = max(
        len(model.get("alignments", []) or []),
        max((len(row.get("cells", []) or []) for row in model.get("rows", []) if isinstance(row, Mapping)), default=1),
    )
    return max(420, min(1800, column_count * 190))


def _table_model_height(model: Mapping[str, Any]) -> int:
    row_count = len([row for row in model.get("rows", []) if isinstance(row, Mapping)])
    return max(120, min(2200, row_count * 34 + 42))


def _is_structural_noise(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return True
    if normalized in {"[", "]", "{", "}"}:
        return True
    if len(normalized) <= 2 and not normalized.isalnum():
        return True
    if normalized.startswith("Squeezing Capacity") and "Technical Appendices" in normalized:
        return True
    return False


def _parse_bibliography_entries(tex: str, root_dir: Path) -> dict[str, Mapping[str, Any]]:
    entries: dict[str, Mapping[str, Any]] = {}
    bibliography_paths: list[str] = []
    for match in _BIBLIOGRAPHY_PATTERN.finditer(tex):
        bibliography_paths.extend(item.strip() for item in match.group("body").split(",") if item.strip())
    for raw_path in bibliography_paths:
        candidates = [raw_path] if raw_path.endswith(".bib") else [f"{raw_path}.bib", raw_path]
        bib_path = next((path for candidate in candidates for path in [_safe_join(root_dir, candidate)] if path is not None and path.exists()), None)
        if bib_path is None:
            continue
        try:
            content = bib_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = bib_path.read_text(encoding="latin-1")
        except OSError:
            continue
        entries.update(_parse_bib_file(content))
    return entries


def _parse_bib_file(content: str) -> dict[str, Mapping[str, Any]]:
    entries: dict[str, Mapping[str, Any]] = {}
    normalized = _strip_comments(content)
    for match in _BIB_ENTRY_PATTERN.finditer(normalized):
        key = match.group("key").strip()
        body = match.group("body")
        fields: dict[str, str] = {}
        for field in _BIB_FIELD_PATTERN.finditer(body):
            name = field.group("name").strip().casefold()
            value = _bib_field_text(field.group("value"))
            if value:
                fields[name] = value
        if key:
            entries[key] = {
                "key": key,
                "kind": match.group("kind").strip().casefold(),
                "fields": fields,
            }
    return entries


def _bib_field_text(value: str) -> str:
    text = value.strip().rstrip(",").strip()
    if (text.startswith("{") and text.endswith("}")) or (text.startswith('"') and text.endswith('"')):
        text = text[1:-1]
    text = text.replace("\n", " ")
    return _latex_to_reference_text(text)


def _latex_to_reference_text(value: str) -> str:
    text = _clean_text_preserving_inline(value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _reference_id(key: str) -> str:
    return f"ref-{_safe_name(key).lower()}"


def _reference_payload(key: str, number: int, entry: Mapping[str, Any]) -> Mapping[str, Any]:
    fields = entry.get("fields") if isinstance(entry.get("fields"), Mapping) else {}
    title = str(fields.get("title") or "").strip()
    authors = str(fields.get("author") or "").strip()
    year = str(fields.get("year") or "").strip()
    venue = str(fields.get("journal") or fields.get("booktitle") or fields.get("publisher") or fields.get("archiveprefix") or "").strip()
    doi = str(fields.get("doi") or "").strip()
    url = str(fields.get("url") or "").strip()
    parts = []
    if authors:
        parts.append(authors)
    if title:
        parts.append(title)
    if venue:
        parts.append(venue)
    if year:
        parts.append(year)
    if doi:
        parts.append(f"doi:{doi}")
    if url:
        parts.append(url)
    text = ". ".join(part.strip(" .") for part in parts if part.strip(" ."))
    if text and not text.endswith("."):
        text = f"{text}."
    return {
        "id": _reference_id(key),
        "key": key,
        "number": number,
        "label": f"[{number}]",
        "title": title,
        "authors": _split_bib_authors(authors),
        "year": year,
        "venue": venue,
        "doi": doi,
        "url": url,
        "text": text or key,
        "missing": not bool(entry),
    }


def _split_bib_authors(value: str) -> list[str]:
    if not value:
        return []
    return [author.strip() for author in re.split(r"\s+and\s+", value) if author.strip()]


def _render_source_image_to_png(*, source_path: Path, output_path: Path, dpi: int) -> tuple[Path, Any]:
    import fitz  # type: ignore[import-not-found]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = source_path.suffix.casefold()
    if suffix == ".pdf":
        document = fitz.open(source_path)
        try:
            if len(document) == 0:
                raise ValueError("source figure PDF has no pages")
            page = document[0]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
            pixmap.save(str(output_path))
            return output_path, pixmap
        finally:
            document.close()
    pixmap = fitz.Pixmap(str(source_path))
    if pixmap.alpha:
        pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
    pixmap.save(str(output_path))
    return output_path, pixmap


def _render_text_asset_to_png(*, text: str, output_path: Path, title: str) -> tuple[Path, Any]:
    import fitz  # type: ignore[import-not-found]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [title, ""]
    for raw_line in text.splitlines() or [text]:
        lines.extend(_wrap_text(raw_line, width=96))
    line_height = 18
    width = 1200
    height = max(180, min(2200, 48 + len(lines) * line_height))
    document = fitz.open()
    try:
        page = document.new_page(width=width, height=height)
        page.draw_rect(fitz.Rect(0, 0, width, height), fill=(1, 1, 1), color=(1, 1, 1))
        y = 28
        for index, line in enumerate(lines):
            if not line:
                y += line_height // 2
                continue
            fontsize = 14 if index == 0 else 11
            fontname = "helv" if index == 0 else "cour"
            page.insert_text((28, y), line[:150], fontsize=fontsize, fontname=fontname, color=(0.08, 0.08, 0.08))
            y += line_height
            if y > height - 20:
                break
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        pixmap.save(str(output_path))
        return output_path, pixmap
    finally:
        document.close()


def _asset_from_png(
    *,
    paper_id: str,
    kind: str,
    file_path: Path,
    file_name: str,
    page_number: int,
    label: str,
    caption: str,
    source: PaperSourceRegion,
    pixmap: Any,
    metadata: Mapping[str, Any],
) -> PaperVisualAsset:
    data = file_path.read_bytes()
    asset_id = _stable_id(paper_id, "asset", kind, label, file_name)
    if kind == "page":
        asset_id = _stable_id(paper_id, "asset", kind, str(page_number), file_name)
    return PaperVisualAsset(
        assetId=asset_id,
        paperId=paper_id,
        kind=kind,  # type: ignore[arg-type]
        fileName=file_name,
        mimeType="image/png",
        width=int(pixmap.width),
        height=int(pixmap.height),
        checksum=hashlib.sha256(data).hexdigest(),
        pageNumber=page_number,
        label=label,
        caption=caption,
        source=source,
        blankRatio=_pixmap_blank_ratio(pixmap),
        fileSize=len(data),
        metadata=dict(metadata),
    )


def _asset_from_text_file(
    *,
    paper_id: str,
    kind: str,
    file_path: Path,
    content: str,
    mime_type: str,
    width: int,
    height: int,
    page_number: int,
    label: str,
    caption: str,
    source: PaperSourceRegion,
    output_dir: Path,
    metadata: Mapping[str, Any],
) -> PaperVisualAsset:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    data = file_path.read_bytes()
    file_name = file_path.relative_to(output_dir).as_posix()
    return PaperVisualAsset(
        assetId=_stable_id(paper_id, "asset", kind, label, file_name),
        paperId=paper_id,
        kind=kind,  # type: ignore[arg-type]
        fileName=file_name,
        mimeType=mime_type,
        width=max(1, int(width)),
        height=max(1, int(height)),
        checksum=hashlib.sha256(data).hexdigest(),
        pageNumber=page_number,
        label=label,
        caption=caption,
        source=source,
        blankRatio=0.0,
        fileSize=len(data),
        metadata=dict(metadata),
    )


def _strip_comments(value: str) -> str:
    return "\n".join(_COMMENT_PATTERN.sub("", line) for line in value.splitlines())


def _safe_join(root: Path, relative: str) -> Path | None:
    if not relative:
        return None
    pure = PurePosixPath(relative.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        return None
    try:
        resolved = (root / Path(*pure.parts)).resolve()
    except OSError:
        return None
    root_resolved = root.resolve()
    if root_resolved not in resolved.parents and resolved != root_resolved:
        return None
    return resolved


def _replace_dir(path: Path) -> None:
    if path.name not in {"source", "assets", "pages"}:
        raise PaperCompilerError("refusing to replace unexpected artifact directory", code="artifact_path_unexpected")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _looks_like_gzip(payload: bytes) -> bool:
    return len(payload) >= 2 and payload[:2] == b"\x1f\x8b"


def _outline_from_blocks(blocks: Sequence[PaperBlock]) -> list[Mapping[str, Any]]:
    return [
        {
            "id": block.id,
            "title": block.text,
            "level": block.level or 1,
            "pageNumber": block.pageNumber,
            "blockId": block.id,
        }
        for block in blocks
        if block.type == "heading" and block.text.strip()
    ]


def _public_paper_metadata(paper: Mapping[str, Any]) -> Mapping[str, Any]:
    allowed = (
        "id",
        "slug",
        "title",
        "titleZh",
        "authors",
        "publishedAt",
        "venue",
        "paperUrl",
        "pdfUrl",
        "arxivId",
        "arxivUrl",
        "tags",
        "taskRefs",
        "methodRefs",
        "thumbnailUrl",
    )
    return {key: paper[key] for key in allowed if key in paper and paper[key] not in (None, "", [], {})}


def _auxiliary_metadata(paper: Mapping[str, Any]) -> Mapping[str, Any]:
    keys = (
        "aiSummary",
        "abstractSnippet",
        "abstractSnippetZh",
        "implementations",
        "benchmarks",
        "evidenceRefs",
        "sourceRefs",
    )
    return {key: paper[key] for key in keys if key in paper and paper[key] not in (None, "", [], {})}


def _synthetic_source(page_number: int, index: int) -> PaperSourceRegion:
    y0 = float(24 + index * 18)
    return PaperSourceRegion(
        pageNumber=page_number,
        bbox=(24.0, y0, 588.0, y0 + 14.0),
        pageWidth=612.0,
        pageHeight=792.0,
    )


def _pixmap_blank_ratio(pixmap: Any) -> float:
    samples = bytes(pixmap.samples)
    channels = max(1, int(getattr(pixmap, "n", 3) or 3))
    if not samples or channels < 3:
        return 1.0
    pixel_count = len(samples) // channels
    if pixel_count <= 0:
        return 1.0
    step = max(1, pixel_count // 30_000)
    sampled = 0
    blank = 0
    for pixel_index in range(0, pixel_count, step):
        offset = pixel_index * channels
        r, g, b = samples[offset], samples[offset + 1], samples[offset + 2]
        if r >= 248 and g >= 248 and b >= 248:
            blank += 1
        sampled += 1
    return blank / sampled if sampled else 1.0


def _wrap_text(value: str, *, width: int) -> list[str]:
    words = value.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= width:
            current = f"{current} {word}"
            continue
        lines.append(current)
        current = word
    lines.append(current)
    return lines


def _arxiv_id_from_paper(paper: Mapping[str, Any]) -> str | None:
    for key in ("arxivId", "arxivUrl", "paperUrl", "pdfUrl"):
        value = _text(paper.get(key))
        if not value:
            continue
        normalized = normalize_arxiv_id(value)
        if normalized:
            return normalized
    return None


def _max_source_bytes_from_env() -> int:
    value = os.environ.get(ARXIV_SOURCE_MAX_BYTES_ENV)
    if not value:
        return DEFAULT_ARXIV_SOURCE_MAX_BYTES
    try:
        parsed = int(value)
    except ValueError:
        return DEFAULT_ARXIV_SOURCE_MAX_BYTES
    return parsed if parsed > 0 else DEFAULT_ARXIV_SOURCE_MAX_BYTES


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-") or "asset"


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _coerce_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
