from __future__ import annotations

import base64
import json
import math
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from http.client import RemoteDisconnected
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PAPER_PDF_PARSE_MODEL_ENABLED_ENV = "NEWSROOM_PAPER_PDF_PARSE_MODEL_ENABLED"
PAPER_PDF_PARSE_MODEL_BASE_URL_ENV = "NEWSROOM_PAPER_PDF_PARSE_MODEL_BASE_URL"
PAPER_PDF_PARSE_MODEL_API_KEY_ENV = "NEWSROOM_PAPER_PDF_PARSE_MODEL_API_KEY"
PAPER_PDF_PARSE_MODEL_NAME_ENV = "NEWSROOM_PAPER_PDF_PARSE_MODEL"
PAPER_PDF_PARSE_MODEL_TIMEOUT_SECONDS_ENV = "NEWSROOM_PAPER_PDF_PARSE_MODEL_TIMEOUT_SECONDS"
PAPER_PDF_PARSE_MODEL_MAX_TOKENS_ENV = "NEWSROOM_PAPER_PDF_PARSE_MODEL_MAX_TOKENS"
PAPER_PDF_PARSE_MODEL_MAX_ATTEMPTS_ENV = "NEWSROOM_PAPER_PDF_PARSE_MODEL_MAX_ATTEMPTS"

PaperLayoutRegionKind = Literal["figure", "table", "equation"]
ModelLayoutTransport = Callable[[Request, float], bytes]


class PaperLayoutProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class PaperLayoutProviderConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PaperLayoutRegion:
    kind: PaperLayoutRegionKind
    bbox: tuple[float, float, float, float]
    label: str | None = None
    caption: str | None = None
    confidence: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperLayoutDetection:
    regions: tuple[PaperLayoutRegion, ...] = ()
    diagnostics: tuple[Mapping[str, Any], ...] = ()


class PaperVisualLayoutProvider:
    provider_name = "paper-layout-provider"

    def detect_regions(
        self,
        *,
        page_image_bytes: bytes,
        page_number: int,
        page_width: float,
        page_height: float,
        rendered_width: int,
        rendered_height: int,
        captions: Sequence[Mapping[str, Any]],
    ) -> PaperLayoutDetection:
        raise NotImplementedError


class OpenAICompatiblePaperLayoutProvider(PaperVisualLayoutProvider):
    provider_name = "openai-compatible-vision-layout-v1"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 90.0,
        max_tokens: int = 1600,
        max_attempts: int = 2,
        transport: ModelLayoutTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.max_attempts = max(1, int(max_attempts))
        self._transport = transport or _urlopen_transport
        if not self.base_url:
            raise PaperLayoutProviderConfigurationError("PDF parse model base URL is required")
        if not self.api_key:
            raise PaperLayoutProviderConfigurationError("PDF parse model API key is required")
        if not self.model:
            raise PaperLayoutProviderConfigurationError("PDF parse model name is required")

    def detect_regions(
        self,
        *,
        page_image_bytes: bytes,
        page_number: int,
        page_width: float,
        page_height: float,
        rendered_width: int,
        rendered_height: int,
        captions: Sequence[Mapping[str, Any]],
    ) -> PaperLayoutDetection:
        if not page_image_bytes:
            return PaperLayoutDetection(
                diagnostics=(
                    _diagnostic("warning", "model_layout_page_image_empty", "page image bytes were empty", pageNumber=page_number),
                )
            )
        payload = self._request_payload(
            page_image_bytes=page_image_bytes,
            page_number=page_number,
            page_width=page_width,
            page_height=page_height,
            rendered_width=rendered_width,
            rendered_height=rendered_height,
            captions=captions,
        )
        request = Request(
            url=_chat_completions_url(self.base_url),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "NewsRoom/0.1 paper-visual-compiler",
            },
            method="POST",
        )
        raw_body = self._send_with_retries(request)

        response_payload = _json_object_from_bytes(raw_body)
        content = _message_content(response_payload)
        parsed = _json_object_from_text(content)
        if not parsed:
            return PaperLayoutDetection(
                diagnostics=(
                    _diagnostic("warning", "model_layout_empty_response", "model returned no parseable layout JSON", pageNumber=page_number),
                )
            )
        return _layout_detection_from_payload(
            parsed,
            page_number=page_number,
            page_width=page_width,
            page_height=page_height,
            rendered_width=rendered_width,
            rendered_height=rendered_height,
        )

    def _send_with_retries(self, request: Request) -> bytes:
        last_error: PaperLayoutProviderError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self._transport(request, self.timeout_seconds)
            except HTTPError as exc:
                retryable = int(exc.code) in {408, 409, 429, 500, 502, 503, 504}
                last_error = PaperLayoutProviderError(
                    f"PDF parse model request failed: HTTP {exc.code}",
                    code="model_layout_http_error",
                    retryable=retryable,
                )
            except (TimeoutError, RemoteDisconnected, URLError, OSError) as exc:
                last_error = PaperLayoutProviderError(
                    f"PDF parse model request failed: {type(exc).__name__}",
                    code="model_layout_network_error",
                    retryable=True,
                )
            if last_error is None or not last_error.retryable or attempt >= self.max_attempts:
                break
            time.sleep(min(1.5, 0.35 * attempt))
        if last_error is not None:
            raise last_error
        raise PaperLayoutProviderError("PDF parse model request failed", code="model_layout_unknown_error", retryable=True)

    def _request_payload(
        self,
        *,
        page_image_bytes: bytes,
        page_number: int,
        page_width: float,
        page_height: float,
        rendered_width: int,
        rendered_height: int,
        captions: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        context = {
            "pageNumber": page_number,
            "pdfCoordinateSystem": "origin is top-left; x grows right; y grows downward",
            "pageSizePoints": {"width": page_width, "height": page_height},
            "renderedImagePixels": {"width": rendered_width, "height": rendered_height},
            "captionCandidates": [_caption_candidate_payload(item) for item in captions][:30],
            "requiredJsonShape": {
                "regions": [
                    {
                        "kind": "figure | table | equation",
                        "label": "Figure 1 / Table 1 / Equation 1",
                        "caption": "figure or table caption text from the paper, not a summary",
                        "equationText": "standalone equation text or LaTeX when kind is equation",
                        "bbox": {"x0": 0, "y0": 0, "x1": page_width, "y1": page_height},
                        "confidence": 0.0,
                    }
                ]
            },
        }
        image_url = f"data:image/png;base64,{base64.b64encode(page_image_bytes).decode('ascii')}"
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You locate visual regions in academic paper PDF page images. "
                        "Return strict JSON only. Do not summarize, translate, or rewrite the paper. "
                        "Detect real figures, tables, and standalone equations. "
                        "Use the paper caption text if it is visible or provided. "
                        "For equations, return equationText as readable LaTeX or plain math text; equations are not image assets. "
                        "Bounding boxes must be in PDF page points with top-left origin. "
                        "Prefer one complete region for a multi-panel figure instead of many tiny sub-images. "
                        "Exclude surrounding prose; exclude the caption from the crop when the visual body is clear."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Parse this PDF page image for reader publication assets. "
                                f"Use this context:\n{json.dumps(context, ensure_ascii=False, sort_keys=True)}"
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }


def build_model_layout_provider_from_env(env: Mapping[str, str] | None = None) -> PaperVisualLayoutProvider | None:
    values = os.environ if env is None else env
    if not _truthy(values.get(PAPER_PDF_PARSE_MODEL_ENABLED_ENV)):
        return None
    base_url = _text(values.get(PAPER_PDF_PARSE_MODEL_BASE_URL_ENV))
    api_key = _text(values.get(PAPER_PDF_PARSE_MODEL_API_KEY_ENV))
    model = _text(values.get(PAPER_PDF_PARSE_MODEL_NAME_ENV))
    missing = [
        name
        for name, value in (
            (PAPER_PDF_PARSE_MODEL_BASE_URL_ENV, base_url),
            (PAPER_PDF_PARSE_MODEL_API_KEY_ENV, api_key),
            (PAPER_PDF_PARSE_MODEL_NAME_ENV, model),
        )
        if not value
    ]
    if missing:
        raise PaperLayoutProviderConfigurationError(
            "PDF parse model is enabled but missing: " + ", ".join(missing)
        )
    return OpenAICompatiblePaperLayoutProvider(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=_positive_float(values.get(PAPER_PDF_PARSE_MODEL_TIMEOUT_SECONDS_ENV)) or 90.0,
        max_tokens=_positive_int(values.get(PAPER_PDF_PARSE_MODEL_MAX_TOKENS_ENV)) or 1600,
        max_attempts=_positive_int(values.get(PAPER_PDF_PARSE_MODEL_MAX_ATTEMPTS_ENV)) or 2,
    )


def _layout_detection_from_payload(
    payload: Mapping[str, Any],
    *,
    page_number: int,
    page_width: float,
    page_height: float,
    rendered_width: int,
    rendered_height: int,
) -> PaperLayoutDetection:
    regions: list[PaperLayoutRegion] = []
    diagnostics: list[Mapping[str, Any]] = []
    for index, item in enumerate(_region_items(payload), start=1):
        if not isinstance(item, Mapping):
            diagnostics.append(_diagnostic("warning", "model_layout_region_invalid", "region is not an object", pageNumber=page_number, index=index))
            continue
        kind = _region_kind(item.get("kind") or item.get("type"))
        raw_bbox = _bbox_from_any(item.get("bbox") or item.get("box") or item.get("boundingBox"))
        if kind is None or raw_bbox is None:
            diagnostics.append(_diagnostic("warning", "model_layout_region_invalid", "region kind or bbox is missing", pageNumber=page_number, index=index))
            continue
        bbox = _normalize_bbox(
            raw_bbox,
            page_width=page_width,
            page_height=page_height,
            rendered_width=rendered_width,
            rendered_height=rendered_height,
        )
        if bbox is None:
            diagnostics.append(_diagnostic("warning", "model_layout_bbox_invalid", "region bbox is outside the page", pageNumber=page_number, index=index))
            continue
        regions.append(
            PaperLayoutRegion(
                kind=kind,
                bbox=bbox,
                label=_optional_text(item.get("label") or item.get("name")),
                caption=_optional_text(item.get("caption") or item.get("captionText")),
                confidence=_optional_float(item.get("confidence")),
                metadata={
                    "provider": OpenAICompatiblePaperLayoutProvider.provider_name,
                    "rawIndex": index,
                    "equationText": _optional_text(item.get("equationText") or item.get("latex") or item.get("formula")),
                },
            )
        )
    regions.sort(key=lambda region: (region.bbox[1], region.bbox[0]))
    return PaperLayoutDetection(regions=tuple(regions), diagnostics=tuple(diagnostics))


def _region_items(payload: Mapping[str, Any]) -> Sequence[Any]:
    for key in ("regions", "visualRegions", "items", "blocks", "detections"):
        value = payload.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return value
    return ()


def _normalize_bbox(
    bbox: tuple[float, float, float, float],
    *,
    page_width: float,
    page_height: float,
    rendered_width: int,
    rendered_height: int,
) -> tuple[float, float, float, float] | None:
    x0, y0, x1, y1 = bbox
    if max(abs(x0), abs(y0), abs(x1), abs(y1)) <= 1.5:
        x0, x1 = x0 * page_width, x1 * page_width
        y0, y1 = y0 * page_height, y1 * page_height
    elif max(x0, x1) > page_width * 1.12 or max(y0, y1) > page_height * 1.12:
        if rendered_width > 0 and rendered_height > 0:
            x0, x1 = x0 * page_width / rendered_width, x1 * page_width / rendered_width
            y0, y1 = y0 * page_height / rendered_height, y1 * page_height / rendered_height
    left = max(0.0, min(x0, x1))
    top = max(0.0, min(y0, y1))
    right = min(page_width, max(x0, x1))
    bottom = min(page_height, max(y0, y1))
    if right - left < 8 or bottom - top < 8:
        return None
    return (left, top, right, bottom)


def _caption_candidate_payload(item: Mapping[str, Any]) -> Mapping[str, Any]:
    bbox = item.get("bbox")
    return {
        "kind": item.get("kind"),
        "label": item.get("label"),
        "text": _text(item.get("text"))[:700],
        "bbox": _bbox_payload(bbox),
    }


def _json_object_from_bytes(raw_body: bytes) -> Mapping[str, Any]:
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PaperLayoutProviderError("PDF parse model response was not valid JSON", code="model_layout_response_invalid") from exc
    if not isinstance(payload, Mapping):
        raise PaperLayoutProviderError("PDF parse model response was not a JSON object", code="model_layout_response_invalid")
    return payload


def _message_content(payload: Mapping[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, Sequence) or not choices:
        raise PaperLayoutProviderError("PDF parse model response did not include choices", code="model_layout_response_invalid")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise PaperLayoutProviderError("PDF parse model choice was invalid", code="model_layout_response_invalid")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise PaperLayoutProviderError("PDF parse model message was invalid", code="model_layout_response_invalid")
    content = message.get("content")
    if isinstance(content, str):
        return content
    raise PaperLayoutProviderError("PDF parse model message content was not text", code="model_layout_response_invalid")


def _json_object_from_text(value: str) -> Mapping[str, Any]:
    stripped = value.strip()
    if not stripped:
        return {}
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return payload if isinstance(payload, Mapping) else {}


def _bbox_from_any(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, Mapping):
        coords = (
            _optional_float(_first_present(value, "x0", "left")),
            _optional_float(_first_present(value, "y0", "top")),
            _optional_float(_first_present(value, "x1", "right")),
            _optional_float(_first_present(value, "y1", "bottom")),
        )
        if all(item is not None for item in coords):
            return coords  # type: ignore[return-value]
        x = _optional_float(value.get("x"))
        y = _optional_float(value.get("y"))
        width = _optional_float(_first_present(value, "width", "w"))
        height = _optional_float(_first_present(value, "height", "h"))
        if x is not None and y is not None and width is not None and height is not None:
            return (x, y, x + width, y + height)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 4:
        coords = tuple(_optional_float(item) for item in value)
        if all(item is not None for item in coords):
            return coords  # type: ignore[return-value]
    return None


def _bbox_payload(value: Any) -> Mapping[str, float] | None:
    bbox = _bbox_from_any(value)
    if bbox is None:
        return None
    return {"x0": bbox[0], "y0": bbox[1], "x1": bbox[2], "y1": bbox[3]}


def _region_kind(value: Any) -> PaperLayoutRegionKind | None:
    text = _text(value).casefold()
    if text in {"fig", "figure", "image", "plot", "chart", "diagram"}:
        return "figure"
    if text in {"table", "tabular"}:
        return "table"
    if text in {"equation", "formula", "math"}:
        return "equation"
    return None


def _first_present(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value:
            return value.get(key)
    return None


def _diagnostic(severity: str, code: str, message: str, **details: Any) -> Mapping[str, Any]:
    payload: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    payload.update({key: value for key, value in details.items() if value not in (None, "", [], {})})
    return payload


def _urlopen_transport(request: Request, timeout_seconds: float) -> bytes:
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _truthy(value: Any) -> bool:
    return _text(value).casefold() in {"1", "true", "yes", "on", "enabled", "model"}


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
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _positive_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0:
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) and parsed > 0 else None
    return None


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None
