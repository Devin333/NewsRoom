from __future__ import annotations

import gzip
import io
import re
import tarfile
from hashlib import sha256
from typing import IO

from business.foundation import build_stable_id
from business.research.document.section_detector import is_boilerplate_section
from business.research.domain.common import SourceLineage
from business.research.domain.document import (
    ResearchDocument,
    ResearchEquation,
    ResearchFigure,
    ResearchSection,
    ResearchTable,
)
from business.research.domain.paper import PaperSourceRecord

# ── regex patterns ────────────────────────────────────────────────────────────

_SEC_RE = re.compile(
    r"\\(section|subsection|subsubsection)\*?\{([^}]+)\}",
    re.MULTILINE,
)
_ABSTRACT_ENV = re.compile(
    r"\\begin\{abstract\}(.*?)\\end\{abstract\}",
    re.DOTALL,
)
_ENV_RE = re.compile(
    r"\\begin\{(equation|align|gather|figure|table|tabular)[*]?\}(.*?)\\end\{\1[*]?\}",
    re.DOTALL,
)
# Only figure/table environments are stripped from section body text;
# equation/align/gather are kept inline so the chunker can detect them.
_NON_FORMULA_ENV_RE = re.compile(
    r"\\begin\{(figure|table|tabular)[*]?\}(.*?)\\end\{\1[*]?\}",
    re.DOTALL,
)
_CAPTION_RE = re.compile(r"\\caption\{([^}]+)\}")
_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
_COMMENT_RE = re.compile(r"(?m)%.*$")
_FORMULA_ENV_RE = re.compile(
    r"(\\begin\{(?:equation|align|gather)[*]?\}.*?\\end\{(?:equation|align|gather)[*]?\}|\$\$[^$]+\$\$|\$[^$\n]+\$)",
    re.DOTALL,
)
_CMD_RE = re.compile(r"\\(?:textbf|textit|emph|text|mathrm|mathbf|mathcal)\{([^}]+)\}")
_BRACES_RE = re.compile(r"\\[a-zA-Z]+\{([^}]*)\}")
_BACKSLASH_CMD_RE = re.compile(r"\\[a-zA-Z]+\s*")
_MULTI_WS_RE = re.compile(r"[ \t]{2,}")
_INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")


def _strip_comments(tex: str) -> str:
    return _COMMENT_RE.sub("", tex)


def _clean_text(tex: str) -> str:
    """Clean LaTeX prose (no formula environments)."""
    text = _CMD_RE.sub(r"\1", tex)
    text = _BRACES_RE.sub(r"\1", text)
    text = _BACKSLASH_CMD_RE.sub(" ", text)
    text = text.replace("{", "").replace("}", "").replace("$", "")
    return _MULTI_WS_RE.sub(" ", text).strip()


def _build_section_text(body: str) -> str:
    """Keep formula environments as raw LaTeX; clean surrounding prose."""
    parts = _FORMULA_ENV_RE.split(body)
    result: list[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 0:  # prose segment
            cleaned = _clean_text(part)
            if cleaned:
                result.append(cleaned)
        else:  # formula segment (kept verbatim for chunker detection)
            result.append(part.strip())
    return "\n".join(result)


def _resolve_inputs(tex: str, files: dict[str, str], depth: int = 0) -> str:
    if depth > 5:
        return tex

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        name = m.group(1).strip()
        for candidate in (name, name + ".tex", name.lstrip("./") + ".tex"):
            if candidate in files:
                return _resolve_inputs(files[candidate], files, depth + 1)
        return ""

    return _INPUT_RE.sub(_replace, tex)


def _find_main_tex(files: dict[str, str]) -> str | None:
    """Return the content of the main .tex file."""
    # prefer a file containing \documentclass
    for name, content in files.items():
        if r"\documentclass" in content:
            return content
    # fallback: the largest .tex file
    tex_files = {k: v for k, v in files.items() if k.endswith(".tex")}
    if not tex_files:
        return None
    return max(tex_files.values(), key=len)


def _read_tex_files(data: bytes) -> dict[str, str] | None:
    """Extract all .tex files from a tar.gz (or raw .tex) archive."""
    files: dict[str, str] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for member in tf.getmembers():
                if member.name.endswith(".tex") and member.isfile():
                    f: IO[bytes] | None = tf.extractfile(member)
                    if f:
                        files[member.name.lstrip("./")] = f.read().decode("utf-8", errors="replace")
    except (tarfile.TarError, gzip.BadGzipFile, EOFError):
        # maybe it's a raw .tex file or a plain gzip
        try:
            text = gzip.decompress(data).decode("utf-8", errors="replace")
            if r"\documentclass" in text or r"\section" in text:
                files["main.tex"] = text
        except Exception:
            try:
                text = data.decode("utf-8", errors="replace")
                if r"\section" in text:
                    files["main.tex"] = text
            except Exception:
                return None
    return files or None


def _parse_sections(tex: str, source_ref: str, paper_id: str) -> list[ResearchSection]:
    tex_clean = _strip_comments(tex)
    # extract abstract separately
    sections: list[ResearchSection] = []
    abs_m = _ABSTRACT_ENV.search(tex_clean)
    if abs_m:
        sections.append(ResearchSection(
            section_id=build_stable_id("sec", paper_id, "abstract"),
            title="Abstract",
            level=1,
            text=_clean_text(abs_m.group(1)),
            source_ref=source_ref,
        ))

    # split by \section / \subsection
    matches = list(_SEC_RE.finditer(tex_clean))
    for i, m in enumerate(matches):
        level = {"section": 1, "subsection": 2, "subsubsection": 3}[m.group(1)]
        title = _clean_text(m.group(2))
        if not title:
            continue
        if is_boilerplate_section(title):
            continue  # acknowledgments / funding / references / appendix → not retrieval content
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(tex_clean)
        body = tex_clean[start:end]
        # strip figure/table; keep equation environments as raw LaTeX (PRD §2 formula triplet)
        body_text = _NON_FORMULA_ENV_RE.sub("", body)
        text = _build_section_text(body_text)
        if not text.strip():
            continue
        sections.append(ResearchSection(
            section_id=build_stable_id("sec", paper_id, title, str(i)),
            title=title,
            level=level,
            text=text,
            source_ref=source_ref,
        ))
    return sections


def _parse_equations(tex: str, source_ref: str, paper_id: str) -> list[ResearchEquation]:
    tex_clean = _strip_comments(tex)
    equations: list[ResearchEquation] = []
    for i, m in enumerate(_ENV_RE.finditer(tex_clean)):
        if m.group(1) not in ("equation", "align", "gather"):
            continue
        label_m = _LABEL_RE.search(m.group(2))
        eq_id = label_m.group(1) if label_m else f"eq_{i}"
        equations.append(ResearchEquation(
            equation_id=build_stable_id("eq", paper_id, eq_id),
            latex=m.group(0).strip(),
            source_ref=source_ref,
        ))
    return equations


def _parse_figures(tex: str, source_ref: str, paper_id: str) -> list[ResearchFigure]:
    tex_clean = _strip_comments(tex)
    figures: list[ResearchFigure] = []
    for i, m in enumerate(_ENV_RE.finditer(tex_clean)):
        if m.group(1) != "figure":
            continue
        label_m = _LABEL_RE.search(m.group(2))
        caption_m = _CAPTION_RE.search(m.group(2))
        if not caption_m:
            continue
        caption = _clean_text(caption_m.group(1))
        if not caption:
            continue
        fig_id = label_m.group(1) if label_m else f"fig_{i}"
        figures.append(ResearchFigure(
            figure_id=build_stable_id("fig", paper_id, fig_id),
            caption=caption,
            source_ref=source_ref,
        ))
    return figures


def _parse_tables(tex: str, source_ref: str, paper_id: str) -> list[ResearchTable]:
    tex_clean = _strip_comments(tex)
    tables: list[ResearchTable] = []
    for i, m in enumerate(_ENV_RE.finditer(tex_clean)):
        if m.group(1) != "table":
            continue
        label_m = _LABEL_RE.search(m.group(2))
        caption_m = _CAPTION_RE.search(m.group(2))
        if not caption_m:
            continue
        caption = _clean_text(caption_m.group(1))
        if not caption:
            continue
        tbl_id = label_m.group(1) if label_m else f"tbl_{i}"
        tables.append(ResearchTable(
            table_id=build_stable_id("tbl", paper_id, tbl_id),
            caption=caption,
            source_ref=source_ref,
        ))
    return tables


def _normalize_arxiv_id(value: str) -> str:
    """Extract a bare arXiv id from a URL or raw id (no infrastructure dependency)."""
    text = value.strip().rstrip(".,;:)]}>'\"")
    for marker in ("arxiv.org/abs/", "arxiv.org/pdf/", "arxiv.org/e-print/", "arxiv.org/src/"):
        if marker in text:
            text = text.rsplit(marker, 1)[-1]
            break
    if text.endswith(".pdf"):
        text = text[:-4]
    return text.split("?", 1)[0].split("#", 1)[0].strip("/")


def _build_document(paper_id: str, source_ref: str, source_hash: str, content: bytes, *, arxiv_id: str | None = None) -> ResearchDocument:
    files = _read_tex_files(content)
    if not files:
        raise ValueError(f"no .tex files found in LaTeX source package for {paper_id}")
    main_tex = _find_main_tex(files)
    if not main_tex:
        raise ValueError(f"could not identify main .tex file for {paper_id}")
    resolved = _resolve_inputs(_strip_comments(main_tex), files)
    meta = {"parse_source": "latex"}
    if arxiv_id:
        meta["arxiv_id"] = arxiv_id
    return ResearchDocument(
        paper_id=paper_id,
        source_hash=source_hash,
        sections=_parse_sections(resolved, source_ref, paper_id),
        equations=_parse_equations(resolved, source_ref, paper_id),
        figures=_parse_figures(resolved, source_ref, paper_id),
        tables=_parse_tables(resolved, source_ref, paper_id),
        lineage=SourceLineage(source_refs=[source_ref], source_hash=source_hash),
        metadata=meta,
    )


class LatexSourceParser:
    """Implements DocumentParserPort: parse raw LaTeX tarball bytes → ResearchDocument."""

    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
        return _build_document(
            paper_id=paper_id,
            source_ref=f"arxiv://{paper_id}/latex",
            source_hash=sha256(source_bytes).hexdigest(),
            content=source_bytes,
        )


class ArxivLatexDocumentCompiler:
    """
    Implements DocumentCompilerPort for arXiv LaTeX sources.
    Fetches the .tar.gz source via an injected SourceFetcherPort, then parses
    LaTeX into a ResearchDocument.
    """

    def __init__(self, source_fetcher) -> None:  # SourceFetcherPort
        self._fetcher = source_fetcher

    def compile(self, source: PaperSourceRecord) -> ResearchDocument:
        arxiv_id = _normalize_arxiv_id(source.source_url)
        if not arxiv_id:
            raise ValueError(f"cannot derive arxiv id from source_url: {source.source_url}")

        pkg = self._fetcher.fetch_source_package(arxiv_id)
        return _build_document(
            paper_id=source.paper_id,
            source_ref=f"arxiv://{arxiv_id}",
            source_hash=pkg.checksum,
            content=pkg.content,
            arxiv_id=arxiv_id,
        )


__all__ = ["ArxivLatexDocumentCompiler", "LatexSourceParser"]
