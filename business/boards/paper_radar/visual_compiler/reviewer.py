from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any

from framework.llm import (
    DEFAULT_MODEL_ROUTE_ID,
    LLMConfigurationError,
    LLMMessage,
    LLMProviderError,
    LLMRequest,
    build_openai_compatible_client_from_config,
)
from business.boards.paper_radar.visual_compiler.models import PaperAssetManifest, PaperDocument, PaperReviewReport


PAPER_VISUAL_REVIEW_MODEL_ROUTE_ENV = "NEWSROOM_PAPER_VISUAL_REVIEW_MODEL_ROUTE"


class PaperDocumentReviewer:
    def review(self, *, document: PaperDocument, manifest: PaperAssetManifest, gate_report: Mapping[str, Any]) -> PaperReviewReport:
        raise NotImplementedError


class LLMPaperDocumentReviewer(PaperDocumentReviewer):
    reviewer_name = "llm-paper-visual-reviewer-v1"

    def __init__(
        self,
        *,
        model_route: str | None = None,
        llm_client_factory: Callable[[str], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.model_route = (
            model_route
            or os.environ.get(PAPER_VISUAL_REVIEW_MODEL_ROUTE_ENV)
            or DEFAULT_MODEL_ROUTE_ID
        )
        self.llm_client_factory = llm_client_factory or _default_llm_client_factory
        self.clock = clock or (lambda: datetime.now(UTC))

    def review(self, *, document: PaperDocument, manifest: PaperAssetManifest, gate_report: Mapping[str, Any]) -> PaperReviewReport:
        try:
            client = self.llm_client_factory(self.model_route)
            response = client.complete(_review_request(document=document, manifest=manifest, gate_report=gate_report))
        except (LLMConfigurationError, LLMProviderError, TimeoutError, OSError, RuntimeError) as exc:
            return PaperReviewReport(
                paperId=document.paperId,
                verdict="unavailable",
                reviewer=self.reviewer_name,
                modelRoute=self.model_route,
                createdAt=_iso(self.clock()),
                summary=f"AI review unavailable: {type(exc).__name__}",
                risks=(str(exc),),
                suggestions=("Retry visual compilation after the review provider is available.",),
            )

        payload = _parse_json_object(response.content or "")
        verdict = _verdict(payload.get("verdict"))
        if verdict is None:
            verdict = "fail"
        return PaperReviewReport(
            paperId=document.paperId,
            verdict=verdict,
            reviewer=self.reviewer_name,
            modelRoute=self.model_route,
            createdAt=_iso(self.clock()),
            summary=_text(payload.get("summary")) or ("Visual review passed." if verdict == "pass" else "Visual review did not pass."),
            findings=tuple(_string_list(payload.get("findings"))),
            risks=tuple(_string_list(payload.get("risks"))),
            suggestions=tuple(_string_list(payload.get("suggestions"))),
            raw=payload,
        )


class HeuristicPaperDocumentReviewer(PaperDocumentReviewer):
    """Test and offline reviewer. Production code should use the LLM reviewer by default."""

    def __init__(self, *, verdict: str = "pass", clock: Callable[[], datetime] | None = None) -> None:
        self.verdict = verdict if verdict in {"pass", "fail", "unavailable"} else "fail"
        self.clock = clock or (lambda: datetime.now(UTC))

    def review(self, *, document: PaperDocument, manifest: PaperAssetManifest, gate_report: Mapping[str, Any]) -> PaperReviewReport:
        asset_blocks = [block for block in document.blocks if block.type in {"figure", "table"}]
        equation_blocks = [block for block in document.blocks if block.type == "equation"]
        findings = [
            f"{len(document.blocks)} body blocks compiled.",
            f"{len(asset_blocks)} figure/table blocks bound to manifest assets.",
            f"{len(equation_blocks)} equation blocks generated as structured text.",
        ]
        risks: list[str] = []
        if not document.outline:
            risks.append("No heading outline was detected.")
        if gate_report.get("warnings"):
            risks.append("Asset Gate reported warnings.")
        return PaperReviewReport(
            paperId=document.paperId,
            verdict=self.verdict,  # type: ignore[arg-type]
            reviewer="heuristic-paper-visual-reviewer-v1",
            createdAt=_iso(self.clock()),
            summary="Heuristic review completed.",
            findings=tuple(findings),
            risks=tuple(risks),
            suggestions=("Inspect source-preview crops for any warning before publication.",) if risks else (),
        )


def _review_request(*, document: PaperDocument, manifest: PaperAssetManifest, gate_report: Mapping[str, Any]) -> LLMRequest:
    context = {
        "paper": document.paper,
        "outline": list(document.outline)[:40],
        "blockCounts": _block_counts(document),
        "sampleBlocks": [
            {
                "id": block.id,
                "type": block.type,
                "text": block.text[:800],
                "pageNumber": block.pageNumber,
                "assetId": block.assetId,
                "label": block.label,
                "caption": block.caption,
            }
            for block in document.blocks[:80]
        ],
        "assets": [
            {
                "assetId": asset.assetId,
                "kind": asset.kind,
                "pageNumber": asset.pageNumber,
                "label": asset.label,
                "caption": asset.caption,
                "width": asset.width,
                "height": asset.height,
                "blankRatio": asset.blankRatio,
            }
            for asset in manifest.assets
            if asset.kind != "page"
        ][:80],
        "gateReport": gate_report,
    }
    return LLMRequest(
        messages=[
            LLMMessage.system(
                "You review compiled academic paper reader artifacts. "
                "Use only the provided structured artifact metadata. "
                "Return strict JSON with keys: verdict, summary, findings, risks, suggestions. "
                "verdict must be pass or fail. Fail if the article structure is unreadable, visuals are mismatched, "
                "paper-body text appears to be AI summary, or serious source/asset risks remain."
                " Equation blocks should be readable generated text with source coordinates, not image assets."
            ),
            LLMMessage.user(
                "Review this PaperDocument artifact for publication readiness:\n"
                f"{json.dumps(context, ensure_ascii=False, sort_keys=True)}"
            ),
        ],
        temperature=0.1,
        max_tokens=1200,
        response_format={"type": "json_object"},
        metadata={"paper_id": document.paperId, "review_schema": "paper_visual_review_v1"},
    )


def _block_counts(document: PaperDocument) -> Mapping[str, int]:
    counts: dict[str, int] = {}
    for block in document.blocks:
        counts[block.type] = counts.get(block.type, 0) + 1
    return counts


def _parse_json_object(content: str) -> Mapping[str, Any]:
    stripped = content.strip()
    if not stripped:
        return {}
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return {"summary": stripped}
        try:
            payload = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return {"summary": stripped}
    return payload if isinstance(payload, Mapping) else {}


def _verdict(value: Any) -> str | None:
    text = _text(value).casefold()
    if text in {"pass", "approve", "approved", "publish"}:
        return "pass"
    if text in {"fail", "reject", "rejected", "needs_review", "needs review"}:
        return "fail"
    return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    return []


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _default_llm_client_factory(route: str):
    return build_openai_compatible_client_from_config(route)
