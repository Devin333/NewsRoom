from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping
from collections import Counter
from pathlib import Path
from typing import Any

from business.boards.paper_radar.visual_compiler.models import (
    ASSET_BACKED_BLOCK_TYPES,
    VISUAL_ASSET_TYPES,
    VISUAL_BLOCK_TYPES,
    PaperAssetManifest,
    PaperDocument,
)


class PaperAssetGate:
    def __init__(
        self,
        *,
        max_blank_ratio: float = 0.9985,
        min_visual_width: int = 16,
        min_visual_height: int = 16,
    ) -> None:
        self.max_blank_ratio = max_blank_ratio
        self.min_visual_width = min_visual_width
        self.min_visual_height = min_visual_height

    def validate(
        self,
        *,
        document: PaperDocument,
        manifest: PaperAssetManifest,
        paper_dir: Path,
    ) -> Mapping[str, Any]:
        errors: list[Mapping[str, Any]] = []
        warnings: list[Mapping[str, Any]] = []

        if document.paperId != manifest.paperId:
            errors.append(_issue("paper_id_mismatch", "document and manifest paper ids differ"))
        if document.sourceHash != manifest.sourceHash:
            errors.append(_issue("source_hash_mismatch", "document and manifest source hashes differ"))

        assets_by_id = {asset.assetId: asset for asset in manifest.assets}
        if len(assets_by_id) != len(manifest.assets):
            errors.append(_issue("duplicate_asset_id", "manifest contains duplicate asset ids"))

        for asset in manifest.assets:
            file_path = (paper_dir / asset.fileName).resolve()
            root = paper_dir.resolve()
            if root not in file_path.parents and file_path != root:
                errors.append(_issue("asset_path_escape", "asset path escapes paper artifact directory", assetId=asset.assetId))
                continue
            if not file_path.exists() or not file_path.is_file():
                errors.append(_issue("asset_file_missing", "asset file is missing", assetId=asset.assetId, fileName=asset.fileName))
                continue
            actual_checksum = hashlib.sha256(file_path.read_bytes()).hexdigest()
            if actual_checksum != asset.checksum:
                errors.append(_issue("asset_checksum_mismatch", "asset checksum does not match file bytes", assetId=asset.assetId))
            actual_size = _asset_size(file_path, asset.mimeType, asset.width, asset.height)
            if actual_size is None:
                errors.append(_issue("asset_file_invalid", "asset is not a readable image or structured table file", assetId=asset.assetId))
                continue
            width, height = actual_size
            if width != asset.width or height != asset.height:
                errors.append(
                    _issue(
                        "asset_dimensions_mismatch",
                        "asset dimensions do not match manifest",
                        assetId=asset.assetId,
                        expected={"width": asset.width, "height": asset.height},
                        actual={"width": width, "height": height},
                    )
                )
            if asset.kind in VISUAL_ASSET_TYPES:
                if width < self.min_visual_width or height < self.min_visual_height:
                    errors.append(_issue("asset_dimensions_too_small", "visual asset is too small", assetId=asset.assetId))
                if not asset.label:
                    errors.append(_issue("asset_label_missing", "visual asset label is missing", assetId=asset.assetId))
                if not asset.caption:
                    errors.append(_issue("asset_caption_missing", "visual asset caption is missing", assetId=asset.assetId))
                if asset.source is None:
                    errors.append(_issue("asset_source_missing", "visual asset source bbox is missing", assetId=asset.assetId))
                if asset.kind == "table" and asset.mimeType.startswith("text/html"):
                    if not isinstance(asset.metadata.get("tableModel"), Mapping) or not asset.metadata.get("tableHtml"):
                        errors.append(_issue("table_asset_model_missing", "structured table asset is missing table model/html metadata", assetId=asset.assetId))
                else:
                    blank_ratio = asset.blankRatio if asset.blankRatio is not None else _blank_ratio(file_path)
                    if blank_ratio >= self.max_blank_ratio:
                        errors.append(
                            _issue(
                                "asset_blank",
                                "visual asset is effectively blank",
                                assetId=asset.assetId,
                                blankRatio=round(blank_ratio, 6),
                            )
                        )
            elif asset.kind == "page" and asset.source is None:
                warnings.append(_issue("page_source_missing", "page asset source bbox is missing", assetId=asset.assetId))

        for block in document.blocks:
            if block.source is None:
                warnings.append(_issue("block_source_missing", "block source bbox is missing", blockId=block.id))
            if block.type in ASSET_BACKED_BLOCK_TYPES:
                if not block.assetId:
                    errors.append(_issue("visual_block_asset_missing", "visual block does not reference an asset", blockId=block.id))
                    continue
                asset = assets_by_id.get(block.assetId)
                if asset is None:
                    errors.append(
                        _issue(
                            "visual_block_asset_not_found",
                            "visual block references an asset missing from manifest",
                            blockId=block.id,
                            assetId=block.assetId,
                        )
                    )
                    continue
                if asset.kind != block.type:
                    errors.append(
                        _issue(
                            "visual_block_asset_kind_mismatch",
                            "visual block type does not match asset kind",
                            blockId=block.id,
                            assetId=asset.assetId,
                            blockType=block.type,
                            assetKind=asset.kind,
                        )
                    )
                if not block.label:
                    errors.append(_issue("visual_block_label_missing", "visual block label is missing", blockId=block.id))
                if not block.caption:
                    errors.append(_issue("visual_block_caption_missing", "visual block caption is missing", blockId=block.id))
            elif block.type == "equation":
                if block.assetId:
                    errors.append(_issue("equation_block_asset_unexpected", "equation block must be generated as text, not an image asset", blockId=block.id, assetId=block.assetId))
                if not block.text and not block.caption:
                    errors.append(_issue("equation_text_missing", "equation block text is missing", blockId=block.id))
                if block.source is None:
                    errors.append(_issue("equation_source_missing", "equation block source bbox is missing", blockId=block.id))

        visual_assets = [asset for asset in manifest.assets if asset.kind in VISUAL_ASSET_TYPES]
        visual_blocks = [block for block in document.blocks if block.type in VISUAL_BLOCK_TYPES]
        asset_backed_blocks = [block for block in document.blocks if block.type in ASSET_BACKED_BLOCK_TYPES]
        if visual_assets and not asset_backed_blocks:
            errors.append(_issue("visual_assets_unbound", "manifest has visual assets but document has no visual blocks"))
        label_counts = Counter(
            block.label
            for block in asset_backed_blocks
            if block.label
        )
        repeated_labels = {label: count for label, count in label_counts.items() if count > 3}
        if repeated_labels:
            errors.append(
                _issue(
                    "visual_block_label_repeated",
                    "too many visual blocks share the same label; likely over-segmented PDF image crops",
                    labels=repeated_labels,
                )
            )
        unique_asset_labels = {asset.label for asset in visual_assets if asset.label}
        if len(visual_assets) > 24 and unique_asset_labels and len(visual_assets) > len(unique_asset_labels) * 3:
            errors.append(
                _issue(
                    "visual_assets_oversegmented",
                    "visual assets appear over-segmented relative to figure/table labels",
                    visualAssetCount=len(visual_assets),
                    uniqueLabelCount=len(unique_asset_labels),
                )
            )

        return {
            "passed": not errors,
            "errors": errors,
            "warnings": warnings,
            "assetCount": len(manifest.assets),
            "visualAssetCount": len(visual_assets),
            "blockCount": len(document.blocks),
            "visualBlockCount": len(visual_blocks),
            "assetBackedBlockCount": len(asset_backed_blocks),
        }


def _issue(code: str, message: str, **details: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    payload.update({key: value for key, value in details.items() if value not in (None, "", [], {})})
    return payload


def _png_size(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError:
        return None
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", header[16:24])


def _asset_size(path: Path, mime_type: str, width: int, height: int) -> tuple[int, int] | None:
    if mime_type.startswith("text/html"):
        return (width, height) if width > 0 and height > 0 and path.read_text(encoding="utf-8", errors="ignore").strip() else None
    return _png_size(path)


def _blank_ratio(path: Path) -> float:
    try:
        import fitz  # type: ignore[import-not-found]

        pixmap = fitz.Pixmap(str(path))
    except Exception:
        return 1.0
    samples = bytes(pixmap.samples)
    channels = max(1, int(getattr(pixmap, "n", 3) or 3))
    if not samples or channels < 3:
        return 1.0
    pixel_count = len(samples) // channels
    if pixel_count <= 0:
        return 1.0
    step = max(1, pixel_count // 30_000)
    blank = 0
    sampled = 0
    for pixel_index in range(0, pixel_count, step):
        offset = pixel_index * channels
        r, g, b = samples[offset], samples[offset + 1], samples[offset + 2]
        if r >= 248 and g >= 248 and b >= 248:
            blank += 1
        sampled += 1
    return blank / sampled if sampled else 1.0
