from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

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


@dataclass(frozen=True)
class FigureImageRef:
    image_ref: str
    page: int | None = None
    metadata: dict[str, Any] | None = None


_SURYA_FIGURE_LABELS = {"figure", "fig", "chart", "diagram", "image", "picture"}


def _figures_dir(paper_id: str) -> str:
    root = os.environ.get("NEWS_ARTIFACT_ROOT", ".newsroom/runs")
    return os.path.join(os.path.dirname(root), "papers", paper_id, "figures")


def _extract_pdf_images(pdf_doc: fitz.Document, paper_id: str) -> list[FigureImageRef]:
    """Extract images from PDF pages, save to figures dir.

    Returns paths in appearance order (page order, deduplicated by xref).
    Skips images smaller than 5 KB.
    """
    figs = _figures_dir(paper_id)
    paths: list[FigureImageRef] = []
    seen_xrefs: set[int] = set()
    for page_index, page in enumerate(pdf_doc, start=1):
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
                paths.append(FigureImageRef(
                    image_ref=path,
                    page=page_index,
                    metadata={"image_source": "pdf_embedded", "xref": xref},
                ))
            except Exception:
                continue
    return paths


# ── nougat (docker compose) ───────────────────────────────────────────────────

def _surya_base_url() -> str:
    return os.environ.get("SURYA_INFERENCE_URL", "").strip()


def _surya_model() -> str:
    return os.environ.get("SURYA_INFERENCE_MODEL", "datalab-to/surya-ocr-2")


def _surya_layout_dpi() -> int:
    raw = os.environ.get("SURYA_LAYOUT_DPI", "150")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("SURYA_LAYOUT_DPI must be an integer") from exc
    if value <= 0:
        raise ValueError("SURYA_LAYOUT_DPI must be positive")
    return value


def _ocr_page(base_url: str, model: str, image_b64: str) -> str:
    """Run a Surya/vLLM vision request for compatibility with diag_ocr.py."""
    response = _call_surya_vision(
        base_url=base_url,
        model=model,
        image_b64=image_b64,
        prompt="Read this page and return the OCR text only.",
    )
    return response.strip()


def _call_surya_vision(
    *,
    base_url: str,
    model: str,
    image_b64: str,
    prompt: str,
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}"
                        },
                    },
                ],
            }
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("SURYA_INFERENCE_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=data,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        body = json.loads(response.read().decode("utf-8"))
    return str(body["choices"][0]["message"]["content"])


def _run_surya_layout(page_png: bytes, page_number: int) -> list[dict[str, Any]]:
    base_url = _surya_base_url()
    if not base_url:
        return []
    prompt = (
        "Detect the visible figure, chart, image, and diagram regions on this "
        "research paper page. Return only JSON with this schema: "
        '{"figures":[{"label":"figure","bbox":[x0,y0,x1,y1],'
        '"caption":"","confidence":0.0}]}. Use normalized bbox '
        "coordinates in reading order, with values between 0 and 1. "
        "Do not include tables, normal paragraphs, headers, footers, or page numbers."
    )
    image_b64 = base64.b64encode(page_png).decode("utf-8")
    content = _call_surya_vision(
        base_url=base_url,
        model=_surya_model(),
        image_b64=image_b64,
        prompt=prompt,
    )
    return _parse_surya_layout_response(content, page_number=page_number)


def _parse_surya_layout_response(
    content: str,
    *,
    page_number: int,
) -> list[dict[str, Any]]:
    payload_text = content.strip()
    if payload_text.startswith("```"):
        payload_text = re.sub(r"^```(?:json)?\s*", "", payload_text)
        payload_text = re.sub(r"\s*```$", "", payload_text)
    payload_text = _extract_json_payload_text(payload_text)
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return []

    raw_regions = payload.get("figures") if isinstance(payload, dict) else payload
    if not isinstance(raw_regions, list):
        return []

    regions: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_regions):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("type") or "figure").lower()
        if label not in _SURYA_FIGURE_LABELS:
            continue
        bbox = _coerce_bbox(raw.get("bbox") or raw.get("box"))
        if bbox is None:
            continue
        regions.append({
            "page": page_number,
            "index": index,
            "label": label,
            "bbox": bbox,
            "caption": str(raw.get("caption") or "").strip(),
            "confidence": raw.get("confidence"),
        })
    return regions


def _extract_json_payload_text(content: str) -> str:
    decoder = json.JSONDecoder()
    start_candidates = sorted(
        idx for idx in (content.find("{"), content.find("[")) if idx >= 0
    )
    for start in start_candidates:
        try:
            _, end = decoder.raw_decode(content[start:])
        except json.JSONDecodeError:
            continue
        return content[start:start + end]
    return content


def _valid_bbox(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return False
    try:
        x0, y0, x1, y1 = (float(v) for v in value)
    except (TypeError, ValueError):
        return False
    return x1 > x0 and y1 > y0


def _coerce_bbox(value: Any) -> list[float] | None:
    if isinstance(value, str):
        value = [part for part in re.split(r"[\s,]+", value.strip()) if part]
    elif isinstance(value, dict):
        for keys in (("x0", "y0", "x1", "y1"), ("left", "top", "right", "bottom")):
            if all(key in value for key in keys):
                value = [value[key] for key in keys]
                break
    if not _valid_bbox(value):
        return None
    return [float(v) for v in value]


def _bbox_to_page_rect(
    bbox: list[float],
    *,
    page_rect: fitz.Rect,
    pix_width: int,
    pix_height: int,
) -> fitz.Rect:
    x0, y0, x1, y1 = bbox
    if max(abs(v) for v in bbox) <= 1.5:
        return fitz.Rect(
            page_rect.x0 + x0 * page_rect.width,
            page_rect.y0 + y0 * page_rect.height,
            page_rect.x0 + x1 * page_rect.width,
            page_rect.y0 + y1 * page_rect.height,
        ) & page_rect
    return fitz.Rect(
        page_rect.x0 + (x0 / pix_width) * page_rect.width,
        page_rect.y0 + (y0 / pix_height) * page_rect.height,
        page_rect.x0 + (x1 / pix_width) * page_rect.width,
        page_rect.y0 + (y1 / pix_height) * page_rect.height,
    ) & page_rect


def _extract_surya_figure_images(
    pdf_doc: fitz.Document,
    paper_id: str,
) -> list[FigureImageRef]:
    if not _surya_base_url():
        return []
    figs = _figures_dir(paper_id)
    os.makedirs(figs, exist_ok=True)
    dpi = _surya_layout_dpi()
    paths: list[FigureImageRef] = []
    for page_index, page in enumerate(pdf_doc, start=1):
        page_pix = page.get_pixmap(dpi=dpi, alpha=False)
        regions = _run_surya_layout(page_pix.tobytes("png"), page_index)
        for region in regions:
            rect = _bbox_to_page_rect(
                region["bbox"],
                page_rect=page.rect,
                pix_width=page_pix.width,
                pix_height=page_pix.height,
            )
            if rect.is_empty or rect.width < 4 or rect.height < 4:
                continue
            crop = page.get_pixmap(clip=rect, dpi=dpi, alpha=False)
            path = os.path.join(
                figs,
                f"surya_p{page_index:03d}_fig{len(paths) + 1:03d}.png",
            )
            crop.save(path)
            paths.append(FigureImageRef(
                image_ref=path,
                page=page_index,
                metadata={
                    "image_source": "surya_layout",
                    "bbox": region["bbox"],
                    "layout_label": region["label"],
                    "surya_caption": region["caption"],
                    "confidence": region["confidence"],
                },
            ))
    return paths


def _attach_figure_images(
    figures: list[ResearchFigure],
    image_refs: list[FigureImageRef],
) -> list[ResearchFigure]:
    out: list[ResearchFigure] = []
    for index, fig in enumerate(figures):
        if index >= len(image_refs):
            out.append(fig)
            continue
        image = image_refs[index]
        metadata = dict(fig.metadata)
        metadata.update(image.metadata or {})
        out.append(fig.model_copy(update={
            "image_ref": image.image_ref,
            "page": image.page,
            "metadata": metadata,
        }))
    return out


_SECTION_RE = re.compile(r"^(#{1,3})\s+(.+)", re.MULTILINE)
_EQUATION_ENV_RE = re.compile(
    r"(\\begin\{(?:equation|align|gather)\*?\}.*?\\end\{(?:equation|align|gather)\*?\})",
    re.DOTALL,
)
_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
_FIGURE_CAPTION_RE = re.compile(
    r"^(?:Figure|Fig\.?)\s*(\d+)[.:]\s*(.+?)(?=\n(?:Figure|Fig\.?)\s*\d+[.:]|\Z)",
    re.MULTILINE | re.IGNORECASE | re.DOTALL,
)

# Directory (relative to project root) where PDFs are staged for the nougat
# container and where .mmd output lands. The compose file mounts the project
# root at /workspace, so both paths must live inside the project tree.
_NOUGAT_WORK_REL = os.path.join(".newsroom", "nougat")
_NOUGAT_CONTAINER_WORK = "/workspace/.newsroom/nougat"


def _nougat_timeout_seconds() -> int:
    raw = os.environ.get("NOUGAT_TIMEOUT_SECONDS", "3600")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("NOUGAT_TIMEOUT_SECONDS must be an integer") from exc
    if value <= 0:
        raise ValueError("NOUGAT_TIMEOUT_SECONDS must be positive")
    return value


def _project_root() -> str:
    """Locate the project root by walking up to the docker-compose.yml."""
    cur = os.path.abspath(os.path.dirname(__file__))
    while cur != os.path.dirname(cur):
        if os.path.exists(os.path.join(cur, "docker-compose.yml")):
            return cur
        cur = os.path.dirname(cur)
    raise RuntimeError(
        "could not locate project root (docker-compose.yml not found)"
    )


def _run_nougat(pdf_bytes: bytes, paper_id: str) -> str:
    """Run Nougat (via `docker compose run`) on the PDF and return .mmd content.

    Nougat executes inside the `nougat` compose service (image
    newsroom-nougat:local). The compose entrypoint injects
    --model ${NOUGAT_MODEL:-0.1.0-base} automatically. The project root is
    mounted at /workspace, so the staged PDF and the output directory both
    live under <root>/.newsroom/nougat/.
    """
    root = _project_root()
    work_dir = os.path.join(root, _NOUGAT_WORK_REL)
    os.makedirs(work_dir, exist_ok=True)

    safe_id = re.sub(r"[^\w.\-]", "_", paper_id)
    pdf_name = f"{safe_id}.pdf"
    pdf_path = os.path.join(work_dir, pdf_name)
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)

    mmd_path = os.path.join(work_dir, f"{safe_id}.mmd")
    try:
        os.unlink(mmd_path)
    except FileNotFoundError:
        pass

    try:
        try:
            subprocess.run(
                [
                    "docker", "compose", "run", "--rm", "nougat",
                    f"{_NOUGAT_CONTAINER_WORK}/{pdf_name}",
                    "-o", _NOUGAT_CONTAINER_WORK,
                    "--recompute",
                ],
                check=True,
                timeout=_nougat_timeout_seconds(),
                cwd=root,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"nougat docker run failed (exit {exc.returncode})"
            ) from exc

        if not os.path.exists(mmd_path):
            actual = os.listdir(work_dir)
            raise FileNotFoundError(
                f"nougat did not produce {mmd_path}\n"
                f"files in {work_dir}: {actual}"
            )
        with open(mmd_path, encoding="utf-8") as f:
            return f.read()
    finally:
        try:
            os.unlink(pdf_path)
        except OSError:
            pass


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
        figure_number = int(m.group(1))
        caption = m.group(2).strip().replace("\n", " ")
        if caption:
            figures.append(ResearchFigure(
                figure_id=build_stable_id("fig", paper_id, f"fig_{i}"),
                caption=caption[:500],
                source_ref=source_ref,
                metadata={"figure_number": figure_number},
            ))

    # ── sections: split by headings ─────────────────────────────────────────
    sections: list[ResearchSection] = []
    matches = list(_SECTION_RE.finditer(text))

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
    mmd = _run_nougat(pdf_bytes, paper_id)

    sections, equations, figures = _parse_mmd(mmd, paper_id, source_ref)

    pdf_doc: fitz.Document = fitz.open(stream=pdf_bytes, filetype="pdf")
    surya_error: str | None = None
    try:
        try:
            image_refs = _extract_surya_figure_images(pdf_doc, paper_id)
        except Exception as exc:
            image_refs = []
            surya_error = f"{type(exc).__name__}: {exc}"
        image_source = "surya_layout" if image_refs else "pdf_embedded"
        if not image_refs:
            image_refs = _extract_pdf_images(pdf_doc, paper_id)
            if not image_refs:
                image_source = "none"
    finally:
        pdf_doc.close()

    figures = _attach_figure_images(figures, image_refs)
    metadata = {
        "parse_source": "nougat",
        "figure_image_source": image_source,
        "figure_images": len(image_refs),
    }
    if surya_error:
        metadata["surya_layout_error"] = surya_error

    return ResearchDocument(
        paper_id=paper_id,
        source_hash=source_hash,
        sections=sections,
        equations=equations,
        figures=figures,
        lineage=SourceLineage(source_refs=[source_ref], source_hash=source_hash),
        metadata=metadata,
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
