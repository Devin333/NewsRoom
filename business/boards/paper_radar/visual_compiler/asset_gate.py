from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from business.boards.paper_radar.visual_compiler.models import (
    ASSET_BACKED_BLOCK_TYPES,
    VISUAL_ASSET_TYPES,
    VISUAL_BLOCK_TYPES,
    PaperAssetManifest,
    PaperDocument,
)
from business.boards.paper_radar.visual_compiler.artifact_reviewer import PaperReaderArtifactReviewSubAgent


class PaperAssetGate:
    def __init__(
        self,
        *,
        max_blank_ratio: float = 0.9985,
        min_visual_width: int = 16,
        min_visual_height: int = 16,
        artifact_reviewer: PaperReaderArtifactReviewSubAgent | None = None,
    ) -> None:
        self.max_blank_ratio = max_blank_ratio
        self.min_visual_width = min_visual_width
        self.min_visual_height = min_visual_height
        self.artifact_reviewer = artifact_reviewer or PaperReaderArtifactReviewSubAgent(
            max_blank_ratio=max_blank_ratio,
            min_visual_width=min_visual_width,
            min_visual_height=min_visual_height,
        )

    @property
    def gate_name(self) -> str:
        return "paper-reader-quality-gate-v2"

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
            errors.append(_issue("paper_id_mismatch", "document and manifest paper ids differ", gate="image"))
        if document.sourceHash != manifest.sourceHash:
            errors.append(_issue("source_hash_mismatch", "document and manifest source hashes differ", gate="image"))

        assets_by_id = {asset.assetId: asset for asset in manifest.assets}
        if len(assets_by_id) != len(manifest.assets):
            errors.append(_issue("duplicate_asset_id", "manifest contains duplicate asset ids", gate="image"))

        for asset in manifest.assets:
            file_path = (paper_dir / asset.fileName).resolve()
            root = paper_dir.resolve()
            if root not in file_path.parents and file_path != root:
                errors.append(_issue("asset_path_escape", "asset path escapes paper artifact directory", gate="image", assetId=asset.assetId))
                continue
            if not file_path.exists() or not file_path.is_file():
                errors.append(_issue("asset_file_missing", "asset file is missing", gate="image", assetId=asset.assetId, fileName=asset.fileName))
                continue
            actual_checksum = hashlib.sha256(file_path.read_bytes()).hexdigest()
            if actual_checksum != asset.checksum:
                errors.append(_issue("asset_checksum_mismatch", "asset checksum does not match file bytes", gate="image", assetId=asset.assetId))
            actual_size = _asset_size(file_path, asset.mimeType, asset.width, asset.height)
            if actual_size is None:
                errors.append(_issue("asset_file_invalid", "asset is not a readable image or structured table file", gate="image", assetId=asset.assetId))
                continue
            width, height = actual_size
            if width != asset.width or height != asset.height:
                errors.append(
                    _issue(
                        "asset_dimensions_mismatch",
                        "asset dimensions do not match manifest",
                        gate="image",
                        assetId=asset.assetId,
                        expected={"width": asset.width, "height": asset.height},
                        actual={"width": width, "height": height},
                    )
                )

        try:
            review_report = self.artifact_reviewer.review(
                document=document.to_dict(),
                manifest=manifest.to_dict(),
                paper_dir=paper_dir,
                memory_path=paper_dir.parent / "paper-reader-artifact-review-memory.json",
            )
        except Exception as exc:
            review_report = None
            errors.append(
                _issue(
                    "artifact_review_failed",
                    "paper artifact review failed",
                    gate="image",
                    error=str(exc),
                )
            )

        if review_report is not None:
            errors.extend(dict(item) for item in _sequence(review_report.get("errors")) if isinstance(item, Mapping))
            warnings.extend(dict(item) for item in _sequence(review_report.get("warnings")) if isinstance(item, Mapping))

        visual_assets = [asset for asset in manifest.assets if asset.kind in VISUAL_ASSET_TYPES]
        visual_blocks = [block for block in document.blocks if block.type in VISUAL_BLOCK_TYPES]
        asset_backed_blocks = [block for block in document.blocks if block.type in ASSET_BACKED_BLOCK_TYPES]

        return {
            "passed": not errors,
            "gate": self.gate_name,
            "reviewer": review_report.get("reviewer") if isinstance(review_report, Mapping) else None,
            "gates": _gate_summaries(errors=errors, warnings=warnings),
            "errors": errors,
            "warnings": warnings,
            "memory": dict(review_report.get("memory")) if isinstance(review_report, Mapping) and isinstance(review_report.get("memory"), Mapping) else None,
            "memoryMatches": list(review_report.get("memoryMatches")) if isinstance(review_report, Mapping) and isinstance(review_report.get("memoryMatches"), list) else [],
            "assetCount": len(manifest.assets),
            "visualAssetCount": len(visual_assets),
            "blockCount": len(document.blocks),
            "visualBlockCount": len(visual_blocks),
            "assetBackedBlockCount": len(asset_backed_blocks),
        }


def _issue(code: str, message: str, *, gate: str, **details: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message, "gate": gate}
    payload.update({key: value for key, value in details.items() if value not in (None, "", [], {})})
    return payload


def _gate_summaries(*, errors: list[Mapping[str, Any]], warnings: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    gates = ("image", "table", "equation", "symbol")
    return [
        {
            "name": gate,
            "passed": not any(_issue_gate(issue) == gate for issue in errors),
            "errorCount": sum(1 for issue in errors if _issue_gate(issue) == gate),
            "warningCount": sum(1 for issue in warnings if _issue_gate(issue) == gate),
        }
        for gate in gates
    ]


def _issue_gate(issue: Mapping[str, Any]) -> str:
    gate = _text(issue.get("gate"))
    if gate:
        return gate
    code = _text(issue.get("code"))
    if code.startswith("table_"):
        return "table"
    if code.startswith("equation_") or code.startswith("inline_equation_"):
        return "equation"
    if "mojibake" in code or "html_entity" in code or "latex_" in code or "alignment_symbols" in code or "control_character" in code:
        return "symbol"
    return "image"


def _asset_size(path: Path, mime_type: str, width: int, height: int) -> tuple[int, int] | None:
    if mime_type.startswith("text/html"):
        return (width, height) if width > 0 and height > 0 and path.read_text(encoding="utf-8", errors="ignore").strip() else None
    return _png_size(path)


def _png_size(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError:
        return None
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", header[16:24])


def _sequence(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
