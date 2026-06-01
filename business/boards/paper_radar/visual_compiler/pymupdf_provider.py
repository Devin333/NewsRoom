from __future__ import annotations

import hashlib
import html
import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from pathlib import Path
from typing import Any

from business.boards.paper_radar.visual_compiler.models import (
    PAPER_DOCUMENT_SCHEMA_VERSION,
    PAPER_TABLE_MODEL_STYLE_SCHEMA_VERSION,
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
from business.boards.paper_radar.visual_compiler.base import PaperCompileDraft, PaperCompilerError


_CAPTION_PATTERN = re.compile(
    r"^\s*(?P<kind>fig(?:ure)?|table)\b\s*\.?\s*(?P<label>[0-9]+[A-Za-z]?|[IVXLC]+|[A-Za-z][0-9]*)\s*(?P<sep>[:.\-]?)\s*(?P<caption>.*)$",
    re.IGNORECASE,
)
_SECTION_PATTERN = re.compile(
    r"^\s*(abstract|introduction|related work|background|method|methods|approach|experiment|experiments|evaluation|results|discussion|limitations?|conclusion|appendix|references)\s*$",
    re.IGNORECASE,
)
_NUMBERED_HEADING_PATTERN = re.compile(r"^\s*(\d+|[IVXLC]+)(?:\.\d+)*\.?\s+[A-Z][^\n]{2,90}$")
_EQUATION_LABEL_PATTERN = re.compile(r"\(\s*(?P<label>\d{1,3})\s*\)\s*$")
_MATH_PATTERN = re.compile(r"(?:=|≤|≥|∑|∫|√|\\sum|\\frac|\\mathbb|\\theta|\\lambda|\\argmax|\\min|\\max)")
_PRIVATE_USE_PATTERN = re.compile(r"^[\ue000-\uf8ff\s]+$")
_PAGE_NUMBER_PATTERN = re.compile(r"^\d{1,3}$")
_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z-]*|\d+(?:\.\d+)?")
_HYPHENATED_LINE_END_PATTERN = re.compile(r"(?P<prefix>[A-Za-z][A-Za-z]+)[\-\u2010-\u2015]\s*$")
_COMPOUND_LINEBREAK_PREFIXES = {
    "cross",
    "fine",
    "identity",
    "image",
    "layer",
    "model",
    "modality",
    "multi",
    "one",
    "single",
    "stage",
    "state",
    "subject",
    "task",
    "text",
    "two",
    "zero",
}
_MAX_EQUATIONS_PER_PAGE = 12


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
        equation_items: list[tuple[Mapping[str, Any], float, float]] = []
        equation_keys: set[str] = set()

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
                    if region.kind == "equation":
                        if len(equation_items) >= _MAX_EQUATIONS_PER_PAGE:
                            continue
                        equation = _equation_from_model_region(region) or _equation_for_model_region(region, text_blocks)
                        if equation is None:
                            continue
                        if _covered_by_visual_asset(equation["bbox"], visual_assets):
                            continue
                        equation_key = _stable_id(paper_id, "equation", str(page_number), equation["text"], _bbox_key(equation["bbox"]))
                        if equation_key in equation_keys:
                            continue
                        equation_keys.add(equation_key)
                        equation_items.append((equation, equation["bbox"][1], equation["bbox"][0]))
                        continue
                    if len(visual_assets) >= self.max_visual_assets_per_page:
                        continue
                    caption = _caption_for_model_region(region, captions, page_height=page_height) if region.kind in {"figure", "table"} else None
                    label = region.label or _caption_label(caption) or _default_visual_label(region.kind)
                    caption_text = region.caption or _caption_text(caption) or label
                    crop_bbox = region.bbox
                    metadata = {
                        "layoutProvider": self.layout_provider.provider_name,
                        "layoutConfidence": region.confidence,
                        **dict(region.metadata),
                    }
                    if region.kind == "table":
                        crop_bbox = _table_visual_bbox_for_region(
                            region.bbox,
                            caption,
                            text_blocks,
                            page=page,
                            page_width=page_width,
                            page_height=page_height,
                        )
                        model_table_metadata = _table_metadata_from_existing_model(metadata, label=label)
                        table_metadata = _table_metadata_for_crop(
                            crop_bbox,
                            text_blocks,
                            page=page,
                            page_width=page_width,
                            page_height=page_height,
                            label=label,
                        )
                        if model_table_metadata and _table_metadata_has_text(model_table_metadata) and not _table_metadata_has_text(table_metadata):
                            metadata.update(model_table_metadata)
                        elif table_metadata:
                            metadata.update(table_metadata)
                        else:
                            metadata.update(model_table_metadata)
                    asset = self._crop_visual_asset(
                        page=page,
                        matrix=matrix,
                        paper_id=paper_id,
                        page_number=page_number,
                        kind=region.kind,
                        label=label,
                        caption=caption_text,
                        bbox=crop_bbox,
                        page_width=page_width,
                        page_height=page_height,
                        assets_dir=assets_dir,
                        metadata=metadata,
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

        visual_text_blocks: list[dict[str, Any]] = []
        image_blocks = _page_image_blocks(page)
        image_groups = _group_image_blocks_by_caption(
            image_blocks,
            captions,
            visual_assets,
            page_height=page_height,
        )
        for group in image_groups:
            if len(visual_assets) >= self.max_visual_assets_per_page:
                break
            caption = group["caption"]
            if _visual_asset_with_label_exists(caption["label"], visual_assets):
                continue
            crop_bbox = _visual_bbox_for_caption_group(
                group,
                text_blocks=text_blocks,
                page_width=page_width,
                page_height=page_height,
            )
            metadata = {"imageBlockCount": len(group["bboxes"])}
            if caption["kind"] == "table":
                metadata.update(
                    _table_metadata_for_crop(
                        crop_bbox,
                        text_blocks,
                        page=page,
                        page_width=page_width,
                        page_height=page_height,
                        label=caption["label"],
                    )
                )
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
                metadata=metadata,
            )
            if asset is None or asset.assetId in visual_keys:
                continue
            visual_keys.add(asset.assetId)
            visual_assets.append((asset, asset.source.bbox[1] if asset.source else crop_bbox[1], crop_bbox[0]))
            visual_text_blocks.extend(_visual_text_blocks_for_crop(crop_bbox, text_blocks, page_width=page_width, page_height=page_height))

        skipped_uncaptioned_images = sum(1 for block in image_blocks if not _image_block_has_caption(block["bbox"], captions, page_height=page_height))
        if skipped_uncaptioned_images:
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "uncaptioned_image_skipped",
                    "message": "image blocks were skipped because no nearby Figure/Table caption was detected",
                    "pageNumber": page_number,
                    "count": skipped_uncaptioned_images,
                }
            )

        for caption in captions:
            if len(visual_assets) >= self.max_visual_assets_per_page:
                break
            if _visual_asset_with_label_exists(caption["label"], visual_assets):
                continue
            if _covered_by_visual_asset(caption["bbox"], visual_assets):
                continue
            if any(_rects_close(caption["bbox"], asset.source.bbox if asset.source else None) for asset, _, _ in visual_assets):
                continue
            metadata = {}
            if caption["kind"] == "table":
                crop_bbox = _table_visual_bbox_for_caption(
                    caption,
                    text_blocks,
                    page=page,
                    page_width=page_width,
                    page_height=page_height,
                )
                metadata.update(
                    _table_metadata_for_crop(
                        crop_bbox,
                        text_blocks,
                        page=page,
                        page_width=page_width,
                        page_height=page_height,
                        label=caption["label"],
                    )
                )
            else:
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
                metadata=metadata,
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
            visual_text_blocks.extend(_visual_text_blocks_for_crop(crop_bbox, text_blocks, page_width=page_width, page_height=page_height))

        equation_count = len(equation_items)
        for block in text_blocks:
            if equation_count >= _MAX_EQUATIONS_PER_PAGE:
                break
            equation = _equation_info(block)
            if equation is None:
                continue
            if _covered_by_visual_asset(equation["bbox"], visual_assets):
                continue
            equation_key = _stable_id(paper_id, "equation", str(page_number), equation["text"], _bbox_key(equation["bbox"]))
            if equation_key in equation_keys:
                continue
            equation_count += 1
            equation_keys.add(equation_key)
            equation_items.append((equation, equation["bbox"][1], equation["bbox"][0]))

        equation_items = [
            (equation, y, x)
            for equation, y, x in equation_items
            if not _covered_by_visual_asset(equation["bbox"], visual_assets)
        ]
        page_assets.extend(asset for asset, _, _ in visual_assets)
        content_items: list[tuple[float, float, PaperBlock]] = []
        current_section_id = f"{paper_id}:page-{page_number}"
        section_ranges: list[tuple[float, str]] = [(0.0, current_section_id)]
        skipped_visual_text_blocks = 0
        skipped_noise_text_blocks = 0
        for index, block in enumerate(text_blocks, start=1):
            text = block["text"]
            if _caption_info(block) is not None:
                continue
            if _equation_info(block) is not None:
                continue
            if not text:
                continue
            skip_reason = _text_block_skip_reason(
                block,
                visual_assets,
                page_number=page_number,
                page_width=page_width,
                page_height=page_height,
            )
            if skip_reason is None and _text_block_matches_any(block, visual_text_blocks):
                skip_reason = "visual_annotation"
            if skip_reason == "visual_annotation":
                skipped_visual_text_blocks += 1
                continue
            if skip_reason is not None:
                skipped_noise_text_blocks += 1
                continue
            block_type, level = _text_block_type(block, page_width=page_width)
            if block_type == "heading":
                current_section_id = _stable_id(paper_id, "section", str(page_number), text)[:40]
                section_ranges.append((block["bbox"][1], current_section_id))
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
        if skipped_visual_text_blocks:
            diagnostics.append(
                {
                    "severity": "info",
                    "code": "visual_text_blocks_skipped",
                    "message": "text blocks inside or next to visual assets were excluded from the article body",
                    "pageNumber": page_number,
                    "count": skipped_visual_text_blocks,
                }
            )
        if skipped_noise_text_blocks:
            diagnostics.append(
                {
                    "severity": "info",
                    "code": "pdf_noise_text_blocks_skipped",
                    "message": "page-number or non-text glyph blocks were excluded from the article body",
                    "pageNumber": page_number,
                    "count": skipped_noise_text_blocks,
                }
            )

        for visual_index, (asset, y, x) in enumerate(visual_assets, start=1):
            block_metadata = {"visualIndex": visual_index}
            if asset.kind == "table":
                table_metadata = _table_metadata_from_asset(asset)
                if table_metadata:
                    block_metadata.update(table_metadata)
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
                        sectionId=_section_id_for_y(y, section_ranges),
                        assetId=asset.assetId,
                        label=asset.label,
                        caption=asset.caption,
                        source=asset.source,
                        metadata=block_metadata,
                    ),
                )
            )
        for equation_index, (equation, y, x) in enumerate(equation_items, start=1):
            equation_bbox = equation["bbox"]
            content_items.append(
                (
                    y,
                    x,
                    PaperBlock(
                        id=_stable_id(paper_id, "equation-block", str(page_number), equation["text"], _bbox_key(equation_bbox)),
                        paperId=paper_id,
                        type="equation",
                        text=equation["text"],
                        pageNumber=page_number,
                        sectionId=_section_id_for_y(y, section_ranges),
                        label=equation["label"],
                        caption=equation["text"],
                        source=PaperSourceRegion(
                            pageNumber=page_number,
                            bbox=equation_bbox,
                            pageWidth=page_width,
                            pageHeight=page_height,
                        ),
                        metadata={"equationIndex": equation_index, **dict(equation.get("metadata") or {})},
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
    page_words = _page_word_items(page)
    blocks: list[dict[str, Any]] = []
    for raw_block in payload.get("blocks", []):
        if raw_block.get("type") != 0:
            continue
        block_number = raw_block.get("number")
        lines = raw_block.get("lines") or []
        line_texts: list[str] = []
        font_sizes: list[float] = []
        line_items: list[dict[str, Any]] = []
        for line in lines:
            spans = line.get("spans") or []
            raw_text = "".join(str(span.get("text") or "") for span in spans)
            text = _normalize_space(raw_text)
            span_items: list[dict[str, Any]] = []
            span_bboxes: list[tuple[float, float, float, float]] = []
            if text:
                line_texts.append(text)
            for span in spans:
                size = span.get("size")
                if isinstance(size, (int, float)) and math.isfinite(size):
                    font_sizes.append(float(size))
                span_text = _normalize_space(str(span.get("text") or ""))
                span_bbox = _bbox_tuple(span.get("bbox"))
                if span_text and span_bbox is not None:
                    span_bboxes.append(span_bbox)
                    span_items.append(
                        {
                            "text": span_text,
                            "bbox": span_bbox,
                            "color": _pdf_color_to_hex(span.get("color")),
                        }
                    )
            line_bbox = _bbox_tuple(line.get("bbox")) or (_merged_bbox(span_bboxes) if span_bboxes else None)
            if text and line_bbox is not None:
                line_items.append(
                    {
                        "text": text,
                        "rawText": raw_text,
                        "bbox": line_bbox,
                        "spans": span_items,
                    }
                )
        text = _normalize_pdf_text_lines(line_texts)
        bbox = _bbox_tuple(raw_block.get("bbox"))
        if not text or bbox is None:
            continue
        block_words = [
            word
            for word in page_words
            if (
                (block_number is not None and word.get("blockNumber") == block_number)
                or _rect_center_inside(word["bbox"], _expand_bbox_xy(bbox, page_width=float(page.rect.width), page_height=float(page.rect.height), margin_x=1.0, margin_y=1.0))
            )
        ]
        for line_item in line_items:
            line_bbox = line_item["bbox"]
            line_item["words"] = [
                word
                for word in block_words
                if word.get("lineNumber") is None or _rect_center_inside(word["bbox"], _expand_bbox_xy(line_bbox, page_width=float(page.rect.width), page_height=float(page.rect.height), margin_x=2.0, margin_y=2.0))
            ]
        blocks.append(
            {
                "text": text,
                "bbox": bbox,
                "fontSize": max(font_sizes) if font_sizes else None,
                "lineCount": len(line_texts),
                "lines": line_items,
                "words": block_words,
            }
        )
    blocks.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return _merge_caption_continuations(blocks)


def _page_word_items(page: Any) -> list[dict[str, Any]]:
    try:
        raw_words = page.get_text("words", sort=True)
    except Exception:
        return []
    words: list[dict[str, Any]] = []
    for raw_word in raw_words:
        if not isinstance(raw_word, Sequence) or len(raw_word) < 5:
            continue
        bbox = _bbox_tuple(raw_word[:4])
        text = _normalize_space(str(raw_word[4] or ""))
        if bbox is None or not text:
            continue
        words.append(
            {
                "text": text,
                "bbox": bbox,
                "blockNumber": raw_word[5] if len(raw_word) > 5 and isinstance(raw_word[5], int) else None,
                "lineNumber": raw_word[6] if len(raw_word) > 6 and isinstance(raw_word[6], int) else None,
                "wordNumber": raw_word[7] if len(raw_word) > 7 and isinstance(raw_word[7], int) else None,
            }
        )
    return words


def _merge_caption_continuations(blocks: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index = 0
    while index < len(blocks):
        current = dict(blocks[index])
        caption = _caption_info(current)
        while caption is not None and _caption_needs_continuation(caption["text"]) and index + 1 < len(blocks):
            candidate = blocks[index + 1]
            if not _is_caption_continuation(current, candidate):
                break
            current = _merge_text_blocks(current, candidate)
            index += 1
            caption = _caption_info(current)
        merged.append(current)
        index += 1
    return merged


def _caption_needs_continuation(text: str) -> bool:
    if not text:
        return False
    if text.endswith((".", "。", "!", "?")):
        return False
    match = _CAPTION_PATTERN.match(text)
    return bool(match and not _normalize_space(match.group("caption")))


def _is_caption_continuation(current: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    current_bbox = current.get("bbox")
    candidate_bbox = candidate.get("bbox")
    if not isinstance(current_bbox, tuple) or not isinstance(candidate_bbox, tuple):
        return False
    if _caption_info(candidate) is not None or _equation_info(candidate) is not None:
        return False
    candidate_text = _normalize_space(str(candidate.get("text") or ""))
    if not candidate_text or _SECTION_PATTERN.match(candidate_text) or _NUMBERED_HEADING_PATTERN.match(candidate_text):
        return False
    vertical_gap = candidate_bbox[1] - current_bbox[3]
    if vertical_gap < -2 or vertical_gap > 24:
        return False
    return _horizontal_overlap_ratio(current_bbox, candidate_bbox) > 0.18 or abs(candidate_bbox[0] - current_bbox[0]) < 48


def _merge_text_blocks(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    left_bbox = left["bbox"]
    right_bbox = right["bbox"]
    return {
        "text": _normalize_space(f"{left.get('text') or ''} {right.get('text') or ''}"),
        "bbox": (
            min(left_bbox[0], right_bbox[0]),
            min(left_bbox[1], right_bbox[1]),
            max(left_bbox[2], right_bbox[2]),
            max(left_bbox[3], right_bbox[3]),
        ),
        "fontSize": max(
            value
            for value in (left.get("fontSize"), right.get("fontSize"))
            if isinstance(value, (int, float))
        ) if any(isinstance(value, (int, float)) for value in (left.get("fontSize"), right.get("fontSize"))) else None,
        "lineCount": int(left.get("lineCount") or 1) + int(right.get("lineCount") or 1),
    }


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


def _group_image_blocks_by_caption(
    image_blocks: Sequence[Mapping[str, Any]],
    captions: Sequence[Mapping[str, Any]],
    visual_assets: Sequence[tuple[PaperVisualAsset, float, float]],
    *,
    page_height: float,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for block in image_blocks:
        bbox = block.get("bbox")
        if not isinstance(bbox, tuple):
            continue
        if _covered_by_visual_asset(bbox, visual_assets):
            continue
        caption = _nearest_caption(bbox, captions, page_height=page_height)
        if caption is None:
            continue
        key = _normalize_label(caption.get("label")) or _bbox_key(caption["bbox"])
        existing = grouped.setdefault(key, {"caption": caption, "bboxes": []})
        existing["bboxes"].append(bbox)
    groups = [item for item in grouped.values() if item["bboxes"]]
    groups.sort(key=lambda item: (_merged_bbox(item["bboxes"])[1], _merged_bbox(item["bboxes"])[0]))
    return groups


def _image_block_has_caption(
    bbox: tuple[float, float, float, float],
    captions: Sequence[Mapping[str, Any]],
    *,
    page_height: float,
) -> bool:
    return _nearest_caption(bbox, captions, page_height=page_height) is not None


def _caption_info(block: Mapping[str, Any]) -> dict[str, Any] | None:
    text = _normalize_space(str(block.get("text") or ""))
    match = _CAPTION_PATTERN.match(_caption_match_text(text))
    if not match:
        return None
    caption_body = _normalize_space(match.group("caption") or "")
    if caption_body.startswith(")"):
        return None
    first_caption_word = _WORD_PATTERN.search(caption_body)
    if not match.group("sep") and first_caption_word is not None and first_caption_word.group(0)[:1].islower():
        return None
    kind_text = match.group("kind").casefold()
    kind = "figure" if kind_text.startswith("fig") else "table"
    number = match.group("label")
    label = f"{'Figure' if kind == 'figure' else 'Table'} {number}"
    return {
        "kind": kind,
        "label": label,
        "text": text,
        "bbox": _caption_bbox_for_block(block) or block["bbox"],
    }


def _caption_match_text(text: str) -> str:
    # Some PDFs expose a section label such as "Tables" in the same text block as
    # the real caption. Match the real caption, not the plural section heading.
    return re.sub(r"^\s*Tables\s+(?=Table\b)", "", text, flags=re.IGNORECASE)


def _caption_bbox_for_block(block: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    line_bboxes = _caption_line_bboxes(block)
    if line_bboxes:
        return _merged_bbox(line_bboxes)
    bbox = block.get("bbox")
    return bbox if isinstance(bbox, tuple) else None


def _caption_line_bboxes(block: Mapping[str, Any]) -> list[tuple[float, float, float, float]]:
    lines = block.get("lines")
    if not isinstance(lines, Sequence):
        return []
    caption_started = False
    bboxes: list[tuple[float, float, float, float]] = []
    for line in lines:
        if not isinstance(line, Mapping):
            continue
        line_text = _normalize_space(str(line.get("text") or ""))
        line_bbox = line.get("bbox")
        if not line_text or not isinstance(line_bbox, tuple):
            continue
        if _CAPTION_PATTERN.match(_caption_match_text(line_text)):
            caption_started = True
            bboxes.append(line_bbox)
            continue
        if not caption_started and line_text.casefold() in {"tables", "figures"}:
            bboxes.append(line_bbox)
            continue
        if caption_started and _looks_like_caption_continuation_line(line_text):
            bboxes.append(line_bbox)
            continue
        if caption_started:
            break
    return bboxes


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
    if not _looks_like_standalone_equation_text(text):
        return None
    label_match = _EQUATION_LABEL_PATTERN.search(text)
    label = f"Equation {label_match.group('label')}" if label_match else "Equation"
    if width < 80 and label == "Equation":
        return None
    return {"label": label, "text": text, "bbox": bbox}


def _text_block_skip_reason(
    block: Mapping[str, Any],
    visual_assets: Sequence[tuple[PaperVisualAsset, float, float]],
    *,
    page_number: int,
    page_width: float,
    page_height: float,
) -> str | None:
    text = _normalize_space(str(block.get("text") or ""))
    bbox = block.get("bbox")
    if not text or not isinstance(bbox, tuple):
        return "empty"
    if _PRIVATE_USE_PATTERN.fullmatch(text):
        return "private_use_glyphs"
    if _looks_like_pdf_mojibake(text):
        return "pdf_encoding_noise"
    if _is_page_number_text(text, bbox, page_number=page_number, page_width=page_width, page_height=page_height):
        return "page_number"
    if _is_arxiv_sidebar_text(text, bbox, page_width=page_width, page_height=page_height):
        return "arxiv_sidebar"
    if _looks_like_front_matter_noise(text, bbox, page_number=page_number, page_width=page_width, page_height=page_height):
        return "front_matter_noise"
    if _text_block_overlaps_visual_asset(bbox, visual_assets):
        return "visual_annotation"
    if _looks_like_table_row(text) and _text_block_near_visual_asset(
        bbox,
        visual_assets,
        page_width=page_width,
        page_height=page_height,
        margin_scale=0.07,
    ):
        return "visual_annotation"
    if _looks_like_short_visual_annotation(text) and _text_block_near_visual_asset(
        bbox,
        visual_assets,
        page_width=page_width,
        page_height=page_height,
        margin_scale=0.045,
    ):
        return "visual_annotation"
    return None


def _is_page_number_text(
    text: str,
    bbox: tuple[float, float, float, float],
    *,
    page_number: int,
    page_width: float,
    page_height: float,
) -> bool:
    if not _PAGE_NUMBER_PATTERN.fullmatch(text):
        return False
    if text != str(page_number):
        return False
    width = bbox[2] - bbox[0]
    return width <= page_width * 0.22 and (bbox[1] <= page_height * 0.16 or bbox[3] >= page_height * 0.78)


def _is_arxiv_sidebar_text(
    text: str,
    bbox: tuple[float, float, float, float],
    *,
    page_width: float,
    page_height: float,
) -> bool:
    if "arXiv:" not in text:
        return False
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    return bbox[0] <= page_width * 0.12 and height > page_height * 0.18 and width < page_width * 0.16


def _looks_like_front_matter_noise(
    text: str,
    bbox: tuple[float, float, float, float],
    *,
    page_number: int,
    page_width: float,
    page_height: float,
) -> bool:
    if page_number != 1:
        return False
    compact = _normalize_space(text)
    if not compact:
        return True
    if compact in {"Preprint."}:
        return True
    if compact.startswith(("†", "*", "‡")) or "Work done" in compact or "Joint Advising" in compact:
        return True
    if bbox[3] > page_height * 0.86 and len(compact) <= 80:
        return True
    if bbox[1] < page_height * 0.31:
        if re.search(r"\b(University|Institute|Adobe|Google|Department|Laboratory)\b", compact):
            return True
        if re.search(r"\d", compact) and len(_WORD_PATTERN.findall(compact)) <= 14:
            return True
        if bbox[0] > page_width * 0.18 and bbox[2] < page_width * 0.82 and len(compact) <= 160:
            return True
    return False


def _looks_like_pdf_mojibake(text: str) -> bool:
    if any(marker in text for marker in ("鈥", "鈭", "檚", "燡", "椻", "€")):
        return True
    if "\ufffd" in text:
        return True
    non_ascii = sum(1 for char in text if ord(char) > 127)
    if non_ascii >= 3 and non_ascii / max(1, len(text)) > 0.18 and not re.search(r"[\u4e00-\u9fff]", text):
        return True
    return False


def _looks_like_standalone_equation_text(text: str) -> bool:
    compact = _normalize_space(text)
    if not compact or _looks_like_pdf_mojibake(compact):
        return False
    if _EQUATION_LABEL_PATTERN.search(compact):
        return True
    if "\\" in compact:
        return True
    if re.search(r"[=≤≥∑∫√^_]", compact) is None:
        return False
    words = _WORD_PATTERN.findall(compact)
    math_symbols = re.findall(r"[=+\-*/^_(){}\[\]|,.;:≤≥∑∫√]", compact)
    if len(words) > 18 and len(math_symbols) < max(5, len(words) // 2):
        return False
    if len(compact) > 180 and len(math_symbols) < 10:
        return False
    return True


def _looks_like_short_visual_annotation(text: str) -> bool:
    if len(text) > 96:
        return False
    words = _WORD_PATTERN.findall(text)
    if not words:
        return True
    if len(words) <= 10:
        return True
    return False


def _looks_like_table_row(text: str) -> bool:
    compact = _normalize_space(text)
    if len(compact) < 12:
        return False
    numbers = re.findall(r"(?:\d+(?:\.\d+)?|\([+-]?\d+(?:\.\d+)?\)|[+-]\d+(?:\.\d+)?)", compact)
    if len(numbers) < 4:
        return False
    tokens = _WORD_PATTERN.findall(compact)
    if not tokens:
        return False
    numeric_ratio = len(numbers) / max(1, len(tokens))
    citation_count = len(re.findall(r"\[[0-9, ]+\]", compact))
    return numeric_ratio >= 0.28 or citation_count >= 2


def _table_metadata_for_crop(
    crop_bbox: tuple[float, float, float, float],
    text_blocks: Sequence[Mapping[str, Any]],
    *,
    page: Any,
    page_width: float,
    page_height: float,
    label: str,
) -> Mapping[str, Any]:
    model_bbox = _expand_bbox(crop_bbox, page_width=page_width, page_height=page_height, margin=4.0)
    model = _best_table_model_for_crop(
        model_bbox,
        text_blocks,
        page=page,
        page_width=page_width,
        page_height=page_height,
        label=label,
    )
    if not model:
        return {}
    table_html = _table_model_html(model, label=label)
    model_source_kind = str(model.get("sourceKind") or "")
    source_kind = "pdf-raster-table-model" if model_source_kind == "pdf-raster-table-model" else "pdf-text-table-model"
    return {
        "sourceKind": source_kind,
        "sourceMapping": "pdf-fallback",
        "tableModel": model,
        "tableHtml": table_html,
        "tableText": _table_model_text(model),
    }


def _best_table_model_for_crop(
    crop_bbox: tuple[float, float, float, float],
    text_blocks: Sequence[Mapping[str, Any]],
    *,
    page: Any,
    page_width: float,
    page_height: float,
    label: str,
) -> Mapping[str, Any] | None:
    candidates: list[tuple[float, int, Mapping[str, Any]]] = []
    original_words = _table_words_for_crop(crop_bbox, text_blocks, page_width=page_width, page_height=page_height)
    for table in _pymupdf_tables_near_crop(page, crop_bbox):
        table_model = _table_model_from_pymupdf_table(table, text_blocks=text_blocks, page=page, label=label)
        if table_model:
            candidates.append((_table_model_score(table_model), len(candidates), table_model))

    candidate_bboxes = [crop_bbox]
    if original_words:
        candidate_bboxes = _table_candidate_bboxes_for_crop(
            crop_bbox,
            text_blocks,
            page_width=page_width,
            page_height=page_height,
            label=label,
        )
    for candidate_bbox in candidate_bboxes:
        table_model = _table_model_for_crop(
            candidate_bbox,
            text_blocks,
            page=page,
            page_width=page_width,
            page_height=page_height,
            label=label,
        )
        if table_model:
            candidates.append((_table_model_score(table_model), len(candidates), table_model))
    raster_model = _raster_table_model_for_crop(
        crop_bbox,
        text_blocks,
        page=page,
        page_width=page_width,
        page_height=page_height,
        label=label,
    )
    if raster_model:
        candidates.append((_table_model_score(raster_model), len(candidates), raster_model))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], -item[1]))[2]


def _table_metadata_from_asset(asset: PaperVisualAsset) -> Mapping[str, Any]:
    metadata = asset.metadata if isinstance(asset.metadata, Mapping) else {}
    table_model = metadata.get("tableModel")
    table_html = metadata.get("tableHtml")
    if not isinstance(table_model, Mapping) or not isinstance(table_html, str) or not table_html.strip():
        return {}
    return {
        key: metadata[key]
        for key in ("sourceKind", "sourceMapping", "tableModel", "tableHtml", "tableText")
        if key in metadata and metadata[key] not in (None, "", [], {})
    }


def _table_metadata_from_existing_model(metadata: Mapping[str, Any], *, label: str) -> Mapping[str, Any]:
    table_model = _safe_table_model(metadata.get("tableModel"))
    if table_model is None:
        return {}
    table_html = _table_model_html(table_model, label=label)
    source_kind = str(metadata.get("sourceKind") or table_model.get("sourceKind") or "model-vision-table-model")
    return {
        "sourceKind": source_kind,
        "sourceMapping": metadata.get("sourceMapping") or "model-vision",
        "tableModel": table_model,
        "tableHtml": table_html,
        "tableText": _table_model_text(table_model),
    }


def _table_metadata_has_text(metadata: Mapping[str, Any]) -> bool:
    if not metadata:
        return False
    text = metadata.get("tableText")
    if isinstance(text, str) and text.strip():
        return True
    model = metadata.get("tableModel")
    if not isinstance(model, Mapping):
        return False
    for row in model.get("rows", []):
        if not isinstance(row, Mapping):
            continue
        for cell in row.get("cells", []):
            if isinstance(cell, Mapping) and _normalize_space(str(cell.get("text") or "")):
                return True
    return False


def _safe_table_model(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    raw_rows = value.get("rows")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        return None
    raw_alignments = value.get("alignments")
    alignments = [
        _safe_table_align(item)
        for item in raw_alignments
        if _safe_table_align(item) is not None
    ] if isinstance(raw_alignments, Sequence) and not isinstance(raw_alignments, (str, bytes)) else []
    rows: list[dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, Mapping):
            continue
        raw_cells = row.get("cells")
        if not isinstance(raw_cells, Sequence) or isinstance(raw_cells, (str, bytes)):
            continue
        cells: list[dict[str, Any]] = []
        for cell in raw_cells:
            if not isinstance(cell, Mapping):
                continue
            text = _normalize_space(_text(cell.get("text")) or _plain_text_from_html(cell.get("html")))
            style = _safe_table_style(cell.get("style"))
            payload: dict[str, Any] = {
                "text": text,
                "html": html.escape(text) if text else "",
                "colspan": _positive_span(cell.get("colspan")),
                "rowspan": _positive_span(cell.get("rowspan")),
                "align": _safe_table_align(cell.get("align")),
                "classes": _safe_table_classes(cell.get("classes")),
                "style": style,
            }
            if not payload["align"]:
                payload.pop("align")
            if not payload["classes"]:
                payload["classes"] = []
            cells.append(payload)
        if not cells:
            continue
        row_payload: dict[str, Any] = {"cells": cells}
        for key in ("rulesBefore", "rulesAfter"):
            rules = _safe_table_rules(row.get(key))
            if rules:
                row_payload[key] = rules
        for key in ("rowColor", "zebra"):
            classes = _safe_table_classes([row.get(key)])
            if classes:
                row_payload[key] = classes[0]
        for key in ("rowStyle", "zebraStyle"):
            style = _safe_table_style(row.get(key))
            if style:
                row_payload[key] = style
        rows.append(row_payload)
    if not rows:
        return None
    if not alignments:
        max_columns = max(len(row["cells"]) for row in rows)
        alignments = ["center"] * max_columns
    return {
        "version": 1,
        "styleSchemaVersion": PAPER_TABLE_MODEL_STYLE_SCHEMA_VERSION,
        "sourceKind": _text(value.get("sourceKind")) or "model-vision-table-model",
        "alignments": alignments,
        "rows": rows,
    }


def _table_visual_bbox_for_caption(
    caption: Mapping[str, Any],
    text_blocks: Sequence[Mapping[str, Any]],
    *,
    page: Any,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    label = _text(caption.get("label")) or "Table"
    default_bbox = _caption_visual_bbox(caption, page_width=page_width, page_height=page_height)
    scored: list[tuple[float, int, tuple[float, float, float, float]]] = []
    for table in _pymupdf_tables_near_crop(page, default_bbox):
        table_bbox = _bbox_tuple(getattr(table, "bbox", None))
        table_model = _table_model_from_pymupdf_table(table, text_blocks=text_blocks, page=page, label=label)
        if table_bbox is not None and table_model:
            scored.append((_table_model_score(table_model), len(scored), _expand_bbox(table_bbox, page_width=page_width, page_height=page_height, margin=4.0)))
    for candidate_bbox in _table_candidate_bboxes_for_caption(caption, page_width=page_width, page_height=page_height):
        model = _table_model_for_crop(
            candidate_bbox,
            text_blocks,
            page=page,
            page_width=page_width,
            page_height=page_height,
            label=label,
        )
        if model:
            scored.append((_table_model_score(model), len(scored), candidate_bbox))
    if scored:
        return max(scored, key=lambda item: (item[0], -item[1]))[2]
    return default_bbox


def _table_visual_bbox_for_region(
    region_bbox: tuple[float, float, float, float],
    caption: Mapping[str, Any] | None,
    text_blocks: Sequence[Mapping[str, Any]],
    *,
    page: Any,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    if caption is not None:
        return _table_visual_bbox_for_caption(
            caption,
            text_blocks,
            page=page,
            page_width=page_width,
            page_height=page_height,
        )
    tables = _pymupdf_tables_near_crop(page, region_bbox)
    if tables:
        table_bbox = _bbox_tuple(getattr(tables[0], "bbox", None))
        if table_bbox is not None:
            return _expand_bbox(table_bbox, page_width=page_width, page_height=page_height, margin=4.0)
    return region_bbox


def _table_candidate_bboxes_for_crop(
    crop_bbox: tuple[float, float, float, float],
    text_blocks: Sequence[Mapping[str, Any]],
    *,
    page_width: float,
    page_height: float,
    label: str,
) -> list[tuple[float, float, float, float]]:
    candidates = [crop_bbox]
    captions = [
        caption
        for block in text_blocks
        if (caption := _caption_info(block)) is not None and caption["kind"] == "table"
    ]
    normalized_label = _normalize_label(label)
    for caption in captions:
        caption_bbox = caption.get("bbox")
        if not isinstance(caption_bbox, tuple):
            continue
        label_matches = normalized_label and _normalize_label(caption.get("label")) == normalized_label
        near_crop = _rect_center_inside(caption_bbox, _expand_bbox_xy(crop_bbox, page_width=page_width, page_height=page_height, margin_x=page_width * 0.08, margin_y=page_height * 0.18))
        if not label_matches and not near_crop:
            continue
        candidates.extend(_table_candidate_bboxes_for_caption(caption, page_width=page_width, page_height=page_height))
    return _dedupe_bboxes(candidates)


def _table_candidate_bboxes_for_caption(
    caption: Mapping[str, Any],
    *,
    page_width: float,
    page_height: float,
) -> list[tuple[float, float, float, float]]:
    caption_bbox = caption.get("bbox")
    if not isinstance(caption_bbox, tuple):
        return []
    left, right = _table_horizontal_bounds_for_caption(caption_bbox, page_width=page_width)
    vertical_window = max(220.0, page_height * 0.46)
    above = (
        left,
        max(20.0, caption_bbox[1] - vertical_window),
        right,
        max(20.0, caption_bbox[1] - 2.0),
    )
    below = (
        left,
        min(page_height - 20.0, caption_bbox[3] + 2.0),
        right,
        min(page_height - 20.0, caption_bbox[3] + vertical_window),
    )
    return [above, below]


def _table_horizontal_bounds_for_caption(
    caption_bbox: tuple[float, float, float, float],
    *,
    page_width: float,
) -> tuple[float, float]:
    caption_width = caption_bbox[2] - caption_bbox[0]
    center_x = (caption_bbox[0] + caption_bbox[2]) / 2
    if caption_width < page_width * 0.58:
        if center_x > page_width * 0.52:
            return max(20.0, caption_bbox[0] - 4.0), page_width - 20.0
        if center_x < page_width * 0.48 and caption_bbox[2] < page_width * 0.72:
            return 20.0, min(page_width - 20.0, max(caption_bbox[2] + page_width * 0.36, page_width * 0.58))
    return 20.0, page_width - 20.0


def _pymupdf_tables_near_crop(page: Any, crop_bbox: tuple[float, float, float, float]) -> list[Any]:
    try:
        finder = page.find_tables()
        tables = list(getattr(finder, "tables", []) or [])
    except Exception:
        return []
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)
    guard = _expand_bbox_xy(
        crop_bbox,
        page_width=page_width,
        page_height=page_height,
        margin_x=max(16.0, page_width * 0.04),
        margin_y=max(36.0, page_height * 0.08),
    )
    related: list[Any] = []
    for table in tables:
        table_bbox = _bbox_tuple(getattr(table, "bbox", None))
        if table_bbox is None:
            continue
        if _intersection_over_min_area(table_bbox, guard) > 0 or _rect_center_inside(table_bbox, guard):
            related.append(table)
    return related


def _table_model_from_pymupdf_table(
    table: Any,
    *,
    text_blocks: Sequence[Mapping[str, Any]],
    page: Any,
    label: str,
) -> Mapping[str, Any] | None:
    table_bbox = _bbox_tuple(getattr(table, "bbox", None))
    if table_bbox is None:
        return None
    try:
        extracted = table.extract()
    except Exception:
        return None
    if not isinstance(extracted, Sequence) or not extracted:
        return None
    rows_attr = getattr(table, "rows", []) or []
    rows_payload: list[dict[str, Any]] = []
    max_columns = max((len(row) for row in extracted if isinstance(row, Sequence) and not isinstance(row, (str, bytes))), default=0)
    if max_columns <= 0:
        return None
    drawings = _table_drawing_primitives(page, table_bbox)
    alignments = ["center"] * max_columns
    for row_index, row in enumerate(extracted):
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
            continue
        row_cells = getattr(rows_attr[row_index], "cells", []) if row_index < len(rows_attr) else []
        cells: list[dict[str, Any]] = []
        cell_bboxes: list[tuple[float, float, float, float]] = []
        for column_index in range(max_columns):
            text = _normalize_space(str(row[column_index] or "")) if column_index < len(row) else ""
            raw_bbox = row_cells[column_index] if column_index < len(row_cells) else None
            cell_bbox = _bbox_tuple(raw_bbox) or _synthetic_table_cell_bbox(table_bbox, row_index, column_index, len(extracted), max_columns)
            cell_bboxes.append(cell_bbox)
            cells.append(
                _table_cell_payload(
                    {"text": text, "bbox": cell_bbox},
                    text_blocks=text_blocks,
                    fills=drawings["fills"],
                    default_align=alignments[column_index],
                    header=row_index == 0,
                )
            )
        if not any(cell["text"] for cell in cells):
            continue
        row_bbox = _merged_bbox(cell_bboxes)
        row_payload: dict[str, Any] = {
            "cells": cells,
            "rulesBefore": _rules_before_row(row_bbox, row_index=row_index, horizontal_rules=drawings["horizontalRules"]),
        }
        row_style = _table_background_style(row_bbox, drawings["fills"], min_overlap=0.58)
        if row_style:
            row_payload["rowStyle"] = row_style
        if row_index == len(extracted) - 1:
            rules_after = _rules_after_row(row_bbox, horizontal_rules=drawings["horizontalRules"])
            if rules_after:
                row_payload["rulesAfter"] = rules_after
        rows_payload.append(row_payload)
    if not rows_payload:
        return None
    if "rulesAfter" not in rows_payload[-1]:
        rows_payload[-1]["rulesAfter"] = ["bottomrule"]
    return {
        "version": 1,
        "styleSchemaVersion": PAPER_TABLE_MODEL_STYLE_SCHEMA_VERSION,
        "sourceKind": "pdf-detected-table-model",
        "alignments": alignments,
        "rows": rows_payload,
        "sourceLabel": label,
    }


def _synthetic_table_cell_bbox(
    table_bbox: tuple[float, float, float, float],
    row_index: int,
    column_index: int,
    row_count: int,
    column_count: int,
) -> tuple[float, float, float, float]:
    width = max(1.0, (table_bbox[2] - table_bbox[0]) / max(1, column_count))
    height = max(1.0, (table_bbox[3] - table_bbox[1]) / max(1, row_count))
    return (
        table_bbox[0] + column_index * width,
        table_bbox[1] + row_index * height,
        table_bbox[0] + (column_index + 1) * width,
        table_bbox[1] + (row_index + 1) * height,
    )


def _table_model_score(model: Mapping[str, Any]) -> float:
    rows = [row for row in model.get("rows", []) if isinstance(row, Mapping)]
    cell_counts = [
        len([cell for cell in row.get("cells", []) if isinstance(cell, Mapping) and _normalize_space(str(cell.get("text") or ""))])
        for row in rows
    ]
    multi_cell_rows = sum(1 for count in cell_counts if count >= 2)
    non_empty_cells = sum(cell_counts)
    return float(multi_cell_rows * 20 + non_empty_cells + len(rows))


def _table_model_for_crop(
    crop_bbox: tuple[float, float, float, float],
    text_blocks: Sequence[Mapping[str, Any]],
    *,
    page: Any,
    page_width: float,
    page_height: float,
    label: str,
) -> Mapping[str, Any] | None:
    words = _table_words_for_crop(crop_bbox, text_blocks, page_width=page_width, page_height=page_height)
    if not words:
        return None
    row_groups = _cluster_table_rows(words)
    if not row_groups:
        return None
    drawings = _table_drawing_primitives(page, crop_bbox)
    rows_with_geometry = _table_rows_from_word_groups(row_groups, text_blocks=text_blocks, drawings=drawings)
    multi_cell_rows = [row for row in rows_with_geometry if len(row["cells"]) >= 2]
    if not multi_cell_rows:
        return None
    first_y = min(row["bbox"][1] for row in multi_cell_rows)
    last_y = max(row["bbox"][3] for row in multi_cell_rows)
    rows_with_geometry = [
        row
        for row in rows_with_geometry
        if first_y - 18 <= row["bbox"][1] <= last_y + 18
        and (len(row["cells"]) >= 2 or _looks_like_table_heading_row(row["text"]))
    ]
    if not rows_with_geometry:
        return None

    max_columns = min(20, max(len(row["cells"]) for row in rows_with_geometry))
    alignments = _infer_table_alignments(rows_with_geometry, max_columns)
    rows: list[dict[str, Any]] = []
    horizontal_rules = drawings["horizontalRules"]
    for row_index, row in enumerate(rows_with_geometry):
        row_bbox = row["bbox"]
        row_payload: dict[str, Any] = {
            "cells": [
                _table_cell_payload(
                    cell,
                    text_blocks=text_blocks,
                    fills=drawings["fills"],
                    default_align=alignments[min(cell_index, len(alignments) - 1)] if alignments else "center",
                    header=row_index == 0,
                )
                for cell_index, cell in enumerate(row["cells"][:max_columns])
            ],
            "rulesBefore": _rules_before_row(row_bbox, row_index=row_index, horizontal_rules=horizontal_rules),
        }
        row_style = _table_background_style(row_bbox, drawings["fills"], min_overlap=0.58)
        if row_style:
            row_payload["rowStyle"] = row_style
        if row_index == len(rows_with_geometry) - 1:
            rules_after = _rules_after_row(row_bbox, horizontal_rules=horizontal_rules)
            if rules_after:
                row_payload["rulesAfter"] = rules_after
        rows.append(row_payload)

    if rows and "rulesAfter" not in rows[-1]:
        rows[-1]["rulesAfter"] = ["bottomrule"]
    return {
        "version": 1,
        "styleSchemaVersion": PAPER_TABLE_MODEL_STYLE_SCHEMA_VERSION,
        "sourceKind": "pdf-text-table-model",
        "alignments": alignments,
        "rows": rows,
    }


def _raster_table_model_for_crop(
    crop_bbox: tuple[float, float, float, float],
    text_blocks: Sequence[Mapping[str, Any]],
    *,
    page: Any,
    page_width: float,
    page_height: float,
    label: str,
) -> Mapping[str, Any] | None:
    raster = _render_table_crop_array(page, crop_bbox)
    if raster is None:
        return None
    pixels, rect = raster
    geometry = _raster_table_geometry(pixels, rect=rect)
    if geometry is None:
        return None
    rows_payload: list[dict[str, Any]] = []
    alignments = ["center"] * max(1, len(geometry["xBounds"]) - 1)
    for row_index, (top, bottom) in enumerate(zip(geometry["yBounds"], geometry["yBounds"][1:])):
        cells: list[dict[str, Any]] = []
        cell_bboxes: list[tuple[float, float, float, float]] = []
        for column_index, (left, right) in enumerate(zip(geometry["xBounds"], geometry["xBounds"][1:])):
            cell_bbox = (left, top, right, bottom)
            cell_bboxes.append(cell_bbox)
            style = _raster_cell_background_style(
                pixels,
                cell_bbox,
                rect=rect,
                table_bbox=geometry["tableBBox"],
            )
            cells.append(
                {
                    "text": "",
                    "html": "",
                    "colspan": 1,
                    "rowspan": 1,
                    "align": alignments[column_index],
                    "classes": [],
                    "style": style,
                }
            )
        if not cells:
            continue
        row_bbox = _merged_bbox(cell_bboxes)
        row_payload: dict[str, Any] = {
            "cells": cells,
            "rulesBefore": ["toprule"] if row_index == 0 else ["midrule"],
        }
        row_style = _raster_row_background_style(cells)
        if row_style:
            row_payload["rowStyle"] = row_style
        if row_index == len(geometry["yBounds"]) - 2:
            row_payload["rulesAfter"] = ["bottomrule"]
        rows_payload.append(row_payload)
    if not rows_payload:
        return None
    return {
        "version": 1,
        "styleSchemaVersion": PAPER_TABLE_MODEL_STYLE_SCHEMA_VERSION,
        "sourceKind": "pdf-raster-table-model",
        "sourceLabel": label,
        "textExtraction": "unavailable",
        "alignments": alignments,
        "rows": rows_payload,
    }


def _render_table_crop_array(
    page: Any,
    crop_bbox: tuple[float, float, float, float],
) -> tuple[Any, tuple[float, float, float, float]] | None:
    try:
        import fitz  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except Exception:
        return None
    rect = _rect_from_bbox(page, crop_bbox, margin=0)
    if rect is None or rect.width < 24 or rect.height < 24:
        return None
    scale = min(4.0, max(2.0, 180.0 / 72.0))
    try:
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
    except Exception:
        return None
    if pixmap.width < 24 or pixmap.height < 24 or pixmap.n <= 0:
        return None
    try:
        array = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape((pixmap.height, pixmap.width, pixmap.n))
    except ValueError:
        return None
    if pixmap.n == 1:
        array = np.repeat(array, 3, axis=2)
    elif pixmap.n >= 3:
        array = array[:, :, :3]
    else:
        return None
    return array, (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def _raster_table_geometry(
    pixels: Any,
    *,
    rect: tuple[float, float, float, float],
) -> Mapping[str, Any] | None:
    gray = pixels.mean(axis=2)
    dark = gray < min(225.0, max(90.0, float(gray.mean()) - 18.0))
    height, width = dark.shape
    if height < 24 or width < 24:
        return None
    horizontal_clusters = _raster_line_clusters(dark, axis=1, min_coverage=0.48)
    vertical_clusters = _raster_line_clusters(dark, axis=0, min_coverage=0.52)
    if len(horizontal_clusters) < 2:
        return None
    horizontal_positions = _raster_cluster_centers(horizontal_clusters)
    horizontal_extents = [_raster_line_extent(dark, cluster, axis=1) for cluster in horizontal_clusters]
    horizontal_extents = [extent for extent in horizontal_extents if extent is not None]
    if not horizontal_extents:
        return None
    table_x0_px = max(0, min(extent[0] for extent in horizontal_extents))
    table_x1_px = min(width - 1, max(extent[1] for extent in horizontal_extents))
    content_bbox = _raster_dark_content_bbox(dark)
    if content_bbox is not None:
        table_x0_px = max(0, min(table_x0_px, content_bbox[0]))
        table_x1_px = min(width - 1, max(table_x1_px, content_bbox[2]))
    if table_x1_px - table_x0_px < max(24, width * 0.18):
        return None

    y_positions = sorted(horizontal_positions)
    if content_bbox is not None:
        bottom_gap = content_bbox[3] - y_positions[-1]
        row_height = _median([float(b - a) for a, b in zip(y_positions, y_positions[1:])])
        if bottom_gap > max(8.0, row_height * 0.45):
            y_positions.append(min(height - 1, content_bbox[3] + 3))
    y_positions = _dedupe_raster_positions(y_positions, min_gap=5)
    if len(y_positions) < 2:
        return None

    x_positions = sorted(_raster_cluster_centers(vertical_clusters))
    x_positions = [
        position
        for position in x_positions
        if table_x0_px - 4 <= position <= table_x1_px + 4
    ]
    if not x_positions or abs(x_positions[0] - table_x0_px) > 5:
        x_positions.insert(0, table_x0_px)
    if abs(x_positions[-1] - table_x1_px) > 5:
        x_positions.append(table_x1_px)
    x_positions = _dedupe_raster_positions(x_positions, min_gap=5)
    if len(x_positions) < 2:
        return None
    if len(x_positions) > 24 or len(y_positions) > 80:
        return None

    x_bounds = [_pixel_x_to_pdf(position, rect=rect, width=width) for position in x_positions]
    y_bounds = [_pixel_y_to_pdf(position, rect=rect, height=height) for position in y_positions]
    table_bbox = (x_bounds[0], y_bounds[0], x_bounds[-1], y_bounds[-1])
    if table_bbox[2] - table_bbox[0] < 16 or table_bbox[3] - table_bbox[1] < 16:
        return None
    return {"xBounds": x_bounds, "yBounds": y_bounds, "tableBBox": table_bbox}


def _raster_line_clusters(mask: Any, *, axis: int, min_coverage: float) -> list[tuple[int, int]]:
    projection = mask.mean(axis=1 if axis == 1 else 0)
    indexes = [int(index) for index, value in enumerate(projection) if float(value) >= min_coverage]
    if not indexes:
        return []
    clusters: list[tuple[int, int]] = []
    start = previous = indexes[0]
    for index in indexes[1:]:
        if index <= previous + 2:
            previous = index
            continue
        clusters.append((start, previous))
        start = previous = index
    clusters.append((start, previous))
    return [cluster for cluster in clusters if cluster[1] - cluster[0] <= 14]


def _raster_cluster_centers(clusters: Sequence[tuple[int, int]]) -> list[int]:
    return [int(round((start + end) / 2)) for start, end in clusters]


def _raster_line_extent(mask: Any, cluster: tuple[int, int], *, axis: int) -> tuple[int, int] | None:
    if axis == 1:
        line = mask[max(0, cluster[0]) : cluster[1] + 1, :].any(axis=0)
    else:
        line = mask[:, max(0, cluster[0]) : cluster[1] + 1].any(axis=1)
    indexes = [int(index) for index, value in enumerate(line) if bool(value)]
    if not indexes:
        return None
    return indexes[0], indexes[-1]


def _raster_dark_content_bbox(mask: Any) -> tuple[int, int, int, int] | None:
    ys, xs = mask.nonzero()
    if len(xs) == 0 or len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _dedupe_raster_positions(positions: Sequence[int], *, min_gap: int) -> list[int]:
    deduped: list[int] = []
    for position in sorted(int(item) for item in positions):
        if deduped and position - deduped[-1] < min_gap:
            deduped[-1] = int(round((deduped[-1] + position) / 2))
            continue
        deduped.append(position)
    return deduped


def _pixel_x_to_pdf(value: int, *, rect: tuple[float, float, float, float], width: int) -> float:
    return rect[0] + (float(value) / max(1.0, float(width - 1))) * (rect[2] - rect[0])


def _pixel_y_to_pdf(value: int, *, rect: tuple[float, float, float, float], height: int) -> float:
    return rect[1] + (float(value) / max(1.0, float(height - 1))) * (rect[3] - rect[1])


def _pdf_bbox_to_pixel_bounds(
    bbox: tuple[float, float, float, float],
    *,
    rect: tuple[float, float, float, float],
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    rect_width = max(1.0, rect[2] - rect[0])
    rect_height = max(1.0, rect[3] - rect[1])
    x0 = int(max(0, min(width - 1, round((bbox[0] - rect[0]) * (width - 1) / rect_width))))
    x1 = int(max(0, min(width, round((bbox[2] - rect[0]) * (width - 1) / rect_width))))
    y0 = int(max(0, min(height - 1, round((bbox[1] - rect[1]) * (height - 1) / rect_height))))
    y1 = int(max(0, min(height, round((bbox[3] - rect[1]) * (height - 1) / rect_height))))
    if x1 <= x0:
        x1 = min(width, x0 + 1)
    if y1 <= y0:
        y1 = min(height, y0 + 1)
    return x0, y0, x1, y1


def _raster_cell_background_style(
    pixels: Any,
    cell_bbox: tuple[float, float, float, float],
    *,
    rect: tuple[float, float, float, float],
    table_bbox: tuple[float, float, float, float],
) -> dict[str, str]:
    height, width = pixels.shape[:2]
    x0, y0, x1, y1 = _pdf_bbox_to_pixel_bounds(cell_bbox, rect=rect, width=width, height=height)
    inset_x = max(1, int((x1 - x0) * 0.08))
    inset_y = max(1, int((y1 - y0) * 0.12))
    sample = pixels[y0 + inset_y : max(y0 + inset_y + 1, y1 - inset_y), x0 + inset_x : max(x0 + inset_x + 1, x1 - inset_x), :]
    if sample.size == 0:
        return {}
    gray = sample.mean(axis=2)
    background_pixels = sample[gray > 110]
    if background_pixels.size == 0:
        background_pixels = sample.reshape((-1, 3))
    median = background_pixels.reshape((-1, 3)).mean(axis=0)
    color = "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, int(round(float(median[0]))))),
        max(0, min(255, int(round(float(median[1]))))),
        max(0, min(255, int(round(float(median[2]))))),
    )
    if not _is_visible_table_fill(color):
        return {}
    table_style = _raster_table_background_style(pixels, table_bbox, rect=rect)
    if table_style.get("backgroundColor") == color:
        return {}
    return {"backgroundColor": color}


def _raster_table_background_style(
    pixels: Any,
    table_bbox: tuple[float, float, float, float],
    *,
    rect: tuple[float, float, float, float],
) -> dict[str, str]:
    height, width = pixels.shape[:2]
    x0, y0, x1, y1 = _pdf_bbox_to_pixel_bounds(table_bbox, rect=rect, width=width, height=height)
    sample = pixels[y0:y1, x0:x1, :]
    if sample.size == 0:
        return {}
    gray = sample.mean(axis=2)
    background_pixels = sample[gray > 140]
    if background_pixels.size == 0:
        return {}
    median = background_pixels.reshape((-1, 3)).mean(axis=0)
    color = "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, int(round(float(median[0]))))),
        max(0, min(255, int(round(float(median[1]))))),
        max(0, min(255, int(round(float(median[2]))))),
    )
    return {"backgroundColor": color} if _is_visible_table_fill(color) else {}


def _raster_row_background_style(cells: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    colors = [
        style["backgroundColor"]
        for cell in cells
        for style in [cell.get("style")]
        if isinstance(style, Mapping) and isinstance(style.get("backgroundColor"), str)
    ]
    if not colors:
        return {}
    rgb_values = [_hex_rgb(color) for color in colors]
    if len(colors) == len(cells) and all(value is not None for value in rgb_values):
        channels = list(zip(*(value for value in rgb_values if value is not None)))
        if all(max(channel) - min(channel) <= 10 for channel in channels):
            average = tuple(int(round(sum(channel) / len(channel))) for channel in channels)
            return {"backgroundColor": f"#{average[0]:02x}{average[1]:02x}{average[2]:02x}"}
    dominant = max(set(colors), key=colors.count)
    return {"backgroundColor": dominant} if colors.count(dominant) == len(cells) else {}


def _hex_rgb(value: str) -> tuple[int, int, int] | None:
    if not _is_safe_table_css_color(value):
        return None
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def _table_words_for_crop(
    crop_bbox: tuple[float, float, float, float],
    text_blocks: Sequence[Mapping[str, Any]],
    *,
    page_width: float,
    page_height: float,
) -> list[dict[str, Any]]:
    guard = _expand_bbox_xy(
        crop_bbox,
        page_width=page_width,
        page_height=page_height,
        margin_x=max(3.0, page_width * 0.006),
        margin_y=max(3.0, page_height * 0.006),
    )
    caption_bboxes = _caption_exclusion_bboxes(text_blocks)
    words: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for block in text_blocks:
        block_words = block.get("words")
        if not isinstance(block_words, Sequence):
            continue
        for word in block_words:
            if not isinstance(word, Mapping):
                continue
            text = _normalize_space(str(word.get("text") or ""))
            bbox = word.get("bbox")
            if not text or not isinstance(bbox, tuple):
                continue
            if not _rect_center_inside(bbox, guard):
                continue
            if any(_rect_center_inside(bbox, caption_bbox) for caption_bbox in caption_bboxes):
                continue
            if _is_structural_table_noise(text):
                continue
            key = (text, _bbox_key(bbox))
            if key in seen:
                continue
            seen.add(key)
            words.append({"text": text, "bbox": bbox})
    words.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return words


def _caption_exclusion_bboxes(text_blocks: Sequence[Mapping[str, Any]]) -> list[tuple[float, float, float, float]]:
    bboxes: list[tuple[float, float, float, float]] = []
    for block in text_blocks:
        if _caption_info(block) is None:
            continue
        line_bboxes = _caption_line_bboxes(block)
        if line_bboxes:
            bboxes.extend(line_bboxes)
        else:
            block_bbox = block.get("bbox")
            if isinstance(block_bbox, tuple):
                bboxes.append(block_bbox)
    return bboxes


def _looks_like_caption_continuation_line(text: str) -> bool:
    compact = _normalize_space(text)
    if not compact:
        return False
    return compact[:1].islower()


def _cluster_table_rows(words: Sequence[Mapping[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    heights = [
        max(1.0, word["bbox"][3] - word["bbox"][1])
        for word in words
        if isinstance(word.get("bbox"), tuple)
    ]
    tolerance = max(4.0, _median(heights) * 0.72)
    centers: list[float] = []
    for word in sorted(words, key=lambda item: ((item["bbox"][1] + item["bbox"][3]) / 2, item["bbox"][0])):
        bbox = word["bbox"]
        center = (bbox[1] + bbox[3]) / 2
        target_index = next((index for index, row_center in enumerate(centers) if abs(center - row_center) <= tolerance), None)
        item = {"text": str(word["text"]), "bbox": bbox}
        if target_index is None:
            groups.append([item])
            centers.append(center)
            continue
        groups[target_index].append(item)
        centers[target_index] = (centers[target_index] * (len(groups[target_index]) - 1) + center) / len(groups[target_index])
    for group in groups:
        group.sort(key=lambda item: item["bbox"][0])
    groups.sort(key=lambda group: (_merged_bbox([item["bbox"] for item in group])[1], _merged_bbox([item["bbox"] for item in group])[0]))
    return groups


def _table_rows_from_word_groups(
    row_groups: Sequence[Sequence[Mapping[str, Any]]],
    *,
    text_blocks: Sequence[Mapping[str, Any]],
    drawings: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in row_groups:
        cells = _split_table_row_cells(group)
        if not cells:
            continue
        row_bbox = _merged_bbox([cell["bbox"] for cell in cells])
        row_text = " ".join(str(cell["text"]) for cell in cells)
        if _caption_info({"text": row_text, "bbox": row_bbox}) is not None:
            continue
        rows.append({"bbox": row_bbox, "cells": cells, "text": row_text})
    return rows


def _split_table_row_cells(words: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ordered = [word for word in words if isinstance(word.get("bbox"), tuple) and _normalize_space(str(word.get("text") or ""))]
    ordered.sort(key=lambda item: item["bbox"][0])
    if not ordered:
        return []
    heights = [max(1.0, word["bbox"][3] - word["bbox"][1]) for word in ordered]
    widths = [max(1.0, word["bbox"][2] - word["bbox"][0]) for word in ordered]
    gap_threshold = max(10.0, _median(heights) * 1.35, min(38.0, _median(widths) * 0.92))
    cells: list[list[Mapping[str, Any]]] = [[ordered[0]]]
    for previous, current in zip(ordered, ordered[1:]):
        gap = current["bbox"][0] - previous["bbox"][2]
        if gap > gap_threshold:
            cells.append([current])
        else:
            cells[-1].append(current)
    return [
        {
            "text": _normalize_space(" ".join(str(word["text"]) for word in cell_words)),
            "bbox": _merged_bbox([word["bbox"] for word in cell_words]),
        }
        for cell_words in cells
        if _normalize_space(" ".join(str(word["text"]) for word in cell_words))
    ]


def _table_cell_payload(
    cell: Mapping[str, Any],
    *,
    text_blocks: Sequence[Mapping[str, Any]],
    fills: Sequence[Mapping[str, Any]],
    default_align: str,
    header: bool,
) -> dict[str, Any]:
    text = _normalize_space(str(cell.get("text") or ""))
    bbox = cell["bbox"]
    style = _table_text_style(bbox, text_blocks)
    background_style = _table_background_style(bbox, fills, min_overlap=0.42)
    if background_style:
        style = {**style, **background_style}
    html_text = html.escape(text)
    payload: dict[str, Any] = {
        "text": text,
        "html": f"<strong>{html_text}</strong>" if header else html_text,
        "colspan": 1,
        "rowspan": 1,
        "align": _infer_cell_alignment(bbox, default_align=default_align),
        "classes": [],
        "style": style,
    }
    if not style:
        payload["style"] = {}
    return payload


def _infer_table_alignments(rows: Sequence[Mapping[str, Any]], max_columns: int) -> list[str]:
    alignments: list[str] = []
    for column_index in range(max_columns):
        values: list[str] = []
        for row in rows:
            cells = row.get("cells")
            if not isinstance(cells, Sequence) or column_index >= len(cells):
                continue
            cell = cells[column_index]
            if isinstance(cell, Mapping) and isinstance(cell.get("bbox"), tuple):
                values.append(_infer_cell_alignment(cell["bbox"], default_align="center"))
        if values:
            alignments.append(max({"left", "center", "right"}, key=values.count))
        else:
            alignments.append("center")
    return alignments


def _infer_cell_alignment(bbox: tuple[float, float, float, float], *, default_align: str) -> str:
    width = bbox[2] - bbox[0]
    if width <= 0:
        return default_align if default_align in {"left", "center", "right"} else "center"
    # PDF fallback has no TeX column spec. Text-heavy first columns are normally left aligned;
    # compact numeric columns are usually centered in arXiv tables.
    return default_align if default_align in {"left", "center", "right"} else "center"


def _table_text_style(
    bbox: tuple[float, float, float, float],
    text_blocks: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    colors: list[str] = []
    for block in text_blocks:
        lines = block.get("lines")
        if not isinstance(lines, Sequence):
            continue
        for line in lines:
            if not isinstance(line, Mapping):
                continue
            spans = line.get("spans")
            if not isinstance(spans, Sequence):
                continue
            for span in spans:
                if not isinstance(span, Mapping):
                    continue
                span_bbox = span.get("bbox")
                color = span.get("color")
                if not isinstance(span_bbox, tuple) or not isinstance(color, str):
                    continue
                if color.lower() in {"#000000", "#111111", "#1a1a1a"}:
                    continue
                if _intersection_over_min_area(span_bbox, bbox) >= 0.35 or _rect_center_inside(span_bbox, bbox):
                    colors.append(color.lower())
    if not colors:
        return {}
    dominant = max(set(colors), key=colors.count)
    return {"color": dominant} if _is_safe_table_css_color(dominant) else {}


def _table_background_style(
    bbox: tuple[float, float, float, float],
    fills: Sequence[Mapping[str, Any]],
    *,
    min_overlap: float,
) -> dict[str, str]:
    candidates: list[tuple[float, float, str]] = []
    for fill in fills:
        fill_bbox = fill.get("bbox")
        color = fill.get("color")
        if not isinstance(fill_bbox, tuple) or not isinstance(color, str):
            continue
        overlap = _intersection_over_min_area(bbox, fill_bbox)
        if overlap >= min_overlap or _rect_center_inside(bbox, fill_bbox):
            fill_area = max(1.0, (fill_bbox[2] - fill_bbox[0]) * (fill_bbox[3] - fill_bbox[1]))
            candidates.append((overlap, -fill_area, color))
    if not candidates:
        return {}
    color = sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)[0][2].lower()
    return {"backgroundColor": color} if _is_safe_table_css_color(color) else {}


def _table_drawing_primitives(page: Any, crop_bbox: tuple[float, float, float, float]) -> Mapping[str, Any]:
    try:
        drawings = page.get_drawings()
    except Exception:
        return {"fills": [], "horizontalRules": []}
    fills: list[dict[str, Any]] = []
    horizontal_rules: list[dict[str, Any]] = []
    crop_width = crop_bbox[2] - crop_bbox[0]
    for drawing in drawings:
        if not isinstance(drawing, Mapping):
            continue
        fill_color = _pdf_color_to_hex(drawing.get("fill"))
        stroke_color = _pdf_color_to_hex(drawing.get("color"))
        rect = _rect_like(drawing.get("rect"))
        if rect is not None and _intersection_over_min_area(rect, crop_bbox) > 0:
            if fill_color and _is_visible_table_fill(fill_color):
                fills.append({"bbox": rect, "color": fill_color.lower()})
            if stroke_color and _is_visible_table_rule(stroke_color):
                horizontal_rules.extend(_horizontal_rules_from_rect(rect, crop_bbox=crop_bbox, crop_width=crop_width, color=stroke_color))
        items = drawing.get("items")
        if not isinstance(items, Sequence):
            continue
        for item in items:
            if not isinstance(item, Sequence) or not item:
                continue
            op = item[0]
            if op == "l" and len(item) >= 3:
                p0 = _point_xy(item[1])
                p1 = _point_xy(item[2])
                if p0 is not None and p1 is not None:
                    rule = _horizontal_rule_from_points(p0, p1, crop_bbox=crop_bbox, crop_width=crop_width, color=stroke_color)
                    if rule is not None:
                        horizontal_rules.append(rule)
            elif op == "re" and len(item) >= 2:
                item_rect = _rect_like(item[1])
                if item_rect is None or _intersection_over_min_area(item_rect, crop_bbox) <= 0:
                    continue
                if fill_color and _is_visible_table_fill(fill_color):
                    fills.append({"bbox": item_rect, "color": fill_color.lower()})
                if stroke_color and _is_visible_table_rule(stroke_color):
                    horizontal_rules.extend(_horizontal_rules_from_rect(item_rect, crop_bbox=crop_bbox, crop_width=crop_width, color=stroke_color))
    return {
        "fills": _dedupe_drawing_items(fills),
        "horizontalRules": _dedupe_drawing_items(horizontal_rules),
    }


def _horizontal_rules_from_rect(
    rect: tuple[float, float, float, float],
    *,
    crop_bbox: tuple[float, float, float, float],
    crop_width: float,
    color: str | None,
) -> list[dict[str, Any]]:
    return [
        rule
        for rule in (
            _horizontal_rule_from_points((rect[0], rect[1]), (rect[2], rect[1]), crop_bbox=crop_bbox, crop_width=crop_width, color=color),
            _horizontal_rule_from_points((rect[0], rect[3]), (rect[2], rect[3]), crop_bbox=crop_bbox, crop_width=crop_width, color=color),
        )
        if rule is not None
    ]


def _horizontal_rule_from_points(
    p0: tuple[float, float],
    p1: tuple[float, float],
    *,
    crop_bbox: tuple[float, float, float, float],
    crop_width: float,
    color: str | None,
) -> dict[str, Any] | None:
    if abs(p0[1] - p1[1]) > 1.25:
        return None
    x0, x1 = sorted((p0[0], p1[0]))
    y = (p0[1] + p1[1]) / 2
    if y < crop_bbox[1] - 2 or y > crop_bbox[3] + 2:
        return None
    if min(x1, crop_bbox[2]) - max(x0, crop_bbox[0]) < max(32.0, crop_width * 0.18):
        return None
    return {"x0": x0, "x1": x1, "y": y, "color": (color or "#111111").lower()}


def _rules_before_row(
    row_bbox: tuple[float, float, float, float],
    *,
    row_index: int,
    horizontal_rules: Sequence[Mapping[str, Any]],
) -> list[str]:
    row_height = max(1.0, row_bbox[3] - row_bbox[1])
    nearby = [
        rule
        for rule in horizontal_rules
        if isinstance(rule.get("y"), (int, float)) and abs(float(rule["y"]) - row_bbox[1]) <= max(4.0, row_height * 0.35)
    ]
    if row_index == 0:
        return ["toprule"]
    if nearby or row_index == 1:
        return ["midrule"]
    return []


def _rules_after_row(
    row_bbox: tuple[float, float, float, float],
    *,
    horizontal_rules: Sequence[Mapping[str, Any]],
) -> list[str]:
    row_height = max(1.0, row_bbox[3] - row_bbox[1])
    if any(
        isinstance(rule.get("y"), (int, float)) and abs(float(rule["y"]) - row_bbox[3]) <= max(4.0, row_height * 0.35)
        for rule in horizontal_rules
    ):
        return ["bottomrule"]
    return []


def _table_model_html(model: Mapping[str, Any], *, label: str) -> str:
    alignments = [str(item) for item in model.get("alignments", [])]
    rows_html: list[str] = []
    for row in model.get("rows", []):
        if not isinstance(row, Mapping):
            continue
        row_classes = ["paperTableRow"]
        row_classes.extend(f"rule-{rule}" for rule in row.get("rulesBefore", []) if isinstance(rule, str))
        row_classes.extend(f"rule-after-{rule}" for rule in row.get("rulesAfter", []) if isinstance(rule, str))
        row_style = _table_style_attr(row.get("rowStyle") if row.get("rowStyle") else row.get("zebraStyle"))
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
            cell_style = _table_style_attr(cell.get("style"))
            if cell_style:
                attrs.append(cell_style)
            value = str(cell.get("html") or html.escape(str(cell.get("text") or "")))
            cells_html.append(f"<{tag} {' '.join(attrs)}>{value}</{tag}>")
        row_attrs = [f"class=\"{' '.join(html.escape(item) for item in row_classes)}\""]
        if row_style:
            row_attrs.append(row_style)
        rows_html.append(f"<tr {' '.join(row_attrs)}>{''.join(cells_html)}</tr>")
    return f"<table class=\"paperCompiledTable\" aria-label=\"{html.escape(label)}\"><tbody>{''.join(rows_html)}</tbody></table>"


def _table_style_attr(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    declarations: list[str] = []
    color = value.get("color")
    if isinstance(color, str) and _is_safe_table_css_color(color):
        declarations.append(f"color: {color}")
    background = value.get("backgroundColor")
    if isinstance(background, str) and _is_safe_table_css_color(background):
        declarations.append(f"background-color: {background}")
    if not declarations:
        return ""
    return f"style=\"{html.escape('; '.join(declarations))}\""


def _safe_table_style(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    style: dict[str, str] = {}
    color = _text(value.get("color")).lower()
    if color and _is_safe_table_css_color(color):
        style["color"] = color
    background = _text(value.get("backgroundColor") or value.get("background")).lower()
    if background and _is_safe_table_css_color(background):
        style["backgroundColor"] = background
    return style


def _safe_table_align(value: Any) -> str | None:
    text = _text(value).casefold()
    return text if text in {"left", "center", "right"} else None


def _safe_table_classes(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates: Sequence[Any] = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        candidates = value
    else:
        return []
    classes: list[str] = []
    for item in candidates:
        text = _text(item)
        if re.fullmatch(r"paperTableColor(?:Red|Blue|Gray|Neutral)", text):
            classes.append(text)
    return classes


def _safe_table_rules(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates: Sequence[Any] = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        candidates = value
    else:
        return []
    rules: list[str] = []
    for item in candidates:
        text = _text(item)
        if text in {"toprule", "midrule", "bottomrule", "cmidrule"}:
            rules.append(text)
    return rules


def _positive_span(value: Any) -> int:
    if isinstance(value, bool):
        return 1
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return max(1, min(40, int(value)))
    if isinstance(value, str):
        try:
            return max(1, min(40, int(value.strip())))
        except ValueError:
            return 1
    return 1


def _plain_text_from_html(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return _normalize_space(re.sub(r"<[^>]+>", " ", html.unescape(value)))


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


def _looks_like_table_heading_row(text: str) -> bool:
    compact = _normalize_space(text)
    if not compact or len(compact) > 90:
        return False
    if re.search(r"[.!?]\s*$", compact):
        return False
    return len(_WORD_PATTERN.findall(compact)) <= 12


def _is_structural_table_noise(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return True
    if normalized in {"[", "]", "{", "}", "|"}:
        return True
    return len(normalized) <= 1 and not normalized.isalnum()


def _dedupe_drawing_items(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        bbox = item.get("bbox")
        y = item.get("y")
        color = str(item.get("color") or "")
        key = (_bbox_key(bbox) if isinstance(bbox, tuple) else str(round(float(y), 2)) if isinstance(y, (int, float)) else "", color)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(item))
    return deduped


def _dedupe_bboxes(items: Sequence[tuple[float, float, float, float]]) -> list[tuple[float, float, float, float]]:
    seen: set[str] = set()
    deduped: list[tuple[float, float, float, float]] = []
    for item in items:
        if item[2] - item[0] < 8 or item[3] - item[1] < 8:
            continue
        key = _bbox_key(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _rect_like(value: Any) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    for attrs in (("x0", "y0", "x1", "y1"), ("left", "top", "right", "bottom")):
        coords = [getattr(value, attr, None) for attr in attrs]
        if all(isinstance(coord, (int, float)) and math.isfinite(float(coord)) for coord in coords):
            return (float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3]))
    return _bbox_tuple(value)


def _point_xy(value: Any) -> tuple[float, float] | None:
    x = getattr(value, "x", None)
    y = getattr(value, "y", None)
    if isinstance(x, (int, float)) and isinstance(y, (int, float)) and math.isfinite(float(x)) and math.isfinite(float(y)):
        return (float(x), float(y))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 2:
        x_value, y_value = value[0], value[1]
        if isinstance(x_value, (int, float)) and isinstance(y_value, (int, float)):
            return (float(x_value), float(y_value))
    return None


def _pdf_color_to_hex(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return f"#{(value >> 16) & 255:02x}{(value >> 8) & 255:02x}{value & 255:02x}"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 3:
        channels: list[int] = []
        for item in value[:3]:
            if not isinstance(item, (int, float)) or not math.isfinite(float(item)):
                return None
            number = float(item)
            channels.append(max(0, min(255, int(round(number * 255 if number <= 1 else number)))))
        return f"#{channels[0]:02x}{channels[1]:02x}{channels[2]:02x}"
    return None


def _is_safe_table_css_color(value: str) -> bool:
    return re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None


def _is_visible_table_fill(value: str) -> bool:
    if not _is_safe_table_css_color(value):
        return False
    r, g, b = int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)
    return (r + g + b) / 3 < 245


def _is_visible_table_rule(value: str) -> bool:
    if not _is_safe_table_css_color(value):
        return False
    r, g, b = int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)
    return (r + g + b) / 3 < 245


def _median(values: Sequence[float]) -> float:
    if not values:
        return 1.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _text_block_overlaps_visual_asset(
    bbox: tuple[float, float, float, float],
    visual_assets: Sequence[tuple[PaperVisualAsset, float, float]],
) -> bool:
    for asset, _, _ in visual_assets:
        if asset.source is None:
            continue
        if _intersection_over_min_area(bbox, asset.source.bbox) >= 0.55:
            return True
        if _rect_center_inside(bbox, asset.source.bbox):
            return True
    return False


def _text_block_near_visual_asset(
    bbox: tuple[float, float, float, float],
    visual_assets: Sequence[tuple[PaperVisualAsset, float, float]],
    *,
    page_width: float,
    page_height: float,
    kind: str | None = None,
    margin_scale: float = 0.025,
) -> bool:
    margin_x = max(14.0, page_width * margin_scale)
    margin_y = max(14.0, page_height * margin_scale)
    for asset, _, _ in visual_assets:
        if asset.source is None:
            continue
        if kind is not None and asset.kind != kind:
            continue
        if _rect_center_inside(bbox, _expand_bbox_xy(asset.source.bbox, page_width=page_width, page_height=page_height, margin_x=margin_x, margin_y=margin_y)):
            return True
    return False


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


def _equation_for_model_region(region: Any, text_blocks: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    candidates: list[tuple[float, Mapping[str, Any]]] = []
    for block in text_blocks:
        equation = _equation_info(block)
        if equation is None:
            continue
        bbox = equation.get("bbox")
        if not isinstance(bbox, tuple):
            continue
        overlap = _intersection_over_min_area(region.bbox, bbox)
        if overlap <= 0 and not _rect_center_inside(bbox, region.bbox):
            continue
        candidates.append((1 - overlap, equation))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0])[0][1]


def _equation_from_model_region(region: Any) -> Mapping[str, Any] | None:
    region_metadata = dict(getattr(region, "metadata", {}) or {})
    text = _normalize_space(
        str(
            region_metadata.get("equationText")
            or region_metadata.get("latex")
            or region_metadata.get("formula")
            or getattr(region, "caption", None)
            or ""
        )
    )
    if not text:
        return None
    if not _looks_like_standalone_equation_text(text):
        return None
    if len(text) > 500:
        text = text[:500].rstrip()
    label_match = _EQUATION_LABEL_PATTERN.search(text)
    label = _normalize_space(str(getattr(region, "label", None) or ""))
    if not label:
        label = f"Equation {label_match.group('label')}" if label_match else "Equation"
    metadata = {
        "layoutProvider": "model",
        "layoutConfidence": getattr(region, "confidence", None),
        "modelGeneratedEquationText": True,
        **region_metadata,
    }
    return {
        "label": label,
        "text": text,
        "bbox": region.bbox,
        "metadata": metadata,
    }


def _equation_label(equation: Mapping[str, Any] | None) -> str | None:
    if equation is None:
        return None
    return _text(equation.get("label")) or None


def _equation_text(equation: Mapping[str, Any] | None) -> str | None:
    if equation is None:
        return None
    return _text(equation.get("text")) or None


def _visual_asset_with_label_exists(
    label: str | None,
    visual_assets: Sequence[tuple[PaperVisualAsset, float, float]],
) -> bool:
    normalized = _normalize_label(label)
    return bool(normalized) and any(_normalize_label(asset.label) == normalized for asset, _, _ in visual_assets)


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


def _merged_visual_bbox(
    bboxes: Sequence[tuple[float, float, float, float]],
    *,
    text_blocks: Sequence[Mapping[str, Any]] = (),
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    merged = _merged_bbox(bboxes)
    visual_text_bboxes = [
        bbox
        for block in text_blocks
        if (bbox := block.get("bbox")) is not None
        and isinstance(bbox, tuple)
        and _is_text_inside_or_near_image_group(block, merged, page_width=page_width, page_height=page_height)
    ]
    if visual_text_bboxes:
        merged = _merged_bbox([merged, *visual_text_bboxes])
    return _expand_bbox(_clamp_visual_bbox(merged, page_width=page_width, page_height=page_height), page_width=page_width, page_height=page_height, margin=8)


def _visual_bbox_for_caption_group(
    group: Mapping[str, Any],
    *,
    text_blocks: Sequence[Mapping[str, Any]] = (),
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    bboxes = group.get("bboxes")
    caption = group.get("caption")
    if not isinstance(bboxes, Sequence) or not bboxes:
        if isinstance(caption, Mapping):
            return _caption_visual_bbox(caption, page_width=page_width, page_height=page_height)
        return (24.0, 24.0, page_width - 24.0, page_height - 24.0)
    return _merged_visual_bbox(bboxes, text_blocks=text_blocks, page_width=page_width, page_height=page_height)


def _visual_text_blocks_for_crop(
    crop_bbox: tuple[float, float, float, float],
    text_blocks: Sequence[Mapping[str, Any]],
    *,
    page_width: float,
    page_height: float,
) -> list[dict[str, Any]]:
    return [
        dict(block)
        for block in text_blocks
        if _is_text_inside_or_near_image_group(block, crop_bbox, page_width=page_width, page_height=page_height)
    ]


def _is_text_inside_or_near_image_group(
    block: Mapping[str, Any],
    image_bbox: tuple[float, float, float, float],
    *,
    page_width: float,
    page_height: float,
) -> bool:
    text = _normalize_space(str(block.get("text") or ""))
    bbox = block.get("bbox")
    if not text or not isinstance(bbox, tuple):
        return False
    if _caption_info(block) is not None:
        return False
    if _SECTION_PATTERN.match(text) or _NUMBERED_HEADING_PATTERN.match(text):
        return False
    guard = _expand_bbox_xy(
        image_bbox,
        page_width=page_width,
        page_height=page_height,
        margin_x=max(10.0, page_width * 0.025),
        margin_y=max(12.0, page_height * 0.035),
    )
    if not _rect_center_inside(bbox, guard):
        return False
    if _intersection_over_min_area(bbox, image_bbox) >= 0.08:
        return True
    if _looks_like_short_visual_annotation(text):
        return True
    return _looks_like_table_row(text)


def _text_block_matches_any(block: Mapping[str, Any], others: Sequence[Mapping[str, Any]]) -> bool:
    text = _normalize_space(str(block.get("text") or ""))
    bbox = block.get("bbox")
    if not text or not isinstance(bbox, tuple):
        return False
    for other in others:
        other_bbox = other.get("bbox")
        if not isinstance(other_bbox, tuple):
            continue
        if text == _normalize_space(str(other.get("text") or "")) and _intersection_over_min_area(bbox, other_bbox) >= 0.8:
            return True
    return False


def _section_id_for_y(y: float, section_ranges: Sequence[tuple[float, str]]) -> str:
    current = section_ranges[0][1] if section_ranges else ""
    for section_y, section_id in sorted(section_ranges, key=lambda item: item[0]):
        if section_y <= y + 0.1:
            current = section_id
            continue
        break
    return current


def _clamp_visual_bbox(
    bbox: tuple[float, float, float, float],
    *,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    return (
        max(20.0, min(page_width - 20.0, bbox[0])),
        max(20.0, min(page_height - 20.0, bbox[1])),
        max(20.0, min(page_width - 20.0, bbox[2])),
        max(20.0, min(page_height - 20.0, bbox[3])),
    )


def _merged_bbox(bboxes: Sequence[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    )


def _union_bbox(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    *,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    return (
        max(0.0, min(left[0], right[0])),
        max(0.0, min(left[1], right[1])),
        min(page_width, max(left[2], right[2])),
        min(page_height, max(left[3], right[3])),
    )


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
            **({"sectionNumber": str(block.metadata.get("sectionNumber"))} if block.metadata.get("sectionNumber") else {}),
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


def _expand_bbox_xy(
    bbox: tuple[float, float, float, float],
    *,
    page_width: float,
    page_height: float,
    margin_x: float,
    margin_y: float,
) -> tuple[float, float, float, float]:
    return (
        max(0.0, bbox[0] - margin_x),
        max(0.0, bbox[1] - margin_y),
        min(page_width, bbox[2] + margin_x),
        min(page_height, bbox[3] + margin_y),
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


def _rect_center_inside(
    inner: tuple[float, float, float, float],
    outer: tuple[float, float, float, float],
) -> bool:
    center_x = (inner[0] + inner[2]) / 2
    center_y = (inner[1] + inner[3]) / 2
    return outer[0] <= center_x <= outer[2] and outer[1] <= center_y <= outer[3]


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


def _normalize_pdf_text_lines(lines: Sequence[str]) -> str:
    normalized_lines = [_normalize_space(line) for line in lines if _normalize_space(line)]
    if not normalized_lines:
        return ""
    text = normalized_lines[0]
    for line in normalized_lines[1:]:
        match = _HYPHENATED_LINE_END_PATTERN.search(text)
        if match and line[:1].islower():
            prefix = match.group("prefix")
            separator = "-" if prefix.casefold() in _COMPOUND_LINEBREAK_PREFIXES else ""
            text = f"{text[:match.start()]}{prefix}{separator}{line}"
            continue
        text = f"{text} {line}"
    return _normalize_space(text)


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def _bbox_key(bbox: tuple[float, float, float, float]) -> str:
    return ",".join(str(round(value, 2)) for value in bbox)


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
