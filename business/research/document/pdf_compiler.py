from __future__ import annotations

import os
import re
import subprocess
import tempfile
from hashlib import sha256

import fitz  # PyMuPDF

from business.foundation import build_stable_id
from business.research.domain.common import SourceLineage
from business.research.domain.document import (
    ResearchDocument,
    ResearchEquation,
    ResearchFigure,
    ResearchSection,
)

# ── figures ───────────────────────────────────────────────────────────────────


def _figures_dir(paper_id: str) -> str:
    root = os.environ.get("NEWS_ARTIFACT_ROOT", ".newsroom/runs")
    return os.path.join(os.path.dirname(root), "papers", paper_id, "figures")


def _extract_pdf_images(pdf_doc: fitz.Document, paper_id: str) -> list[str]:
    """Extract images from PDF pages, save to figures dir.

    Returns paths in appearance order (page order, deduplicated by xref).
    Skips images smaller than 5 KB.
    """
    figs = _figures_dir(paper_id)
    paths: list[str] = []
    seen_xrefs: set[int] = set()
    for page in pdf_doc:
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                base_image = pdf_doc.extract_image(xref)
                img_bytes: bytes = base_image["image"]
                if len(img_bytes) < 5000:
                    continue
                ext: str = base_image.get("ext", "png")
                os.makedirs(figs, exist_ok=True)
                path = os.path.join(figs, f"img{len(paths) + 1}.{ext}")
                with open(path, "wb") as out:
                    out.write(img_bytes)
                paths.append(path)
            except Exception:
                continue
    return paths


# ── nougat ────────────────────────────────────────────────────────────────────

_SECTION_RE = re.compile(r"^(#{1,3})\s+(.+)", re.MULTILINE)
_EQUATION_ENV_RE = re.compile(
    r"(\\begin\{(?:equation|align|gather)\*?\}.*?\\end\{(?:equation|align|gather)\*?\})",
    re.DOTALL,
)
_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
_FIGURE_CAPTION_RE = re.compile(
    r"^(?:Figure|Fig\.?)\s*\d+[.:]\s*(.+?)(?=\n(?:Figure|Fig\.?)\s*\d+[.:]|\Z)",
    re.MULTILINE | re.IGNORECASE | re.DOTALL,
)


def _run_nougat(pdf_path: str) -> str:
    """Run Nougat CLI on a PDF file and return the .mmd content.

    Model is controlled via NOUGAT_MODEL env var (default: 0.1.0-base).
    """
    model = os.environ.get("NOUGAT_MODEL", "0.1.0-base")
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(
            ["nougat", pdf_path, "-o", tmpdir, "--model", model, "--no-skipping"],
            check=True,
            capture_output=True,
            timeout=600,
        )
        stem = os.path.splitext(os.path.basename(pdf_path))[0]
        mmd_path = os.path.join(tmpdir, stem + ".mmd")
        with open(mmd_path, encoding="utf-8") as f:
            return f.read()


def _parse_mmd(
    mmd: str, paper_id: str, source_ref: str
) -> tuple[list[ResearchSection], list[ResearchEquation], list[ResearchFigure]]:
    """Parse Nougat .mmd output into ResearchDocument components."""
    # ── equations: collect, keep in-place so chunker can detect has_formula ─
    equations: list[ResearchEquation] = []
    eq_idx = 0

    def _collect_equation(m: re.Match) -> str:  # type: ignore[type-arg]
        nonlocal eq_idx
        label_m = _LABEL_RE.search(m.group(1))
        eq_id = label_m.group(1) if label_m else f"eq_{eq_idx}"
        equations.append(ResearchEquation(
            equation_id=build_stable_id("eq", paper_id, eq_id),
            latex=m.group(1).strip(),
            source_ref=source_ref,
        ))
        eq_idx += 1
        return m.group(1)  # keep verbatim

    text = _EQUATION_ENV_RE.sub(_collect_equation, mmd)

    # ── figures: extract captions ───────────────────────────────────────────
    figures: list[ResearchFigure] = []
    for i, m in enumerate(_FIGURE_CAPTION_RE.finditer(text)):
        caption = m.group(1).strip().replace("\n", " ")
        if caption:
            figures.append(ResearchFigure(
                figure_id=build_stable_id("fig", paper_id, f"fig_{i}"),
                caption=caption[:500],
                source_ref=source_ref,
            ))

    # ── sections: split by headings ─────────────────────────────────────────
    sections: list[ResearchSection] = []
    matches = list(_SECTION_RE.finditer(text))

    # text before the first heading becomes the abstract / preamble
    preamble = text[: matches[0].start()].strip() if matches else text.strip()
    if preamble:
        sections.append(ResearchSection(
            section_id=build_stable_id("sec", paper_id, "preamble"),
            title="Abstract",
            level=1,
            text=preamble,
            source_ref=source_ref,
        ))

    for i, m in enumerate(matches):
        title = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        sections.append(ResearchSection(
            section_id=build_stable_id("sec", paper_id, title, str(i)),
            title=title,
            level=len(m.group(1)),
            text=body,
            source_ref=source_ref,
        ))

    return sections, equations, figures


# ── main ──────────────────────────────────────────────────────────────────────


def _parse_pdf(
    paper_id: str,
    source_ref: str,
    source_hash: str,
    pdf_bytes: bytes,
) -> ResearchDocument:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        mmd = _run_nougat(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    sections, equations, figures = _parse_mmd(mmd, paper_id, source_ref)

    # associate image files from PDF with figures by appearance order
    pdf_doc: fitz.Document = fitz.open(stream=pdf_bytes, filetype="pdf")
    image_paths = _extract_pdf_images(pdf_doc, paper_id)
    pdf_doc.close()

    figures = [
        fig.model_copy(update={"image_ref": image_paths[i]})
        if i < len(image_paths) else fig
        for i, fig in enumerate(figures)
    ]

    return ResearchDocument(
        paper_id=paper_id,
        source_hash=source_hash,
        sections=sections,
        equations=equations,
        figures=figures,
        lineage=SourceLineage(source_refs=[source_ref], source_hash=source_hash),
        metadata={"parse_source": "nougat"},
    )


class PdfDocumentParser:
    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
        return _parse_pdf(
            paper_id=paper_id,
            source_ref=f"arxiv://{paper_id}/pdf",
            source_hash=sha256(source_bytes).hexdigest(),
            pdf_bytes=source_bytes,
        )


__all__ = ["PdfDocumentParser"]
