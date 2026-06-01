from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime, timezone as _tz
from pathlib import Path
from typing import Any

from business.boards.paper_radar.visual_compiler.models import (
    ASSET_BACKED_BLOCK_TYPES,
    VISUAL_ASSET_TYPES,
    PaperAssetManifest,
    PaperCompileInfo,
    PaperDocument,
    PaperSourceComparisonReport,
    PaperSourceRegion,
)


UTC = _tz.utc


class PaperSourceComparer:
    comparer_name = "paper-source-comparer-v1"

    def compare(
        self,
        *,
        document: PaperDocument,
        manifest: PaperAssetManifest,
        compile_info: PaperCompileInfo,
        paper_dir: Path,
        paper: Mapping[str, Any] | None = None,
        gate_report: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> PaperSourceComparisonReport:
        paper_payload = dict(paper or {})
        errors: list[Mapping[str, Any]] = []
        warnings: list[Mapping[str, Any]] = []

        paper_dir = paper_dir.resolve()
        assets_by_id = {asset.assetId: asset for asset in manifest.assets}
        page_assets = [asset for asset in manifest.assets if asset.kind == "page"]
        visual_assets = [asset for asset in manifest.assets if asset.kind in VISUAL_ASSET_TYPES]
        visual_blocks = [block for block in document.blocks if block.type in ASSET_BACKED_BLOCK_TYPES]
        text_blocks = [block for block in document.blocks if block.type in {"heading", "paragraph", "equation"}]
        readable_text_blocks = [block for block in text_blocks if block.text.strip()]
        visual_block_asset_ids = {block.assetId for block in visual_blocks if block.assetId}

        source_pdf_path = self._source_pdf_path(manifest=manifest, paper_dir=paper_dir, errors=errors)
        source_pdf_metrics = _source_pdf_metrics(source_pdf_path, warnings=warnings)

        if document.paperId != manifest.paperId or document.paperId != compile_info.paperId:
            errors.append(
                _issue(
                    "error",
                    "paper_id_mismatch",
                    "compiled document, manifest, and compile info must describe the same paper",
                    documentPaperId=document.paperId,
                    manifestPaperId=manifest.paperId,
                    compileInfoPaperId=compile_info.paperId,
                )
            )
        if document.sourceHash != manifest.sourceHash or document.sourceHash != compile_info.sourceHash:
            errors.append(
                _issue(
                    "error",
                    "source_hash_mismatch",
                    "compiled document, manifest, and compile info must share one source hash",
                    documentSourceHash=document.sourceHash,
                    manifestSourceHash=manifest.sourceHash,
                    compileInfoSourceHash=compile_info.sourceHash,
                )
            )
        if not _text(document.title):
            errors.append(_issue("error", "paper_title_missing", "compiled reader document is missing the paper title"))
        if not _text(compile_info.sourcePdfUrl):
            errors.append(_issue("error", "source_pdf_url_missing", "compile info is missing the native source PDF URL"))
        if not _text(paper_payload.get("id")):
            errors.append(_issue("error", "paper_metadata_id_missing", "source paper metadata is missing a stable id"))
        if not (_text(paper_payload.get("title")) or _text(paper_payload.get("titleZh"))):
            warnings.append(_issue("warning", "paper_metadata_title_missing", "source paper metadata has no title field"))

        if not document.blocks:
            errors.append(_issue("error", "compiled_body_empty", "compiled reader document has no blocks"))
        elif not readable_text_blocks:
            errors.append(_issue("error", "readable_text_missing", "compiled reader document has no readable text blocks"))
        if not page_assets:
            errors.append(_issue("error", "page_assets_missing", "manifest is missing native PDF page assets"))

        for block in document.blocks:
            problem = _source_region_problem(block.source)
            if problem:
                errors.append(
                    _issue(
                        "error",
                        "block_source_invalid",
                        "compiled block must retain a valid native source region",
                        blockId=block.id,
                        blockType=block.type,
                        reason=problem,
                    )
                )
            if block.type in ASSET_BACKED_BLOCK_TYPES:
                if not block.assetId:
                    errors.append(
                        _issue(
                            "error",
                            "visual_block_asset_missing",
                            "figure/table blocks shown to readers must reference a visual asset",
                            blockId=block.id,
                            blockType=block.type,
                        )
                    )
                    continue
                asset = assets_by_id.get(block.assetId)
                if asset is None:
                    errors.append(
                        _issue(
                            "error",
                            "visual_block_asset_not_found",
                            "figure/table block references a missing visual asset",
                            blockId=block.id,
                            assetId=block.assetId,
                        )
                    )
                    continue
                if asset.kind != block.type:
                    errors.append(
                        _issue(
                            "error",
                            "visual_block_asset_kind_mismatch",
                            "figure/table block type must match its visual asset kind",
                            blockId=block.id,
                            assetId=asset.assetId,
                            blockType=block.type,
                            assetKind=asset.kind,
                        )
                    )

        for asset in manifest.assets:
            if asset.kind in {"page", *VISUAL_ASSET_TYPES}:
                problem = _source_region_problem(asset.source)
                if problem:
                    errors.append(
                        _issue(
                            "error",
                            "asset_source_invalid",
                            "manifest assets must retain valid native source regions",
                            assetId=asset.assetId,
                            assetKind=asset.kind,
                            reason=problem,
                        )
                    )
            if asset.kind in VISUAL_ASSET_TYPES and asset.assetId not in visual_block_asset_ids:
                errors.append(
                    _issue(
                        "error",
                        "visual_asset_unreferenced",
                        "figure/table assets must be represented by reader blocks",
                        assetId=asset.assetId,
                        assetKind=asset.kind,
                    )
                )

        if source_pdf_metrics.get("pageCount") and page_assets:
            page_count = int(source_pdf_metrics["pageCount"])
            page_asset_numbers = {asset.pageNumber for asset in page_assets}
            if page_count > len(page_asset_numbers):
                warnings.append(
                    _issue(
                        "warning",
                        "source_page_assets_incomplete",
                        "native PDF has pages without page preview assets",
                        sourcePageCount=page_count,
                        pageAssetCount=len(page_asset_numbers),
                    )
                )

        provider = compile_info.provider
        if "fallback" in provider:
            warnings.append(
                _issue(
                    "warning",
                    "source_first_fallback_used",
                    "compiler fell back from source package parsing to PDF extraction",
                    provider=provider,
                )
            )
        if document.auxiliary.get("sourceMapping") == "synthetic":
            warnings.append(
                _issue(
                    "warning",
                    "synthetic_source_mapping",
                    "compiled blocks use synthetic TeX source regions; native PDF previews remain the visual reference",
                )
            )

        metrics: dict[str, Any] = {
            "blockCount": len(document.blocks),
            "textBlockCount": len(text_blocks),
            "readableTextBlockCount": len(readable_text_blocks),
            "visualBlockCount": len(visual_blocks),
            "assetCount": len(manifest.assets),
            "visualAssetCount": len(visual_assets),
            "pageAssetCount": len(page_assets),
            "sourceMappedBlockCount": sum(1 for block in document.blocks if block.source is not None),
            "sourceMappedAssetCount": sum(1 for asset in manifest.assets if asset.source is not None),
            "textCharacterCount": sum(len(block.text.strip()) for block in readable_text_blocks),
            "provider": provider,
            "manifestProvider": manifest.provider,
            "sourcePdfPresent": source_pdf_path is not None and source_pdf_path.exists(),
            **source_pdf_metrics,
        }
        if gate_report is not None:
            metrics["assetGatePassed"] = bool(gate_report.get("passed"))
            metrics["assetGateErrorCount"] = len(_sequence(gate_report.get("errors")))
            metrics["assetGateWarningCount"] = len(_sequence(gate_report.get("warnings")))

        passed = not errors
        summary = (
            f"Source comparison passed for {document.paperId}: {len(document.blocks)} blocks and "
            f"{len(visual_assets)} visual assets are traceable to the native source."
            if passed
            else f"Source comparison failed for {document.paperId}: {len(errors)} hard issue(s) must be fixed before readers see the paper."
        )
        created = _iso(created_at or datetime.now(UTC))
        return PaperSourceComparisonReport(
            paperId=document.paperId,
            passed=passed,
            comparer=self.comparer_name,
            createdAt=created,
            summary=summary,
            metrics=metrics,
            errors=tuple(errors),
            warnings=tuple(warnings),
            lessons=tuple(_lessons(document.paperId, passed=passed, errors=errors, warnings=warnings, metrics=metrics)),
            raw={
                "sourcePdfFileName": manifest.sourcePdfFileName,
                "sourcePdfUrl": compile_info.sourcePdfUrl,
            },
        )

    def _source_pdf_path(
        self,
        *,
        manifest: PaperAssetManifest,
        paper_dir: Path,
        errors: list[Mapping[str, Any]],
    ) -> Path | None:
        file_name = _text(manifest.sourcePdfFileName)
        if not file_name:
            errors.append(_issue("error", "source_pdf_reference_missing", "manifest is missing the native source PDF file reference"))
            return None
        path = (paper_dir / file_name).resolve()
        if paper_dir not in path.parents and path != paper_dir:
            errors.append(_issue("error", "source_pdf_path_escape", "native source PDF path escapes the paper artifact directory", fileName=file_name))
            return None
        if not path.exists() or not path.is_file():
            errors.append(_issue("error", "source_pdf_file_missing", "native source PDF file is missing", fileName=file_name))
            return path
        return path


def _source_pdf_metrics(path: Path | None, *, warnings: list[Mapping[str, Any]]) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    metrics: dict[str, Any] = {"sourcePdfBytes": path.stat().st_size}
    try:
        import fitz  # type: ignore[import-not-found]

        pdf = fitz.open(path)
    except Exception as exc:
        warnings.append(
            _issue(
                "warning",
                "source_pdf_page_count_unavailable",
                "native source PDF page count could not be inspected",
                reason=str(exc),
            )
        )
        return metrics
    try:
        metrics["pageCount"] = len(pdf)
    finally:
        pdf.close()
    return metrics


def _source_region_problem(region: PaperSourceRegion | None) -> str | None:
    if region is None:
        return "missing"
    if region.pageNumber <= 0:
        return "invalid_page"
    x0, y0, x1, y1 = region.bbox
    values = (x0, y0, x1, y1)
    if not all(math.isfinite(value) for value in values):
        return "non_finite_bbox"
    if x1 <= x0 or y1 <= y0:
        return "non_positive_bbox"
    if x0 < 0 or y0 < 0:
        return "negative_bbox"
    if region.pageWidth is not None and x1 > region.pageWidth + 1:
        return "bbox_exceeds_page_width"
    if region.pageHeight is not None and y1 > region.pageHeight + 1:
        return "bbox_exceeds_page_height"
    return None


def _lessons(
    paper_id: str,
    *,
    passed: bool,
    errors: list[Mapping[str, Any]],
    warnings: list[Mapping[str, Any]],
    metrics: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    lessons: list[Mapping[str, Any]] = []
    if passed:
        lessons.append(
            _lesson(
                paper_id,
                severity="info",
                category="source_comparison_passed",
                code="source_comparison_passed",
                message=(
                    "Reader document can be published when body blocks, visual assets, source PDF, "
                    "and source regions all remain traceable."
                ),
                metrics=metrics,
            )
        )
    for issue in errors:
        code = _text(issue.get("code")) or "source_comparison_error"
        lessons.append(
            _lesson(
                paper_id,
                severity="error",
                category="publication_blocker",
                code=code,
                message=f"Block Reader publication until source-comparison issue `{code}` is fixed.",
                issue=issue,
            )
        )
    for issue in warnings:
        code = _text(issue.get("code")) or "source_comparison_warning"
        lessons.append(
            _lesson(
                paper_id,
                severity="warning",
                category="source_comparison_watch",
                code=code,
                message=f"Track non-blocking source-comparison warning `{code}` for future layout improvements.",
                issue=issue,
            )
        )
    return lessons


def _lesson(paper_id: str, *, severity: str, category: str, code: str, message: str, **details: Any) -> Mapping[str, Any]:
    payload = {
        "paperId": paper_id,
        "severity": severity,
        "category": category,
        "code": code,
        "message": message,
        **{key: value for key, value in details.items() if value not in (None, "", [], {})},
    }
    return {
        "lessonId": _stable_id("paper-source-lesson", paper_id, code, message, json.dumps(payload, sort_keys=True, default=str)),
        **payload,
    }


def _issue(severity: str, code: str, message: str, **details: Any) -> Mapping[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        **{key: value for key, value in details.items() if value not in (None, "", [], {})},
    }


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{parts[0]}-{digest}"


def _sequence(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
