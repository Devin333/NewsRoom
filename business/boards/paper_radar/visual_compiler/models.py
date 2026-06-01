from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal


PAPER_DOCUMENT_SCHEMA_VERSION = "paper_document_v1"
PAPER_TABLE_MODEL_STYLE_SCHEMA_VERSION = 2

PaperBlockType = Literal["heading", "paragraph", "figure", "table", "equation"]
PaperVisualAssetKind = Literal["page", "figure", "table", "equation"]
PaperCompileStatus = Literal[
    "queued",
    "compiling",
    "needs_review",
    "compile_failed",
    "review_failed",
    "compiled",
]

VISUAL_BLOCK_TYPES = {"figure", "table", "equation"}
ASSET_BACKED_BLOCK_TYPES = {"figure", "table"}
VISUAL_ASSET_TYPES = {"figure", "table"}


@dataclass(frozen=True)
class PaperSourceRegion:
    pageNumber: int
    bbox: tuple[float, float, float, float]
    pageWidth: float | None = None
    pageHeight: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pageNumber": self.pageNumber,
            "bbox": _bbox_to_dict(self.bbox),
        }
        if self.pageWidth is not None:
            payload["pageWidth"] = self.pageWidth
        if self.pageHeight is not None:
            payload["pageHeight"] = self.pageHeight
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> PaperSourceRegion | None:
        if not isinstance(payload, Mapping):
            return None
        page_number = _positive_int(payload.get("pageNumber") or payload.get("page"))
        bbox = _bbox_from_any(payload.get("bbox"))
        if page_number is None or bbox is None:
            return None
        return cls(
            pageNumber=page_number,
            bbox=bbox,
            pageWidth=_optional_float(payload.get("pageWidth")),
            pageHeight=_optional_float(payload.get("pageHeight")),
        )


@dataclass(frozen=True)
class PaperBlock:
    id: str
    paperId: str
    type: PaperBlockType
    text: str = ""
    level: int | None = None
    pageNumber: int | None = None
    sectionId: str | None = None
    assetId: str | None = None
    label: str | None = None
    caption: str | None = None
    source: PaperSourceRegion | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "paperId": self.paperId,
            "type": self.type,
        }
        for key, value in (
            ("text", self.text),
            ("level", self.level),
            ("pageNumber", self.pageNumber),
            ("sectionId", self.sectionId),
            ("assetId", self.assetId),
            ("label", self.label),
            ("caption", self.caption),
        ):
            if value not in (None, "", [], {}):
                payload[key] = value
        if self.source is not None:
            payload["source"] = self.source.to_dict()
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PaperBlock | None:
        block_id = _text(payload.get("id"))
        paper_id = _text(payload.get("paperId"))
        block_type = _block_type(payload.get("type"))
        if not block_id or not paper_id or block_type is None:
            return None
        metadata = payload.get("metadata")
        return cls(
            id=block_id,
            paperId=paper_id,
            type=block_type,
            text=_text(payload.get("text")),
            level=_positive_int(payload.get("level")),
            pageNumber=_positive_int(payload.get("pageNumber")),
            sectionId=_optional_text(payload.get("sectionId")),
            assetId=_optional_text(payload.get("assetId")),
            label=_optional_text(payload.get("label")),
            caption=_optional_text(payload.get("caption")),
            source=PaperSourceRegion.from_dict(payload.get("source")),
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )


@dataclass(frozen=True)
class PaperVisualAsset:
    assetId: str
    paperId: str
    kind: PaperVisualAssetKind
    fileName: str
    mimeType: str
    width: int
    height: int
    checksum: str
    pageNumber: int
    label: str | None = None
    caption: str | None = None
    source: PaperSourceRegion | None = None
    blankRatio: float | None = None
    fileSize: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "assetId": self.assetId,
            "paperId": self.paperId,
            "kind": self.kind,
            "fileName": self.fileName,
            "mimeType": self.mimeType,
            "width": self.width,
            "height": self.height,
            "checksum": self.checksum,
            "pageNumber": self.pageNumber,
        }
        for key, value in (
            ("label", self.label),
            ("caption", self.caption),
            ("blankRatio", self.blankRatio),
            ("fileSize", self.fileSize),
        ):
            if value not in (None, "", [], {}):
                payload[key] = value
        if self.source is not None:
            payload["source"] = self.source.to_dict()
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PaperVisualAsset | None:
        asset_id = _text(payload.get("assetId") or payload.get("id"))
        paper_id = _text(payload.get("paperId"))
        kind = _asset_kind(payload.get("kind"))
        file_name = _text(payload.get("fileName"))
        mime_type = _text(payload.get("mimeType"))
        checksum = _text(payload.get("checksum"))
        width = _positive_int(payload.get("width"))
        height = _positive_int(payload.get("height"))
        page_number = _positive_int(payload.get("pageNumber"))
        if not asset_id or not paper_id or kind is None or not file_name or not mime_type or not checksum:
            return None
        if width is None or height is None or page_number is None:
            return None
        metadata = payload.get("metadata")
        return cls(
            assetId=asset_id,
            paperId=paper_id,
            kind=kind,
            fileName=file_name,
            mimeType=mime_type,
            width=width,
            height=height,
            checksum=checksum,
            pageNumber=page_number,
            label=_optional_text(payload.get("label")),
            caption=_optional_text(payload.get("caption")),
            source=PaperSourceRegion.from_dict(payload.get("source")),
            blankRatio=_optional_float(payload.get("blankRatio")),
            fileSize=_positive_int(payload.get("fileSize")),
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )


@dataclass(frozen=True)
class PaperAssetManifest:
    paperId: str
    schemaVersion: str
    createdAt: str
    sourceHash: str
    assets: tuple[PaperVisualAsset, ...]
    sourcePdfFileName: str | None = None
    provider: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "paperId": self.paperId,
            "schemaVersion": self.schemaVersion,
            "createdAt": self.createdAt,
            "sourceHash": self.sourceHash,
            "assets": [asset.to_dict() for asset in self.assets],
        }
        if self.sourcePdfFileName:
            payload["sourcePdfFileName"] = self.sourcePdfFileName
        if self.provider:
            payload["provider"] = self.provider
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> PaperAssetManifest | None:
        if not isinstance(payload, Mapping):
            return None
        paper_id = _text(payload.get("paperId"))
        schema_version = _text(payload.get("schemaVersion"))
        created_at = _text(payload.get("createdAt"))
        source_hash = _text(payload.get("sourceHash"))
        if not paper_id or not schema_version or not created_at or not source_hash:
            return None
        assets = [
            asset
            for item in _sequence(payload.get("assets"))
            if isinstance(item, Mapping)
            for asset in [PaperVisualAsset.from_dict(item)]
            if asset is not None
        ]
        return cls(
            paperId=paper_id,
            schemaVersion=schema_version,
            createdAt=created_at,
            sourceHash=source_hash,
            assets=tuple(assets),
            sourcePdfFileName=_optional_text(payload.get("sourcePdfFileName")),
            provider=_optional_text(payload.get("provider")),
        )


@dataclass(frozen=True)
class PaperCompileInfo:
    paperId: str
    status: PaperCompileStatus
    provider: str
    sourceHash: str
    startedAt: str
    finishedAt: str | None = None
    sourcePdfUrl: str | None = None
    pageCount: int = 0
    blockCount: int = 0
    assetCount: int = 0
    diagnostics: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "paperId": self.paperId,
            "status": self.status,
            "provider": self.provider,
            "sourceHash": self.sourceHash,
            "startedAt": self.startedAt,
            "pageCount": self.pageCount,
            "blockCount": self.blockCount,
            "assetCount": self.assetCount,
            "diagnostics": [dict(item) for item in self.diagnostics],
        }
        if self.finishedAt:
            payload["finishedAt"] = self.finishedAt
        if self.sourcePdfUrl:
            payload["sourcePdfUrl"] = self.sourcePdfUrl
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> PaperCompileInfo | None:
        if not isinstance(payload, Mapping):
            return None
        paper_id = _text(payload.get("paperId"))
        status = _status(payload.get("status"))
        provider = _text(payload.get("provider"))
        source_hash = _text(payload.get("sourceHash"))
        started_at = _text(payload.get("startedAt"))
        if not paper_id or status is None or not provider or not source_hash or not started_at:
            return None
        return cls(
            paperId=paper_id,
            status=status,
            provider=provider,
            sourceHash=source_hash,
            startedAt=started_at,
            finishedAt=_optional_text(payload.get("finishedAt")),
            sourcePdfUrl=_optional_text(payload.get("sourcePdfUrl")),
            pageCount=_positive_int(payload.get("pageCount")) or 0,
            blockCount=_positive_int(payload.get("blockCount")) or 0,
            assetCount=_positive_int(payload.get("assetCount")) or 0,
            diagnostics=tuple(dict(item) for item in _sequence(payload.get("diagnostics")) if isinstance(item, Mapping)),
        )


@dataclass(frozen=True)
class PaperReviewReport:
    paperId: str
    verdict: Literal["pass", "fail", "unavailable"]
    reviewer: str
    createdAt: str
    summary: str
    findings: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    suggestions: tuple[str, ...] = ()
    modelRoute: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "paperId": self.paperId,
            "verdict": self.verdict,
            "reviewer": self.reviewer,
            "createdAt": self.createdAt,
            "summary": self.summary,
            "findings": list(self.findings),
            "risks": list(self.risks),
            "suggestions": list(self.suggestions),
        }
        if self.modelRoute:
            payload["modelRoute"] = self.modelRoute
        if self.raw:
            payload["raw"] = dict(self.raw)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> PaperReviewReport | None:
        if not isinstance(payload, Mapping):
            return None
        paper_id = _text(payload.get("paperId"))
        verdict = _review_verdict(payload.get("verdict"))
        reviewer = _text(payload.get("reviewer"))
        created_at = _text(payload.get("createdAt"))
        summary = _text(payload.get("summary"))
        if not paper_id or verdict is None or not reviewer or not created_at:
            return None
        raw = payload.get("raw")
        return cls(
            paperId=paper_id,
            verdict=verdict,
            reviewer=reviewer,
            createdAt=created_at,
            summary=summary,
            findings=tuple(_string_list(payload.get("findings"))),
            risks=tuple(_string_list(payload.get("risks"))),
            suggestions=tuple(_string_list(payload.get("suggestions"))),
            modelRoute=_optional_text(payload.get("modelRoute")),
            raw=dict(raw) if isinstance(raw, Mapping) else {},
        )


@dataclass(frozen=True)
class PaperSourceComparisonReport:
    paperId: str
    passed: bool
    comparer: str
    createdAt: str
    summary: str
    metrics: Mapping[str, Any] = field(default_factory=dict)
    errors: tuple[Mapping[str, Any], ...] = ()
    warnings: tuple[Mapping[str, Any], ...] = ()
    lessons: tuple[Mapping[str, Any], ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "paperId": self.paperId,
            "passed": self.passed,
            "comparer": self.comparer,
            "createdAt": self.createdAt,
            "summary": self.summary,
            "metrics": dict(self.metrics),
            "errors": [dict(item) for item in self.errors],
            "warnings": [dict(item) for item in self.warnings],
            "lessons": [dict(item) for item in self.lessons],
        }
        if self.raw:
            payload["raw"] = dict(self.raw)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> PaperSourceComparisonReport | None:
        if not isinstance(payload, Mapping):
            return None
        paper_id = _text(payload.get("paperId"))
        comparer = _text(payload.get("comparer"))
        created_at = _text(payload.get("createdAt"))
        summary = _text(payload.get("summary"))
        passed = payload.get("passed")
        if not paper_id or not comparer or not created_at or not isinstance(passed, bool):
            return None
        metrics = payload.get("metrics")
        raw = payload.get("raw")
        return cls(
            paperId=paper_id,
            passed=passed,
            comparer=comparer,
            createdAt=created_at,
            summary=summary,
            metrics=dict(metrics) if isinstance(metrics, Mapping) else {},
            errors=tuple(dict(item) for item in _sequence(payload.get("errors")) if isinstance(item, Mapping)),
            warnings=tuple(dict(item) for item in _sequence(payload.get("warnings")) if isinstance(item, Mapping)),
            lessons=tuple(dict(item) for item in _sequence(payload.get("lessons")) if isinstance(item, Mapping)),
            raw=dict(raw) if isinstance(raw, Mapping) else {},
        )


@dataclass(frozen=True)
class PaperDocument:
    paperId: str
    schemaVersion: str
    status: PaperCompileStatus
    title: str
    compiledAt: str
    sourceHash: str
    blocks: tuple[PaperBlock, ...]
    paper: Mapping[str, Any] = field(default_factory=dict)
    outline: tuple[Mapping[str, Any], ...] = ()
    auxiliary: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paperId": self.paperId,
            "schemaVersion": self.schemaVersion,
            "status": self.status,
            "title": self.title,
            "compiledAt": self.compiledAt,
            "sourceHash": self.sourceHash,
            "paper": dict(self.paper),
            "outline": [dict(item) for item in self.outline],
            "blocks": [block.to_dict() for block in self.blocks],
            "auxiliary": dict(self.auxiliary),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> PaperDocument | None:
        if not isinstance(payload, Mapping):
            return None
        paper_id = _text(payload.get("paperId"))
        schema_version = _text(payload.get("schemaVersion"))
        status = _status(payload.get("status"))
        title = _text(payload.get("title"))
        compiled_at = _text(payload.get("compiledAt"))
        source_hash = _text(payload.get("sourceHash"))
        if not paper_id or not schema_version or status is None or not title or not compiled_at or not source_hash:
            return None
        paper = payload.get("paper")
        auxiliary = payload.get("auxiliary")
        blocks = [
            block
            for item in _sequence(payload.get("blocks"))
            if isinstance(item, Mapping)
            for block in [PaperBlock.from_dict(item)]
            if block is not None
        ]
        outline = [dict(item) for item in _sequence(payload.get("outline")) if isinstance(item, Mapping)]
        return cls(
            paperId=paper_id,
            schemaVersion=schema_version,
            status=status,
            title=title,
            compiledAt=compiled_at,
            sourceHash=source_hash,
            blocks=tuple(blocks),
            paper=dict(paper) if isinstance(paper, Mapping) else {},
            outline=tuple(outline),
            auxiliary=dict(auxiliary) if isinstance(auxiliary, Mapping) else {},
        )


@dataclass(frozen=True)
class PaperCompileStatusRecord:
    paperId: str
    status: PaperCompileStatus
    updatedAt: str
    diagnostics: tuple[Mapping[str, Any], ...] = ()
    compileInfo: PaperCompileInfo | None = None
    reviewReport: PaperReviewReport | None = None
    gateReport: Mapping[str, Any] | None = None
    sourceComparisonReport: PaperSourceComparisonReport | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "paperId": self.paperId,
            "status": self.status,
            "updatedAt": self.updatedAt,
            "diagnostics": [dict(item) for item in self.diagnostics],
        }
        if self.compileInfo is not None:
            payload["compileInfo"] = self.compileInfo.to_dict()
        if self.reviewReport is not None:
            payload["reviewReport"] = self.reviewReport.to_dict()
        if self.gateReport is not None:
            payload["gateReport"] = dict(self.gateReport)
        if self.sourceComparisonReport is not None:
            payload["sourceComparisonReport"] = self.sourceComparisonReport.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> PaperCompileStatusRecord | None:
        if not isinstance(payload, Mapping):
            return None
        paper_id = _text(payload.get("paperId"))
        status = _status(payload.get("status"))
        updated_at = _text(payload.get("updatedAt"))
        if not paper_id or status is None or not updated_at:
            return None
        gate_report = payload.get("gateReport")
        return cls(
            paperId=paper_id,
            status=status,
            updatedAt=updated_at,
            diagnostics=tuple(dict(item) for item in _sequence(payload.get("diagnostics")) if isinstance(item, Mapping)),
            compileInfo=PaperCompileInfo.from_dict(payload.get("compileInfo")),
            reviewReport=PaperReviewReport.from_dict(payload.get("reviewReport")),
            gateReport=dict(gate_report) if isinstance(gate_report, Mapping) else None,
            sourceComparisonReport=PaperSourceComparisonReport.from_dict(payload.get("sourceComparisonReport")),
        )


def _block_type(value: Any) -> PaperBlockType | None:
    text = _text(value)
    if text in {"heading", "paragraph", "figure", "table", "equation"}:
        return text  # type: ignore[return-value]
    return None


def _asset_kind(value: Any) -> PaperVisualAssetKind | None:
    text = _text(value)
    if text in {"page", "figure", "table", "equation"}:
        return text  # type: ignore[return-value]
    return None


def _status(value: Any) -> PaperCompileStatus | None:
    text = _text(value)
    if text in {"queued", "compiling", "needs_review", "compile_failed", "review_failed", "compiled"}:
        return text  # type: ignore[return-value]
    return None


def _review_verdict(value: Any) -> Literal["pass", "fail", "unavailable"] | None:
    text = _text(value)
    if text in {"pass", "fail", "unavailable"}:
        return text  # type: ignore[return-value]
    return None


def _bbox_to_dict(bbox: tuple[float, float, float, float]) -> dict[str, float]:
    x0, y0, x1, y1 = bbox
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}


def _bbox_from_any(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, Mapping):
        coords = (
            _optional_float(value.get("x0")),
            _optional_float(value.get("y0")),
            _optional_float(value.get("x1")),
            _optional_float(value.get("y1")),
        )
        if all(item is not None for item in coords):
            return (coords[0], coords[1], coords[2], coords[3])  # type: ignore[return-value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 4:
        coords = tuple(_optional_float(item) for item in value)
        if all(item is not None for item in coords):
            return (coords[0], coords[1], coords[2], coords[3])  # type: ignore[return-value]
    return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return [_text(item) for item in _sequence(value) if _text(item)]


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value.is_integer() and value > 0:
        return int(value)
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None
