from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass, field
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
    ResearchTable,
)

# ── figures ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FigureImageRef:
    image_ref: str
    page: int | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class SuryaLayoutArtifacts:
    figure_images: list[FigureImageRef]
    table_images: list[FigureImageRef]
    layout_ref: str | None = None
    region_count: int = 0
    regions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class PageTextEvidence:
    page: int
    native_text: str
    selected_text: str
    selected_source: str
    native_chars: int
    native_words: int
    ocr_attempted: bool = False
    ocr_chars: int = 0
    ocr_error: str | None = None


_SURYA_FIGURE_LABELS = {"figure", "fig", "chart", "diagram", "image", "picture"}
_SURYA_TABLE_LABELS = {"table"}
_SURYA_CAPTION_LABELS = {"caption"}
_SURYA_EQUATION_LABELS = {"equation", "equation-block", "formula"}
_SURYA_EVIDENCE_LABELS = (
    _SURYA_FIGURE_LABELS
    | _SURYA_TABLE_LABELS
    | _SURYA_CAPTION_LABELS
    | _SURYA_EQUATION_LABELS
)
_SURYA_BBOX_SCALE = 1000.0
_FIGURE_CROP_PADDING_POINTS = 8.0


def _paper_artifact_dir(paper_id: str) -> str:
    root = os.environ.get("NEWS_ARTIFACT_ROOT", ".newsroom/runs")
    return os.path.join(os.path.dirname(root), "papers", paper_id)


def _figures_dir(paper_id: str) -> str:
    return os.path.join(_paper_artifact_dir(paper_id), "figures")


def _tables_dir(paper_id: str) -> str:
    return os.path.join(_paper_artifact_dir(paper_id), "tables")


def _surya_layout_path(paper_id: str) -> str:
    return os.path.join(_paper_artifact_dir(paper_id), "surya_layout.json")


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


def _run_surya_layout(
    page_png: bytes,
    page_number: int,
    *,
    allowed_labels: set[str] | None = None,
) -> list[dict[str, Any]]:
    base_url = _surya_base_url()
    if not base_url:
        return []
    prompt = (
        "Detect the visible figure, chart, image, diagram, table, caption, "
        "and equation-block regions on this "
        "research paper page. Return only JSON with this schema: "
        '{"regions":[{"label":"figure","bbox":[x0,y0,x1,y1],'
        '"caption":"","confidence":0.0}]}. Use normalized bbox '
        "coordinates in reading order, with values between 0 and 1. "
        "Do not include normal paragraphs, headers, footers, or page numbers."
    )
    image_b64 = base64.b64encode(page_png).decode("utf-8")
    content = _call_surya_vision(
        base_url=base_url,
        model=_surya_model(),
        image_b64=image_b64,
        prompt=prompt,
    )
    return _parse_surya_layout_response(
        content,
        page_number=page_number,
        allowed_labels=allowed_labels,
    )


def _parse_surya_layout_response(
    content: str,
    *,
    page_number: int,
    allowed_labels: set[str] | None = None,
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

    if isinstance(payload, dict):
        raw_regions = payload.get("regions") or payload.get("figures")
    else:
        raw_regions = payload
    if not isinstance(raw_regions, list):
        return []

    labels = allowed_labels or _SURYA_FIGURE_LABELS
    regions: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_regions):
        if not isinstance(raw, dict):
            continue
        label = _normalize_layout_label(raw.get("label") or raw.get("type") or "figure")
        if label not in labels:
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


def _normalize_layout_label(value: Any) -> str:
    return str(value).strip().lower().replace("_", "-")


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
        rect = fitz.Rect(
            page_rect.x0 + x0 * page_rect.width,
            page_rect.y0 + y0 * page_rect.height,
            page_rect.x0 + x1 * page_rect.width,
            page_rect.y0 + y1 * page_rect.height,
        )
        return _pad_rect(rect, page_rect, _FIGURE_CROP_PADDING_POINTS)
    if max(abs(v) for v in bbox) <= _SURYA_BBOX_SCALE:
        rect = fitz.Rect(
            page_rect.x0 + (x0 / _SURYA_BBOX_SCALE) * page_rect.width,
            page_rect.y0 + (y0 / _SURYA_BBOX_SCALE) * page_rect.height,
            page_rect.x0 + (x1 / _SURYA_BBOX_SCALE) * page_rect.width,
            page_rect.y0 + (y1 / _SURYA_BBOX_SCALE) * page_rect.height,
        )
        return _pad_rect(rect, page_rect, _FIGURE_CROP_PADDING_POINTS)
    return fitz.Rect(
        page_rect.x0 + (x0 / pix_width) * page_rect.width,
        page_rect.y0 + (y0 / pix_height) * page_rect.height,
        page_rect.x0 + (x1 / pix_width) * page_rect.width,
        page_rect.y0 + (y1 / pix_height) * page_rect.height,
    ) & page_rect


def _bbox_coordinate_system(bbox: list[float]) -> str:
    max_value = max(abs(v) for v in bbox)
    if max_value <= 1.5:
        return "normalized"
    if max_value <= _SURYA_BBOX_SCALE:
        return "surya_1000"
    return "render_pixels"


def _pad_rect(rect: fitz.Rect, page_rect: fitz.Rect, padding: float) -> fitz.Rect:
    return fitz.Rect(
        rect.x0 - padding,
        rect.y0 - padding,
        rect.x1 + padding,
        rect.y1 + padding,
    ) & page_rect


def _extract_surya_figure_images(
    pdf_doc: fitz.Document,
    paper_id: str,
) -> list[FigureImageRef]:
    return _extract_surya_layout_artifacts(pdf_doc, paper_id).figure_images


def _extract_surya_layout_artifacts(
    pdf_doc: fitz.Document,
    paper_id: str,
) -> SuryaLayoutArtifacts:
    if not _surya_base_url():
        return SuryaLayoutArtifacts(figure_images=[], table_images=[])
    figs = _figures_dir(paper_id)
    tables_dir = _tables_dir(paper_id)
    layout_path = _surya_layout_path(paper_id)
    os.makedirs(figs, exist_ok=True)
    os.makedirs(tables_dir, exist_ok=True)
    os.makedirs(os.path.dirname(layout_path), exist_ok=True)
    dpi = _surya_layout_dpi()
    figure_paths: list[FigureImageRef] = []
    table_paths: list[FigureImageRef] = []
    all_regions: list[dict[str, Any]] = []
    for page_index, page in enumerate(pdf_doc, start=1):
        page_pix = page.get_pixmap(dpi=dpi, alpha=False)
        regions = _run_surya_layout(
            page_pix.tobytes("png"),
            page_index,
            allowed_labels=_SURYA_EVIDENCE_LABELS,
        )
        for region in regions:
            rect = _bbox_to_page_rect(
                region["bbox"],
                page_rect=page.rect,
                pix_width=page_pix.width,
                pix_height=page_pix.height,
            )
            enriched_region = dict(region)
            enriched_region["bbox_coordinate_system"] = _bbox_coordinate_system(region["bbox"])
            enriched_region["pdf_rect"] = _rect_to_list(rect)
            all_regions.append(enriched_region)
            if region["label"] not in (_SURYA_FIGURE_LABELS | _SURYA_TABLE_LABELS):
                continue
            if rect.is_empty or rect.width < 4 or rect.height < 4:
                continue
            crop = page.get_pixmap(clip=rect, dpi=dpi, alpha=False)
            table_text = ""
            if region["label"] in _SURYA_TABLE_LABELS:
                target_paths = table_paths
                output_dir = tables_dir
                filename = f"surya_table_p{page_index:03d}_{len(target_paths) + 1:03d}.png"
                image_source = "surya_table_layout"
                try:
                    table_text = page.get_text("text", clip=rect).strip()
                except Exception:
                    table_text = ""
            else:
                target_paths = figure_paths
                output_dir = figs
                filename = f"surya_p{page_index:03d}_fig{len(target_paths) + 1:03d}.png"
                image_source = "surya_layout"
            path = os.path.join(output_dir, filename)
            crop.save(path)
            metadata = {
                "image_source": image_source,
                "bbox": region["bbox"],
                "bbox_coordinate_system": enriched_region["bbox_coordinate_system"],
                "layout_label": region["label"],
                "layout_region_index": region["index"],
                "pdf_rect": enriched_region["pdf_rect"],
                "surya_caption": region["caption"],
                "confidence": region["confidence"],
            }
            if table_text:
                metadata["table_text"] = table_text
                metadata["table_text_source"] = "pymupdf_bbox"
            target_paths.append(FigureImageRef(
                image_ref=path,
                page=page_index,
                metadata=metadata,
            ))
    figure_paths = _with_nearest_caption_region(figure_paths, all_regions)
    table_paths = _with_nearest_caption_region(table_paths, all_regions)
    with open(layout_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "paper_id": paper_id,
                "coordinate_system": "per_region",
                "dpi": dpi,
                "regions": all_regions,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    return SuryaLayoutArtifacts(
        figure_images=figure_paths,
        table_images=table_paths,
        layout_ref=layout_path,
        region_count=len(all_regions),
        regions=all_regions,
    )


def _rect_to_list(rect: fitz.Rect) -> list[float]:
    return [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]


def _rect_from_list(values: Any) -> fitz.Rect | None:
    bbox = _coerce_bbox(values)
    if bbox is None:
        return None
    return fitz.Rect(*bbox)


def _horizontal_overlap_ratio(a: fitz.Rect, b: fitz.Rect) -> float:
    overlap = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    denominator = max(1.0, min(a.width, b.width))
    return overlap / denominator


def _caption_region_score(target_rect: fitz.Rect, caption_rect: fitz.Rect) -> float:
    overlap = _horizontal_overlap_ratio(target_rect, caption_rect)
    if overlap < 0.2:
        return 0.0
    if caption_rect.y0 >= target_rect.y1:
        vertical_gap = caption_rect.y0 - target_rect.y1
    elif target_rect.y0 >= caption_rect.y1:
        vertical_gap = target_rect.y0 - caption_rect.y1
    else:
        vertical_gap = 0.0
    proximity = 1.0 / (1.0 + vertical_gap / 72.0)
    return round((0.75 * overlap) + (0.25 * proximity), 4)


def _with_nearest_caption_region(
    image_refs: list[FigureImageRef],
    regions: list[dict[str, Any]],
) -> list[FigureImageRef]:
    caption_regions = [r for r in regions if r.get("label") in _SURYA_CAPTION_LABELS]
    if not caption_regions:
        return image_refs

    out: list[FigureImageRef] = []
    for image in image_refs:
        metadata = dict(image.metadata or {})
        image_rect = _rect_from_list(metadata.get("pdf_rect"))
        if image.page is None or image_rect is None:
            out.append(image)
            continue

        best: tuple[float, dict[str, Any]] | None = None
        for caption in caption_regions:
            if caption.get("page") != image.page:
                continue
            caption_rect = _rect_from_list(caption.get("pdf_rect"))
            if caption_rect is None:
                continue
            score = _caption_region_score(image_rect, caption_rect)
            if score <= 0:
                continue
            if best is None or score > best[0]:
                best = (score, caption)

        if best is not None:
            score, caption = best
            metadata.update({
                "caption_bbox": caption.get("bbox"),
                "caption_pdf_rect": caption.get("pdf_rect"),
                "caption_region_index": caption.get("index"),
                "caption_match_score": score,
                "caption_match_strategy": "same_page_nearest_caption_region",
            })
        out.append(FigureImageRef(
            image_ref=image.image_ref,
            page=image.page,
            metadata=metadata,
        ))
    return out


def _normalize_search_text(value: str) -> str:
    return " ".join(_SEARCH_WORD_RE.findall(value.lower()))


def _caption_query(caption: str, *, max_words: int = 14) -> str:
    return " ".join(_caption_query_words(caption, max_words=max_words))


def _caption_query_words(caption: str, *, max_words: int = 18) -> list[str]:
    return _SEARCH_WORD_RE.findall(caption.lower())[:max_words]


def _find_caption_page(
    *,
    kind: str,
    number: int | None,
    caption: str,
    page_texts: list[PageTextEvidence],
) -> tuple[int | None, float]:
    query_words = _caption_query_words(caption)
    query = " ".join(query_words)
    if not query:
        return None, 0.0
    label = f"{kind.lower()} {number}" if number is not None else ""
    best: tuple[int, float] | None = None
    for evidence in page_texts:
        haystack = _normalize_search_text(
            evidence.selected_text or evidence.native_text
        )
        haystack_words = set(_SEARCH_WORD_RE.findall(haystack))
        query_unique = set(query_words)
        overlap = (
            len(query_unique & haystack_words) / len(query_unique)
            if query_unique else 0.0
        )
        score = 0.0
        if label and f"{label} {query}" in haystack:
            score = 1.0
        elif query in haystack:
            score = 0.85
        elif label and label in haystack and overlap >= 0.35:
            score = round(0.65 + (0.25 * overlap), 4)
        elif overlap >= 0.8:
            score = round(0.55 + (0.25 * overlap), 4)
        elif label and label in haystack:
            score = 0.55
        if score and (best is None or score > best[1]):
            best = (evidence.page, score)
    if best is None:
        return None, 0.0
    return best


def _select_image_ref(
    image_refs: list[FigureImageRef],
    used_indices: set[int],
    expected_page: int | None,
) -> tuple[int | None, FigureImageRef | None, str, float]:
    if expected_page is not None:
        for index, image in enumerate(image_refs):
            if index not in used_indices and image.page == expected_page:
                return index, image, "caption_text_page_match", 0.9
    for index, image in enumerate(image_refs):
        if index not in used_indices:
            return index, image, "layout_order", 0.5
    return None, None, "unmatched", 0.0


def _attach_figure_images(
    figures: list[ResearchFigure],
    image_refs: list[FigureImageRef],
    page_texts: list[PageTextEvidence] | None = None,
) -> list[ResearchFigure]:
    out: list[ResearchFigure] = []
    used_indices: set[int] = set()
    for fig in figures:
        expected_page, caption_score = _find_caption_page(
            kind="figure",
            number=fig.metadata.get("figure_number"),
            caption=fig.caption,
            page_texts=page_texts or [],
        )
        index, image, strategy, alignment_score = _select_image_ref(
            image_refs,
            used_indices,
            expected_page,
        )
        if image is None or index is None:
            out.append(fig)
            continue
        used_indices.add(index)
        metadata = dict(fig.metadata)
        metadata.update(image.metadata or {})
        metadata.update({
            "alignment_strategy": strategy,
            "alignment_score": alignment_score,
        })
        if expected_page is not None:
            metadata["caption_text_page"] = expected_page
            metadata["caption_text_match_score"] = caption_score
        out.append(fig.model_copy(update={
            "image_ref": image.image_ref,
            "page": image.page,
            "metadata": metadata,
        }))
    return out


def _attach_table_images(
    tables: list[ResearchTable],
    image_refs: list[FigureImageRef],
    page_texts: list[PageTextEvidence] | None = None,
) -> list[ResearchTable]:
    out: list[ResearchTable] = []
    used_indices: set[int] = set()
    for table in tables:
        expected_page, caption_score = _find_caption_page(
            kind="table",
            number=table.metadata.get("table_number"),
            caption=table.caption,
            page_texts=page_texts or [],
        )
        index, image, strategy, alignment_score = _select_image_ref(
            image_refs,
            used_indices,
            expected_page,
        )
        if image is None or index is None:
            out.append(table)
            continue
        used_indices.add(index)
        metadata = dict(table.metadata)
        metadata.update(image.metadata or {})
        metadata["image_ref"] = image.image_ref
        metadata.update({
            "alignment_strategy": strategy,
            "alignment_score": alignment_score,
        })
        if expected_page is not None:
            metadata["caption_text_page"] = expected_page
            metadata["caption_text_match_score"] = caption_score
        update: dict[str, Any] = {
            "page": image.page,
            "metadata": metadata,
        }
        if (not table.columns or not table.rows) and metadata.get("table_text"):
            columns, rows = _parse_table_text_rows(str(metadata["table_text"]))
            if columns and rows:
                metadata["table_structure_source"] = "pymupdf_bbox_text"
                update["columns"] = columns
                update["rows"] = rows
        out.append(table.model_copy(update=update))
    return out


def _attach_equation_positions(
    equations: list[ResearchEquation],
    regions: list[dict[str, Any]],
    page_texts: list[PageTextEvidence] | None = None,
) -> list[ResearchEquation]:
    equation_regions = [
        region for region in regions
        if region.get("label") in _SURYA_EQUATION_LABELS
    ]

    out: list[ResearchEquation] = []
    for index, equation in enumerate(equations):
        if index >= len(equation_regions):
            fallback_page, fallback_score = _find_equation_page(
                equation,
                page_texts or [],
            )
            if fallback_page is None:
                out.append(equation)
                continue
            metadata = dict(equation.metadata)
            metadata.update({
                "position_source": "pymupdf_text_search",
                "position_match_strategy": "equation_token_overlap",
                "position_match_score": fallback_score,
            })
            out.append(equation.model_copy(update={
                "page": fallback_page,
                "metadata": metadata,
            }))
            continue
        region = equation_regions[index]
        metadata = dict(equation.metadata)
        metadata.update({
            "position_source": "surya_equation_layout",
            "position_match_strategy": "layout_order",
            "layout_label": region.get("label"),
            "bbox": region.get("bbox"),
            "bbox_coordinate_system": region.get("bbox_coordinate_system"),
            "pdf_rect": region.get("pdf_rect"),
            "layout_region_index": region.get("index"),
        })
        out.append(equation.model_copy(update={
            "page": region.get("page"),
            "metadata": metadata,
        }))
    return out


def _find_equation_page(
    equation: ResearchEquation,
    page_texts: list[PageTextEvidence],
) -> tuple[int | None, float]:
    query_words = _equation_query_words(equation.latex)
    if len(query_words) < 3:
        return None, 0.0
    query_unique = set(query_words)
    best: tuple[int, float] | None = None
    for evidence in page_texts:
        haystack_words = set(_SEARCH_WORD_RE.findall(
            (evidence.selected_text or evidence.native_text).lower()
        ))
        overlap = len(query_unique & haystack_words) / len(query_unique)
        if overlap < 0.45:
            continue
        score = round(0.55 + (0.35 * overlap), 4)
        if best is None or score > best[1]:
            best = (evidence.page, score)
    if best is None:
        return None, 0.0
    return best


def _equation_query_words(latex: str, *, max_words: int = 18) -> list[str]:
    words = _SEARCH_WORD_RE.findall(latex.lower())
    result: list[str] = []
    for word in words:
        if len(word) < 2 or word in _EQUATION_QUERY_STOP_WORDS:
            continue
        result.append(word)
        if len(result) >= max_words:
            break
    return result


_SECTION_RE = re.compile(r"^(#{1,3})\s+(.+)", re.MULTILINE)
_EQUATION_RE = re.compile(
    r"(\\begin\{(?:equation|align|gather)\*?\}.*?\\end\{(?:equation|align|gather)\*?\}"
    r"|\\\[.*?\\\]"
    r"|\$\$.*?\$\$)",
    re.DOTALL,
)
_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
_TAG_RE = re.compile(r"\\tag\{([^}]+)\}")
_FIGURE_CAPTION_RE = re.compile(
    r"^(?:Figure|Fig\.?)\s*(\d+)[.:]\s*(.+?)(?=\n\s*\n|\n(?:Figure|Fig\.?|Table)\s*\d+[.:]|\n#{1,6}\s+|\Z)",
    re.MULTILINE | re.IGNORECASE | re.DOTALL,
)
_TABLE_CAPTION_RE = re.compile(
    r"^Table\s*(\d+)[.:]\s*(.+?)(?=\n\s*\n|\n(?:Figure|Fig\.?|Table)\s*\d+[.:]|\n#{1,6}\s+|\Z)",
    re.MULTILINE | re.IGNORECASE | re.DOTALL,
)
_TABLE_ENV_RE = re.compile(r"\\begin\{table\}(.*?)\\end\{table\}", re.DOTALL)
_TABULAR_RE = re.compile(
    r"\\begin\{tabular\}\{[^}]*\}(.*?)\\end\{tabular\}",
    re.DOTALL,
)
_MULTICOLUMN_RE = re.compile(r"\\multicolumn\{[^}]+\}\{[^}]+\}\{([^}]*)\}")
_MISSING_PAGE_RE = re.compile(r"\[MISSING_PAGE_FAIL:(\d+)\]")
_SEARCH_WORD_RE = re.compile(r"[a-z0-9]+")
_EQUATION_QUERY_STOP_WORDS = {
    "align",
    "begin",
    "cdot",
    "cos",
    "end",
    "equation",
    "frac",
    "gather",
    "left",
    "mathit",
    "mathrm",
    "right",
    "sin",
    "small",
    "sqrt",
    "tag",
    "text",
    "where",
}

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


def _pdf_text_min_chars() -> int:
    raw = os.environ.get("PDF_TEXT_MIN_CHARS", "100")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("PDF_TEXT_MIN_CHARS must be an integer") from exc
    if value < 0:
        raise ValueError("PDF_TEXT_MIN_CHARS must be non-negative")
    return value


def _pdf_ocr_dpi() -> int:
    raw = os.environ.get("PDF_OCR_DPI", "150")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("PDF_OCR_DPI must be an integer") from exc
    if value <= 0:
        raise ValueError("PDF_OCR_DPI must be positive")
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
) -> tuple[
    list[ResearchSection],
    list[ResearchEquation],
    list[ResearchFigure],
    list[ResearchTable],
]:
    """Parse Nougat .mmd output into ResearchDocument components."""
    # ── equations: collect, keep in-place so chunker can detect has_formula ─
    equations: list[ResearchEquation] = []
    eq_idx = 0

    def _collect_equation(m: re.Match) -> str:  # type: ignore[type-arg]
        nonlocal eq_idx
        label_m = _LABEL_RE.search(m.group(1))
        tag_m = _TAG_RE.search(m.group(1))
        eq_id = label_m.group(1) if label_m else tag_m.group(1) if tag_m else f"eq_{eq_idx}"
        metadata = {
            "parse_source": "nougat_mmd",
            "equation_label": eq_id,
        }
        if label_m:
            metadata["latex_label"] = label_m.group(1)
        if tag_m:
            metadata["equation_number"] = tag_m.group(1)
        equations.append(ResearchEquation(
            equation_id=build_stable_id("eq", paper_id, eq_id),
            latex=m.group(1).strip(),
            source_ref=source_ref,
            metadata=metadata,
        ))
        eq_idx += 1
        return m.group(1)  # keep verbatim

    text = _EQUATION_RE.sub(_collect_equation, mmd)

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

    # ── tables: extract captions plus tabular rows when Nougat preserves them ─
    tables = _parse_mmd_tables(text, paper_id, source_ref)

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

    return sections, equations, figures, tables


def _parse_mmd_tables(
    text: str,
    paper_id: str,
    source_ref: str,
) -> list[ResearchTable]:
    table_blocks = list(_TABLE_ENV_RE.finditer(text))
    used_blocks: set[int] = set()
    tables: list[ResearchTable] = []
    for i, caption_match in enumerate(_TABLE_CAPTION_RE.finditer(text)):
        table_number = int(caption_match.group(1))
        caption = caption_match.group(2).strip().replace("\n", " ")
        if not caption:
            continue

        block_index = _nearest_table_block_before(
            table_blocks,
            caption_match.start(),
            used_blocks,
        )
        columns: list[str] = []
        rows: list[dict[str, str]] = []
        if block_index is not None:
            used_blocks.add(block_index)
            columns, rows = _parse_tabular_rows(table_blocks[block_index].group(1))

        tables.append(ResearchTable(
            table_id=build_stable_id("tbl", paper_id, f"table_{table_number}_{i}"),
            caption=caption[:500],
            source_ref=source_ref,
            columns=columns,
            rows=rows,
            metadata={
                "table_number": table_number,
                "parse_source": "nougat_mmd",
            },
        ))
    return tables


def _nearest_table_block_before(
    table_blocks: list[re.Match],  # type: ignore[type-arg]
    caption_start: int,
    used_blocks: set[int],
) -> int | None:
    candidates = [
        index for index, block in enumerate(table_blocks)
        if index not in used_blocks and block.end() <= caption_start
    ]
    return candidates[-1] if candidates else None


def _parse_tabular_rows(table_body: str) -> tuple[list[str], list[dict[str, str]]]:
    tabular_match = _TABULAR_RE.search(table_body)
    if not tabular_match:
        return [], []

    raw_rows = re.split(r"\\\\", tabular_match.group(1))
    matrix: list[list[str]] = []
    for raw_row in raw_rows:
        cells = [_clean_table_cell(cell) for cell in raw_row.split("&")]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2:
            matrix.append(cells)
    if not matrix:
        return [], []

    columns = _unique_column_names(matrix[0])
    rows = []
    for raw_cells in matrix[1:]:
        padded = raw_cells + [""] * max(0, len(columns) - len(raw_cells))
        rows.append(dict(zip(columns, padded[:len(columns)])))
    return columns, rows


def _parse_table_text_rows(table_text: str) -> tuple[list[str], list[dict[str, str]]]:
    lines = [line.strip() for line in table_text.splitlines() if line.strip()]
    matrix = [_split_table_text_line(line) for line in lines]
    matrix = [cells for cells in matrix if len(cells) >= 2]
    if len(matrix) < 2:
        return [], []

    width = max(len(cells) for cells in matrix)
    if width < 2:
        return [], []

    columns = _unique_column_names(
        matrix[0] + [f"column_{i + 1}" for i in range(len(matrix[0]), width)]
    )
    rows: list[dict[str, str]] = []
    for raw_cells in matrix[1:]:
        padded = raw_cells + [""] * max(0, len(columns) - len(raw_cells))
        rows.append(dict(zip(columns, padded[:len(columns)])))
    return columns, rows


def _split_table_text_line(line: str) -> list[str]:
    if "|" in line:
        cells = [part.strip() for part in line.split("|")]
    elif "\t" in line:
        cells = [part.strip() for part in line.split("\t")]
    else:
        cells = [part.strip() for part in re.split(r"\s{2,}", line)]
    return [re.sub(r"\s+", " ", cell) for cell in cells if cell]


def _clean_table_cell(value: str) -> str:
    text = _MULTICOLUMN_RE.sub(r"\1", value)
    text = re.sub(r"\\hline", " ", text)
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", text).strip()


def _unique_column_names(columns: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    result: list[str] = []
    for index, raw in enumerate(columns):
        name = raw.strip() or f"column_{index + 1}"
        counts[name] = counts.get(name, 0) + 1
        if counts[name] > 1:
            name = f"{name}_{counts[name]}"
        result.append(name)
    return result


def _extract_missing_pages(mmd: str) -> set[int]:
    return {int(match.group(1)) for match in _MISSING_PAGE_RE.finditer(mmd)}


def _extract_page_text_evidence(pdf_doc: fitz.Document) -> list[PageTextEvidence]:
    min_chars = _pdf_text_min_chars()
    ocr_dpi = _pdf_ocr_dpi()
    base_url = _surya_base_url()
    model = _surya_model()
    evidence: list[PageTextEvidence] = []

    for page_index, page in enumerate(pdf_doc, start=1):
        native_text = page.get_text("text").strip()
        native_chars = len(native_text)
        native_words = len(native_text.split())
        selected_text = native_text
        selected_source = "pymupdf_text" if native_text else "none"
        ocr_attempted = False
        ocr_chars = 0
        ocr_error: str | None = None

        should_ocr = native_chars < min_chars and bool(base_url)
        if should_ocr:
            ocr_attempted = True
            try:
                pix = page.get_pixmap(dpi=ocr_dpi, alpha=False)
                image_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
                ocr_text = _ocr_page(base_url, model, image_b64).strip()
                ocr_chars = len(ocr_text)
                if ocr_text:
                    selected_text = ocr_text
                    selected_source = "surya_ocr"
            except Exception as exc:  # noqa: BLE001 - preserve diagnostics
                ocr_error = f"{type(exc).__name__}: {exc}"

        evidence.append(PageTextEvidence(
            page=page_index,
            native_text=native_text,
            selected_text=selected_text,
            selected_source=selected_source,
            native_chars=native_chars,
            native_words=native_words,
            ocr_attempted=ocr_attempted,
            ocr_chars=ocr_chars,
            ocr_error=ocr_error,
        ))

    return evidence


def _page_text_evidence_summary(
    page_texts: list[PageTextEvidence],
) -> list[dict[str, Any]]:
    return [
        {
            "page": evidence.page,
            "native_chars": evidence.native_chars,
            "native_words": evidence.native_words,
            "selected_source": evidence.selected_source,
            "selected_chars": len(evidence.selected_text),
            "ocr_attempted": evidence.ocr_attempted,
            "ocr_chars": evidence.ocr_chars,
            **({"ocr_error": evidence.ocr_error} if evidence.ocr_error else {}),
        }
        for evidence in page_texts
    ]


def _append_text_fallback_sections(
    sections: list[ResearchSection],
    *,
    paper_id: str,
    source_ref: str,
    page_texts: list[PageTextEvidence],
    missing_pages: set[int],
) -> tuple[list[ResearchSection], list[int]]:
    fallback_pages = set(missing_pages)
    fallback_pages.update(
        evidence.page for evidence in page_texts
        if evidence.selected_source == "surya_ocr"
    )
    if not any(section.text.strip() for section in sections):
        fallback_pages.update(evidence.page for evidence in page_texts)

    if not fallback_pages:
        return sections, []

    by_page = {evidence.page: evidence for evidence in page_texts}
    out = list(sections)
    appended_pages: list[int] = []
    for page_number in sorted(fallback_pages):
        evidence = by_page.get(page_number)
        if evidence is None or not evidence.selected_text.strip():
            continue
        source_name = evidence.selected_source
        title = "OCR Page" if source_name == "surya_ocr" else "PDF Text Page"
        if page_number in missing_pages:
            reason = "nougat_missing_page"
        elif source_name == "surya_ocr":
            reason = "low_native_text"
        else:
            reason = "nougat_empty_output"
        out.append(ResearchSection(
            section_id=build_stable_id("sec", paper_id, f"fallback_page_{page_number}"),
            title=f"{title} {page_number}",
            level=1,
            text=evidence.selected_text,
            page_start=page_number,
            page_end=page_number,
            source_ref=f"{source_ref}#page={page_number}",
            metadata={
                "parse_source": f"{source_name}_fallback",
                "fallback_reason": reason,
                "native_chars": evidence.native_chars,
                "ocr_chars": evidence.ocr_chars,
            },
        ))
        appended_pages.append(page_number)

    return out, appended_pages


# ── main ──────────────────────────────────────────────────────────────────────


def _parse_pdf(
    paper_id: str,
    source_ref: str,
    source_hash: str,
    pdf_bytes: bytes,
) -> ResearchDocument:
    mmd = _run_nougat(pdf_bytes, paper_id)

    sections, equations, figures, tables = _parse_mmd(mmd, paper_id, source_ref)
    missing_pages = _extract_missing_pages(mmd)

    pdf_doc: fitz.Document = fitz.open(stream=pdf_bytes, filetype="pdf")
    surya_error: str | None = None
    surya_artifacts = SuryaLayoutArtifacts(figure_images=[], table_images=[])
    page_texts: list[PageTextEvidence] = []
    text_fallback_pages: list[int] = []
    image_refs: list[FigureImageRef] = []
    image_source = "none"
    try:
        page_texts = _extract_page_text_evidence(pdf_doc)
        sections, text_fallback_pages = _append_text_fallback_sections(
            sections,
            paper_id=paper_id,
            source_ref=source_ref,
            page_texts=page_texts,
            missing_pages=missing_pages,
        )
        try:
            surya_artifacts = _extract_surya_layout_artifacts(pdf_doc, paper_id)
            image_refs = surya_artifacts.figure_images
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

    figures = _attach_figure_images(figures, image_refs, page_texts)
    tables = _attach_table_images(tables, surya_artifacts.table_images, page_texts)
    equations = _attach_equation_positions(equations, surya_artifacts.regions, page_texts)
    ocr_pages = [
        evidence.page for evidence in page_texts
        if evidence.selected_source == "surya_ocr"
    ]
    ocr_attempted_pages = [
        evidence.page for evidence in page_texts
        if evidence.ocr_attempted
    ]
    low_native_text_pages = [
        evidence.page for evidence in page_texts
        if evidence.native_chars < _pdf_text_min_chars()
    ]
    ocr_errors = [
        {"page": evidence.page, "error": evidence.ocr_error}
        for evidence in page_texts
        if evidence.ocr_error
    ]
    metadata = {
        "parse_source": "nougat",
        "figure_image_source": image_source,
        "figure_images": len(image_refs),
        "table_images": len(surya_artifacts.table_images),
        "surya_layout_regions": surya_artifacts.region_count,
        "nougat_missing_pages": sorted(missing_pages),
        "text_fallback_pages": text_fallback_pages,
        "ocr_used": bool(ocr_pages),
        "ocr_attempted_pages": ocr_attempted_pages,
        "ocr_pages": ocr_pages,
        "low_native_text_pages": low_native_text_pages,
        "page_text_evidence": _page_text_evidence_summary(page_texts),
    }
    if ocr_errors:
        metadata["ocr_errors"] = ocr_errors
    if surya_artifacts.layout_ref:
        metadata["surya_layout_ref"] = surya_artifacts.layout_ref
    if surya_error:
        metadata["surya_layout_error"] = surya_error

    return ResearchDocument(
        paper_id=paper_id,
        source_hash=source_hash,
        sections=sections,
        equations=equations,
        figures=figures,
        tables=tables,
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
