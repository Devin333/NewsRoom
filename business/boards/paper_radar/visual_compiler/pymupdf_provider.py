from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from business.boards.paper_radar.visual_compiler.models import (
    PAPER_DOCUMENT_SCHEMA_VERSION,
    PaperAssetManifest,
    PaperBlock,
    PaperCompileInfo,
    PaperDocument,
    PaperSourceRegion,
    PaperVisualAsset,
)
from business.boards.paper_radar.visual_compiler.model_layout_provider import (
    PaperLayoutProviderError,
    PaperVisualLayoutProvider,
)


_CAPTION_PATTERN = re.compile(
    r"^\s*(?P<kind>fig(?:ure)?|table)\s*\.?\s*(?P<label>[0-9IVXLC]+[A-Za-z]?)\s*[:.\-]?\s*(?P<caption>.*)$",
    re.IGNORECASE,
)
_SECTION_PATTERN = re.compile(
    r"^\s*(abstract|introduction|related work|background|method|methods|approach|experiment|experiments|evaluation|results|discussion|limitations?|conclusion|appendix|references)\s*$",
    re.IGNORECASE,
)
_NUMBERED_HEADING_PATTERN = re.compile(r"^\s*(\d+|[IVXLC]+)(?:\.\d+)*\.?\s+[A-Z][^\n]{2,90}$")
_EQUATION_LABEL_PATTERN = re.compile(r"\(\s*(?P<label>\d{1,3})\s*\)\s*$")
_MATH_PATTERN = re.compile(r"(?:=|≤|≥|∑|∫|√|\\sum|\\frac|\\mathbb|\\theta|\\lambda|\\argmax|\\min|\\max)")


@dataclass(frozen=True)
class PaperCompileDraft:
    document: PaperDocument
    manifest: PaperAssetManifest
    compile_info: PaperCompileInfo


class PaperCompilerError(RuntimeError):
    def __init__(self, message: str, *, code: str, diagnostics: Sequence[Mapping[str, Any]] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics = tuple(dict(item) for item in diagnostics)


class PyMuPDFPaperCompiler:
    provider_name = "pymupdf-heuristic-v1"

    def __init__(
        self,
        *,
        dpi: int = 300,
        layout_dpi: int = 120,
        max_visual_assets_per_page: int = 24,
        layout_provider: PaperVisualLayoutProvider | None = None,
    ) -> None:
        self.dpi = max(72, int(dpi))
        self.layout_dpi = max(72, min(int(layout_dpi), self.dpi))
        self.max_visual_assets_per_page = max(1, int(max_visual_assets_per_page))
        self.layout_provider = layout_provider

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
        if not pdf_bytes:
            raise PaperCompilerError("PDF content is empty", code="pdf_empty")
        try:
            import fitz  # type: ignore[import-not-found]
        except ImportError as exc:
            raise PaperCompilerError("PyMuPDF is required for paper visual compilation", code="pymupdf_missing") from exc

        started = _coerce_datetime(started_at)
        finished = _coerce_datetime(finished_at)
        paper_id = _text(paper.get("id"))
        title = _text(paper.get("title")) or _text(paper.get("titleZh")) or "Untitled Paper"
        if not paper_id:
            raise PaperCompilerError("paper id is required", code="paper_id_missing")
        source_hash = hashlib.sha256(pdf_bytes).hexdigest()

        output_dir.mkdir(parents=True, exist_ok=True)
        pages_dir = output_dir / "pages"
        assets_dir = output_dir / "assets"
        pages_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)
        source_pdf_path = output_dir / "source.pdf"
        source_pdf_path.write_bytes(pdf_bytes)

        try:
            pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:  # pragma: no cover - PyMuPDF raises broad implementation exceptions.
            raise PaperCompilerError(str(exc), code="pdf_open_failed") from exc

        all_blocks: list[PaperBlock] = []
        assets: list[PaperVisualAsset] = []
        diagnostics: list[Mapping[str, Any]] = []
        try:
            if len(pdf) == 0:
                raise PaperCompilerError("PDF has no pages", code="pdf_no_pages")
            for page_index, page in enumerate(pdf):
                page_number = page_index + 1
                page_assets, page_blocks, page_diagnostics = self._compile_page(
                    page=page,
                    paper_id=paper_id,
                    page_number=page_number,
                    pages_dir=pages_dir,
                    assets_dir=assets_dir,
                )
                assets.extend(page_assets)
                all_blocks.extend(page_blocks)
                diagnostics.extend(page_diagnostics)
        finally:
            pdf.close()

        if not any(block.text.strip() or block.assetId for block in all_blocks):
            raise PaperCompilerError("PDF produced no readable blocks", code="no_blocks", diagnostics=diagnostics)

        outline = tuple(_outline_from_blocks(all_blocks))
        document = PaperDocument(
            paperId=paper_id,
            schemaVersion=PAPER_DOCUMENT_SCHEMA_VERSION,
            status="needs_review",
            title=title,
            compiledAt=_iso(finished),
            sourceHash=source_hash,
            paper=_public_paper_metadata(paper),
            outline=outline,
            blocks=tuple(all_blocks),
            auxiliary=_auxiliary_metadata(paper),
        )
        manifest = PaperAssetManifest(
            paperId=paper_id,
            schemaVersion=PAPER_DOCUMENT_SCHEMA_VERSION,
            createdAt=_iso(finished),
            sourceHash=source_hash,
            assets=tuple(assets),
            sourcePdfFileName=source_pdf_path.name,
            provider=self._provider_name(),
        )
        compile_info = PaperCompileInfo(
            paperId=paper_id,
            status="needs_review",
            provider=self._provider_name(),
            sourceHash=source_hash,
            startedAt=_iso(started),
            finishedAt=_iso(finished),
            sourcePdfUrl=source_pdf_url,
            pageCount=len({asset.pageNumber for asset in assets if asset.kind == "page"}) or 0,
            blockCount=len(all_blocks),
            assetCount=len(assets),
            diagnostics=tuple(diagnostics),
        )
        return PaperCompileDraft(document=document, manifest=manifest, compile_info=compile_info)

    def render_source_preview(
        self,
        *,
        source_pdf_path: Path,
        page_number: int,
        bbox: tuple[float, float, float, float],
        output_path: Path,
        dpi: int | None = None,
    ) -> Path:
        try:
            import fitz  # type: ignore[import-not-found]
        except ImportError as exc:
            raise PaperCompilerError("PyMuPDF is required for source previews", code="pymupdf_missing") from exc
        if page_number <= 0:
            raise PaperCompilerError("page number must be positive", code="page_invalid")
        try:
            pdf = fitz.open(source_pdf_path)
        except Exception as exc:  # pragma: no cover
            raise PaperCompilerError(str(exc), code="source_pdf_open_failed") from exc
        try:
            if page_number > len(pdf):
                raise PaperCompilerError("page was not found", code="page_not_found")
            page = pdf[page_number - 1]
            clip = _rect_from_bbox(page, bbox, margin=6)
            if clip is None:
                raise PaperCompilerError("bbox is invalid", code="bbox_invalid")
            matrix = fitz.Matrix((dpi or self.dpi) / 72, (dpi or self.dpi) / 72)
            pixmap = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            pixmap.save(str(output_path))
        finally:
            pdf.close()
        return output_path

    def _compile_page(
        self,
        *,
        page: Any,
        paper_id: str,
        page_number: int,
        pages_dir: Path,
        assets_dir: Path,
    ) -> tuple[list[PaperVisualAsset], list[PaperBlock], list[Mapping[str, Any]]]:
        scale = self.dpi / 72
        matrix = page.parent._new_matrix(scale, scale) if hasattr(page.parent, "_new_matrix") else None
        if matrix is None:
            import fitz  # type: ignore[import-not-found]

            matrix = fitz.Matrix(scale, scale)

        page_rect = page.rect
        page_width = float(page_rect.width)
        page_height = float(page_rect.height)
        page_assets: list[PaperVisualAsset] = []
        diagnostics: list[Mapping[str, Any]] = []

        page_file = pages_dir / f"page-{page_number:04d}.png"
        page_pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        page_pixmap.save(str(page_file))
        page_assets.append(
            self._asset_from_file(
                paper_id=paper_id,
                kind="page",
                file_path=page_file,
                file_name=page_file.relative_to(pages_dir.parent).as_posix(),
                page_number=page_number,
                label=f"Page {page_number}",
                caption=None,
                source=PaperSourceRegion(
                    pageNumber=page_number,
                    bbox=(0.0, 0.0, page_width, page_height),
                    pageWidth=page_width,
                    pageHeight=page_height,
                ),
                pixmap=page_pixmap,
            )
        )

        text_blocks = _page_text_blocks(page)
        captions = [_caption_info(block) for block in text_blocks]
        captions = [caption for caption in captions if caption is not None]

        visual_assets: list[tuple[PaperVisualAsset, float, float]] = []
        visual_keys: set[str] = set()

        if self.layout_provider is not None:
            try:
                layout_image = _render_layout_image(page, dpi=self.layout_dpi)
                detection = self.layout_provider.detect_regions(
                    page_image_bytes=layout_image["bytes"],
                    page_number=page_number,
                    page_width=page_width,
                    page_height=page_height,
                    rendered_width=layout_image["width"],
                    rendered_height=layout_image["height"],
                    captions=captions,
                )
            except PaperLayoutProviderError as exc:
                diagnostics.append(
                    {
                        "severity": "warning" if exc.retryable else "error",
                        "code": exc.code,
                        "message": str(exc),
                        "pageNumber": page_number,
                    }
                )
            else:
                diagnostics.extend(detection.diagnostics)
                for region in detection.regions:
                    if len(visual_assets) >= self.max_visual_assets_per_page:
                        break
                    caption = _caption_for_model_region(region, captions, page_height=page_height)
                    label = region.label or _caption_label(caption) or _default_visual_label(region.kind)
                    caption_text = region.caption or _caption_text(caption) or label
                    asset = self._crop_visual_asset(
                        page=page,
                        matrix=matrix,
                        paper_id=paper_id,
                        page_number=page_number,
                        kind=region.kind,
                        label=label,
                        caption=caption_text,
                        bbox=region.bbox,
                        page_width=page_width,
                        page_height=page_height,
                        assets_dir=assets_dir,
                        metadata={
                            "layoutProvider": self.layout_provider.provider_name,
                            "layoutConfidence": region.confidence,
                            **dict(region.metadata),
                        },
                    )
                    if asset is None or asset.assetId in visual_keys:
                        continue
                    visual_keys.add(asset.assetId)
                    visual_assets.append((asset, asset.source.bbox[1] if asset.source else region.bbox[1], region.bbox[0]))

        if not visual_assets:
            diagnostics.append(
                {
                    "severity": "info",
                    "code": "heuristic_visual_layout_used",
                    "message": "heuristic visual layout extraction was used for this page",
                    "pageNumber": page_number,
                }
            )

        for block in _page_image_blocks(page):
            if len(visual_assets) >= self.max_visual_assets_per_page:
                break
            if _covered_by_visual_asset(block["bbox"], visual_assets):
                continue
            caption = _nearest_caption(block["bbox"], captions, page_height=page_height)
            if caption is None:
                diagnostics.append(
                    {
                        "severity": "warning",
                        "code": "uncaptioned_image_skipped",
                        "message": "image block was skipped because no nearby Figure/Table caption was detected",
                        "pageNumber": page_number,
                    }
                )
                continue
            asset = self._crop_visual_asset(
                page=page,
                matrix=matrix,
                paper_id=paper_id,
                page_number=page_number,
                kind=caption["kind"],
                label=caption["label"],
                caption=caption["text"],
                bbox=block["bbox"],
                page_width=page_width,
                page_height=page_height,
                assets_dir=assets_dir,
            )
            if asset is None or asset.assetId in visual_keys:
                continue
            visual_keys.add(asset.assetId)
            visual_assets.append((asset, asset.source.bbox[1] if asset.source else block["bbox"][1], block["bbox"][0]))

        for caption in captions:
            if len(visual_assets) >= self.max_visual_assets_per_page:
                break
            if _covered_by_visual_asset(caption["bbox"], visual_assets):
                continue
            if any(_rects_close(caption["bbox"], asset.source.bbox if asset.source else None) for asset, _, _ in visual_assets):
                continue
            crop_bbox = _caption_visual_bbox(caption, page_width=page_width, page_height=page_height)
            asset = self._crop_visual_asset(
                page=page,
                matrix=matrix,
                paper_id=paper_id,
                page_number=page_number,
                kind=caption["kind"],
                label=caption["label"],
                caption=caption["text"],
                bbox=crop_bbox,
                page_width=page_width,
                page_height=page_height,
                assets_dir=assets_dir,
            )
            if asset is None or asset.assetId in visual_keys:
                diagnostics.append(
                    {
                        "severity": "warning",
                        "code": "caption_crop_skipped",
                        "message": "caption could not be converted into a visual crop",
                        "pageNumber": page_number,
                        "label": caption["label"],
                    }
                )
                continue
            visual_keys.add(asset.assetId)
            visual_assets.append((asset, asset.source.bbox[1] if asset.source else crop_bbox[1], crop_bbox[0]))

        equation_count = 0
        for block in text_blocks:
            if len(visual_assets) >= self.max_visual_assets_per_page or equation_count >= 8:
                break
            equation = _equation_info(block)
            if equation is None:
                continue
            if _covered_by_visual_asset(equation["bbox"], visual_assets):
                continue
            asset = self._crop_visual_asset(
                page=page,
                matrix=matrix,
                paper_id=paper_id,
                page_number=page_number,
                kind="equation",
                label=equation["label"],
                caption=equation["text"],
                bbox=_expand_bbox(equation["bbox"], page_width=page_width, page_height=page_height, margin=8),
                page_width=page_width,
                page_height=page_height,
                assets_dir=assets_dir,
            )
            if asset is None or asset.assetId in visual_keys:
                continue
            equation_count += 1
            visual_keys.add(asset.assetId)
            visual_assets.append((asset, asset.source.bbox[1] if asset.source else equation["bbox"][1], equation["bbox"][0]))

        page_assets.extend(asset for asset, _, _ in visual_assets)
        content_items: list[tuple[float, float, PaperBlock]] = []
        current_section_id = f"{paper_id}:page-{page_number}"
        for index, block in enumerate(text_blocks, start=1):
            text = block["text"]
            if _caption_info(block) is not None:
                continue
            if _equation_info(block) is not None:
                continue
            if not text:
                continue
            block_type, level = _text_block_type(block, page_width=page_width)
            if block_type == "heading":
                current_section_id = _stable_id(paper_id, "section", str(page_number), text)[:40]
            content_items.append(
                (
                    block["bbox"][1],
                    block["bbox"][0],
                    PaperBlock(
                        id=_stable_id(paper_id, "block", str(page_number), str(index), text),
                        paperId=paper_id,
                        type=block_type,
                        text=text,
                        level=level,
                        pageNumber=page_number,
                        sectionId=current_section_id,
                        source=PaperSourceRegion(
                            pageNumber=page_number,
                            bbox=block["bbox"],
                            pageWidth=page_width,
                            pageHeight=page_height,
                        ),
                        metadata={"fontSize": block.get("fontSize")},
                    ),
                )
            )

        for visual_index, (asset, y, x) in enumerate(visual_assets, start=1):
            content_items.append(
                (
                    y,
                    x,
                    PaperBlock(
                        id=_stable_id(paper_id, "visual-block", asset.assetId),
                        paperId=paper_id,
                        type=asset.kind,  # type: ignore[arg-type]
                        text=asset.caption or asset.label or "",
                        pageNumber=page_number,
                        sectionId=current_section_id,
                        assetId=asset.assetId,
                        label=asset.label,
                        caption=asset.caption,
                        source=asset.source,
                        metadata={"visualIndex": visual_index},
                    ),
                )
            )
        content_items.sort(key=lambda item: (item[0], item[1]))
        return page_assets, [item[2] for item in content_items], diagnostics

    def _crop_visual_asset(
        self,
        *,
        page: Any,
        matrix: Any,
        paper_id: str,
        page_number: int,
        kind: str,
        label: str,
        caption: str | None,
        bbox: tuple[float, float, float, float],
        page_width: float,
        page_height: float,
        assets_dir: Path,
        metadata: Mapping[str, Any] | None = None,
    ) -> PaperVisualAsset | None:
        rect = _rect_from_bbox(page, bbox, margin=4)
        if rect is None or rect.width < 12 or rect.height < 12:
            return None
        asset_id = _stable_id(
            paper_id,
            "asset",
            kind,
            str(page_number),
            f"{rect.x0:.1f}",
            f"{rect.y0:.1f}",
            f"{rect.x1:.1f}",
            f"{rect.y1:.1f}",
        )
        file_path = assets_dir / f"{asset_id}.png"
        pixmap = page.get_pixmap(matrix=matrix, clip=rect, alpha=False)
        pixmap.save(str(file_path))
        return self._asset_from_file(
            paper_id=paper_id,
            kind=kind,
            file_path=file_path,
            file_name=file_path.relative_to(assets_dir.parent).as_posix(),
            page_number=page_number,
            label=label,
            caption=caption,
            source=PaperSourceRegion(
                pageNumber=page_number,
                bbox=(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)),
                pageWidth=page_width,
                pageHeight=page_height,
            ),
            pixmap=pixmap,
            asset_id=asset_id,
            metadata=metadata,
        )

    def _asset_from_file(
        self,
        *,
        paper_id: str,
        kind: str,
        file_path: Path,
        file_name: str,
        page_number: int,
        label: str | None,
        caption: str | None,
        source: PaperSourceRegion,
        pixmap: Any,
        asset_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> PaperVisualAsset:
        data = file_path.read_bytes()
        checksum = hashlib.sha256(data).hexdigest()
        return PaperVisualAsset(
            assetId=asset_id or _stable_id(paper_id, "asset", kind, str(page_number), file_name),
            paperId=paper_id,
            kind=kind,  # type: ignore[arg-type]
            fileName=file_name,
            mimeType="image/png",
            width=int(pixmap.width),
            height=int(pixmap.height),
            checksum=checksum,
            pageNumber=page_number,
            label=label,
            caption=caption,
            source=source,
            blankRatio=_pixmap_blank_ratio(pixmap),
            fileSize=len(data),
            metadata={key: value for key, value in {"dpi": self.dpi, **dict(metadata or {})}.items() if value is not None},
        )

    def _provider_name(self) -> str:
        if self.layout_provider is None:
            return self.provider_name
        return f"{self.provider_name}+{self.layout_provider.provider_name}"


def _page_text_blocks(page: Any) -> list[dict[str, Any]]:
    payload = page.get_text("dict")
    blocks: list[dict[str, Any]] = []
    for raw_block in payload.get("blocks", []):
        if raw_block.get("type") != 0:
            continue
        lines = raw_block.get("lines") or []
        line_texts: list[str] = []
        font_sizes: list[float] = []
        for line in lines:
            spans = line.get("spans") or []
            text = "".join(str(span.get("text") or "") for span in spans)
            text = _normalize_space(text)
            if text:
                line_texts.append(text)
            for span in spans:
                size = span.get("size")
                if isinstance(size, (int, float)) and math.isfinite(size):
                    font_sizes.append(float(size))
        text = _normalize_space("\n".join(line_texts))
        bbox = _bbox_tuple(raw_block.get("bbox"))
        if not text or bbox is None:
            continue
        blocks.append(
            {
                "text": text,
                "bbox": bbox,
                "fontSize": max(font_sizes) if font_sizes else None,
                "lineCount": len(line_texts),
            }
        )
    blocks.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return blocks


def _render_layout_image(page: Any, *, dpi: int) -> Mapping[str, Any]:
    import fitz  # type: ignore[import-not-found]

    scale = dpi / 72
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return {
        "bytes": pixmap.tobytes("png"),
        "width": int(pixmap.width),
        "height": int(pixmap.height),
    }


def _page_image_blocks(page: Any) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for raw_block in page.get_text("dict").get("blocks", []):
        if raw_block.get("type") != 1:
            continue
        bbox = _bbox_tuple(raw_block.get("bbox"))
        if bbox is not None:
            blocks.append({"bbox": bbox})
    blocks.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return blocks


def _caption_info(block: Mapping[str, Any]) -> dict[str, Any] | None:
    text = _normalize_space(str(block.get("text") or ""))
    match = _CAPTION_PATTERN.match(text)
    if not match:
        return None
    kind_text = match.group("kind").casefold()
    kind = "figure" if kind_text.startswith("fig") else "table"
    number = match.group("label")
    label = f"{'Figure' if kind == 'figure' else 'Table'} {number}"
    return {
        "kind": kind,
        "label": label,
        "text": text,
        "bbox": block["bbox"],
    }


def _equation_info(block: Mapping[str, Any]) -> dict[str, Any] | None:
    text = _normalize_space(str(block.get("text") or ""))
    bbox = block.get("bbox")
    if not text or not isinstance(bbox, tuple):
        return None
    width = max(0.0, bbox[2] - bbox[0])
    height = max(0.0, bbox[3] - bbox[1])
    if len(text) > 360 or height > 100:
        return None
    if not _MATH_PATTERN.search(text):
        return None
    label_match = _EQUATION_LABEL_PATTERN.search(text)
    label = f"Equation {label_match.group('label')}" if label_match else "Equation"
    if width < 80 and label == "Equation":
        return None
    return {"label": label, "text": text, "bbox": bbox}


def _nearest_caption(
    bbox: tuple[float, float, float, float],
    captions: Sequence[Mapping[str, Any]],
    *,
    page_height: float,
) -> Mapping[str, Any] | None:
    candidates: list[tuple[float, Mapping[str, Any]]] = []
    for caption in captions:
        caption_bbox = caption.get("bbox")
        if not isinstance(caption_bbox, tuple):
            continue
        vertical_gap = caption_bbox[1] - bbox[3] if caption_bbox[1] >= bbox[3] else bbox[1] - caption_bbox[3]
        if vertical_gap < -8 or vertical_gap > max(140.0, page_height * 0.18):
            continue
        overlap = _horizontal_overlap_ratio(bbox, caption_bbox)
        if overlap <= 0.1:
            continue
        candidates.append((vertical_gap + (1 - overlap) * 40, caption))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0])[0][1]


def _caption_for_model_region(
    region: Any,
    captions: Sequence[Mapping[str, Any]],
    *,
    page_height: float,
) -> Mapping[str, Any] | None:
    label = _normalize_label(getattr(region, "label", None))
    if label:
        for caption in captions:
            if _normalize_label(caption.get("label")) == label:
                return caption
    nearest = _nearest_caption(region.bbox, captions, page_height=page_height)
    if nearest is not None:
        return nearest
    for caption in captions:
        caption_bbox = caption.get("bbox")
        if isinstance(caption_bbox, tuple) and _horizontal_overlap_ratio(region.bbox, caption_bbox) > 0.1:
            return caption
    return None


def _caption_label(caption: Mapping[str, Any] | None) -> str | None:
    if caption is None:
        return None
    return _text(caption.get("label")) or None


def _caption_text(caption: Mapping[str, Any] | None) -> str | None:
    if caption is None:
        return None
    return _text(caption.get("text")) or None


def _default_visual_label(kind: str) -> str:
    if kind == "table":
        return "Table"
    if kind == "equation":
        return "Equation"
    return "Figure"


def _normalize_label(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _text(value).casefold())


def _covered_by_visual_asset(
    bbox: tuple[float, float, float, float],
    visual_assets: Sequence[tuple[PaperVisualAsset, float, float]],
) -> bool:
    for asset, _, _ in visual_assets:
        if asset.source is None:
            continue
        if _intersection_over_min_area(bbox, asset.source.bbox) >= 0.72:
            return True
    return False


def _intersection_over_min_area(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    overlap_width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    overlap_height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    intersection = overlap_width * overlap_height
    if intersection <= 0:
        return 0.0
    left_area = max(1.0, (left[2] - left[0]) * (left[3] - left[1]))
    right_area = max(1.0, (right[2] - right[0]) * (right[3] - right[1]))
    return intersection / min(left_area, right_area)


def _caption_visual_bbox(
    caption: Mapping[str, Any],
    *,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = caption["bbox"]
    crop_width = min(page_width - 48, max(x1 - x0 + 80, page_width * 0.55))
    center_x = (x0 + x1) / 2
    left = max(24.0, center_x - crop_width / 2)
    right = min(page_width - 24.0, left + crop_width)
    left = max(24.0, right - crop_width)
    if y0 > page_height * 0.22:
        top = max(24.0, y0 - min(260.0, page_height * 0.34))
        bottom = min(page_height - 24.0, y1 + 8)
    else:
        top = max(24.0, y0 - 8)
        bottom = min(page_height - 24.0, y1 + min(260.0, page_height * 0.34))
    return (left, top, right, bottom)


def _text_block_type(block: Mapping[str, Any], *, page_width: float) -> tuple[str, int | None]:
    text = _normalize_space(str(block.get("text") or ""))
    font_size = block.get("fontSize")
    bbox = block.get("bbox")
    width = bbox[2] - bbox[0] if isinstance(bbox, tuple) else page_width
    if _SECTION_PATTERN.match(text):
        return "heading", 1
    if _NUMBERED_HEADING_PATTERN.match(text):
        return "heading", 2 if "." in text.split(" ", 1)[0] else 1
    if isinstance(font_size, (int, float)) and font_size >= 14 and len(text) <= 120 and width <= page_width * 0.86:
        return "heading", 2
    return "paragraph", None


def _outline_from_blocks(blocks: Sequence[PaperBlock]) -> list[Mapping[str, Any]]:
    outline = [
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
    if outline:
        return outline
    pages: dict[int, int] = {}
    for block in blocks:
        if block.pageNumber is not None:
            pages.setdefault(block.pageNumber, 0)
            pages[block.pageNumber] += 1
    return [
        {"id": f"page-{page}", "title": f"Page {page}", "level": 1, "pageNumber": page, "blockCount": count}
        for page, count in sorted(pages.items())
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


def _rect_from_bbox(page: Any, bbox: tuple[float, float, float, float], *, margin: float) -> Any | None:
    import fitz  # type: ignore[import-not-found]

    x0, y0, x1, y1 = bbox
    rect = fitz.Rect(
        max(0.0, min(x0, x1) - margin),
        max(0.0, min(y0, y1) - margin),
        min(float(page.rect.width), max(x0, x1) + margin),
        min(float(page.rect.height), max(y0, y1) + margin),
    )
    if rect.is_empty or rect.is_infinite or rect.width <= 0 or rect.height <= 0:
        return None
    return rect


def _expand_bbox(
    bbox: tuple[float, float, float, float],
    *,
    page_width: float,
    page_height: float,
    margin: float,
) -> tuple[float, float, float, float]:
    return (
        max(0.0, bbox[0] - margin),
        max(0.0, bbox[1] - margin),
        min(page_width, bbox[2] + margin),
        min(page_height, bbox[3] + margin),
    )


def _bbox_tuple(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 4:
        coords: list[float] = []
        for item in value:
            if not isinstance(item, (int, float)) or not math.isfinite(item):
                return None
            coords.append(float(item))
        if coords[2] <= coords[0] or coords[3] <= coords[1]:
            return None
        return (coords[0], coords[1], coords[2], coords[3])
    return None


def _rects_close(left: tuple[float, float, float, float], right: tuple[float, float, float, float] | None) -> bool:
    if right is None:
        return False
    return sum(abs(a - b) for a, b in zip(left, right, strict=True)) < 30


def _horizontal_overlap_ratio(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    overlap = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    width = max(1.0, min(left[2] - left[0], right[2] - right[0]))
    return overlap / width


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


def _normalize_space(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", value.replace("\u00a0", " ")).strip()


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
