from __future__ import annotations

import base64
import logging
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from framework.llm.clients.openai_compatible import (
    LLMRetryPolicy,
    OpenAICompatibleClient,
    OpenAICompatibleConfig,
)
from framework.llm.models.request import LLMRequest
from framework.shared.time import format_datetime, utc_now
from framework.shared.env import load_root_env

from backend.research.application.llm_client import _browser_ua_transport
from backend.research.document.models import PaperChunk

logger = logging.getLogger(__name__)

_DEFAULT_PROMPT = (
    "Describe this academic paper visual artifact for retrieval. "
    "Be factual and concise. Mention visible architecture blocks, axes, labels, "
    "tables, equations, curves, arrows, datasets, metrics, and the main takeaway "
    "when visible. Do not infer unsupported claims.\n\n"
    "Caption:\n{caption}\n\n"
    "Nearby text:\n{context}"
)

_DESCRIPTION_SECTION = "Visual Description:"


@dataclass(frozen=True)
class VisualChunkDescriptionConfig:
    enabled: bool = False
    base_url: str = ""
    model: str = "gpt-5.4-mini"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = 120.0
    max_tokens: int = 260
    image_root: Path | None = None

    @classmethod
    def from_env(
        cls,
        *,
        env: Mapping[str, str] | None = None,
        image_root: str | os.PathLike[str] | None = None,
    ) -> "VisualChunkDescriptionConfig":
        load_root_env()
        values = env if env is not None else os.environ
        enabled = _env_truthy(values.get("NEWS_VISUAL_DESCRIPTION_ENABLED"))
        root_value = image_root or values.get("NEWS_VISUAL_DESCRIPTION_IMAGE_ROOT") or values.get("NEWS_VISUAL_IMAGE_ROOT")
        return cls(
            enabled=enabled,
            base_url=str(values.get("NEWS_VISUAL_DESCRIPTION_BASE_URL") or values.get("OPENAI_BASE_URL") or "").rstrip("/"),
            model=str(values.get("NEWS_VISUAL_DESCRIPTION_MODEL") or values.get("OPENAI_MODEL") or "gpt-5.4-mini"),
            api_key_env=str(values.get("NEWS_VISUAL_DESCRIPTION_API_KEY_ENV") or "OPENAI_API_KEY"),
            timeout_seconds=float(values.get("NEWS_VISUAL_DESCRIPTION_TIMEOUT_SECONDS") or 120.0),
            max_tokens=int(values.get("NEWS_VISUAL_DESCRIPTION_MAX_TOKENS") or 260),
            image_root=Path(root_value) if root_value else None,
        )


class OpenAICompatibleVisualChunkDescriber:
    """Uses an OpenAI-compatible multimodal chat model to enrich figure/table chunks."""

    def __init__(
        self,
        config: VisualChunkDescriptionConfig,
        *,
        client: OpenAICompatibleClient | None = None,
    ) -> None:
        self.config = config
        self._client = client or _build_client(config)

    def describe_chunks(self, chunks: list[PaperChunk]) -> list[PaperChunk]:
        updated: list[PaperChunk] = []
        for chunk in chunks:
            if not _should_describe(chunk):
                updated.append(chunk)
                continue
            described = self._describe_chunk(chunk)
            updated.append(described)
        return updated

    def _describe_chunk(self, chunk: PaperChunk) -> PaperChunk:
        image_ref = str(chunk.metadata.get("image_ref") or "")
        image_path = _resolve_image_path(
            image_ref,
            paper_id=chunk.paper_id,
            image_root=self.config.image_root,
        )
        if not image_path.exists():
            logger.warning("visual description image missing, skipped: %s", image_path)
            return _mark_description_skipped(chunk, reason="image_missing", image_path=image_path)

        try:
            description = self._request_description(chunk, image_path=image_path).strip()
        except Exception as exc:
            logger.warning("visual description failed for chunk %s: %s", chunk.chunk_id, exc)
            return _mark_description_skipped(chunk, reason=type(exc).__name__, image_path=image_path)

        if not description:
            return _mark_description_skipped(chunk, reason="empty_description", image_path=image_path)
        return _with_visual_description(
            chunk,
            description=description,
            model=self.config.model,
            image_path=image_path,
        )

    def _request_description(self, chunk: PaperChunk, *, image_path: Path) -> str:
        media_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
        data_url = "data:%s;base64,%s" % (
            media_type,
            base64.b64encode(image_path.read_bytes()).decode("ascii"),
        )
        request = LLMRequest(
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": _prompt_for_chunk(chunk)},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            max_tokens=self.config.max_tokens,
        )
        response = self._client.complete(request)
        return response.content or ""


def build_visual_chunk_describer_from_env(
    *,
    env: Mapping[str, str] | None = None,
    image_root: str | os.PathLike[str] | None = None,
) -> OpenAICompatibleVisualChunkDescriber | None:
    config = VisualChunkDescriptionConfig.from_env(env=env, image_root=image_root)
    values = env if env is not None else os.environ
    if not config.enabled:
        return None
    if not config.base_url:
        logger.warning("visual description disabled: OPENAI_BASE_URL is not configured")
        return None
    if not values.get(config.api_key_env):
        logger.warning("visual description disabled: %s is not configured", config.api_key_env)
        return None
    return OpenAICompatibleVisualChunkDescriber(config)


def _build_client(config: VisualChunkDescriptionConfig) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        OpenAICompatibleConfig(
            provider="openai-compatible-vision",
            base_url=config.base_url,
            model=config.model,
            api_key_env=config.api_key_env,
            timeout_seconds=config.timeout_seconds,
        ),
        transport=_browser_ua_transport,
        retry_policy=LLMRetryPolicy(max_attempts=2, retry_delay_seconds=(1.0,)),
    )


def _should_describe(chunk: PaperChunk) -> bool:
    if chunk.chunk_type not in {"figure", "table"}:
        return False
    if not chunk.metadata.get("image_ref"):
        return False
    return not str(chunk.metadata.get("visual_description") or "").strip()


def _prompt_for_chunk(chunk: PaperChunk) -> str:
    caption = _caption_for_chunk(chunk)
    context = _context_for_chunk(chunk)
    return _DEFAULT_PROMPT.format(caption=caption[:900], context=context[:1200])


def _caption_for_chunk(chunk: PaperChunk) -> str:
    caption_alignment = chunk.metadata.get("caption_alignment")
    if isinstance(caption_alignment, dict):
        caption = str(caption_alignment.get("caption_text") or "")
        if caption.strip():
            return caption.strip()
    for key in ("caption_text", "surya_caption"):
        text = str(chunk.metadata.get(key) or "")
        if text.strip():
            return text.strip()
    return _caption_block(chunk.content)


def _context_for_chunk(chunk: PaperChunk) -> str:
    marker = "Nearby Context:"
    normalized = chunk.content.casefold()
    index = normalized.find(marker.casefold())
    if index < 0:
        return chunk.content
    return chunk.content[index + len(marker):].strip()


def _caption_block(content: str) -> str:
    marker = "caption:"
    normalized = content.casefold()
    index = normalized.find(marker)
    if index < 0:
        return ""
    tail = content[index + len(marker):]
    lines: list[str] = []
    for line in tail.splitlines():
        stripped = line.strip()
        if not stripped:
            if lines:
                break
            continue
        if stripped.endswith(":") and lines:
            break
        lines.append(stripped)
    return " ".join(lines)


def _with_visual_description(
    chunk: PaperChunk,
    *,
    description: str,
    model: str,
    image_path: Path,
) -> PaperChunk:
    metadata = dict(chunk.metadata)
    metadata.update({
        "visual_description": description,
        "visual_description_model": model,
        "visual_description_source": "openai-compatible-vision",
        "visual_description_status": "ok",
        "visual_description_generated_at": format_datetime(utc_now()),
        "visual_description_image_path": str(image_path),
    })
    content = chunk.content
    if _DESCRIPTION_SECTION.casefold() not in content.casefold():
        content = f"{content.rstrip()}\n\n{_DESCRIPTION_SECTION}\n{description}"
    return chunk.model_copy(update={"content": content, "metadata": metadata})


def _mark_description_skipped(chunk: PaperChunk, *, reason: str, image_path: Path) -> PaperChunk:
    metadata = dict(chunk.metadata)
    metadata.update({
        "visual_description_skipped": True,
        "visual_description_skip_reason": reason,
        "visual_description_status": "missing_image" if reason == "image_missing" else "model_error",
        "visual_description_error_type": reason,
        "visual_description_image_path": str(image_path),
    })
    return chunk.model_copy(update={"metadata": metadata})


def _resolve_image_path(image_ref: str, *, paper_id: str, image_root: Path | None) -> Path:
    normalized = image_ref.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute():
        return path

    candidates: list[Path] = []
    if image_root is not None:
        candidates.extend([image_root / path, image_root / paper_id / path])
        if path.parts and path.parts[0] == ".newsroom":
            candidates.append(Path.cwd() / path)
        newsroom_index = normalized.find(".newsroom/")
        if newsroom_index > 0:
            candidates.append(Path.cwd() / normalized[newsroom_index:])
    candidates.extend([
        Path.cwd() / path,
        Path.cwd() / ".newsroom" / "papers" / paper_id / path,
    ])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else path


def _env_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "OpenAICompatibleVisualChunkDescriber",
    "VisualChunkDescriptionConfig",
    "build_visual_chunk_describer_from_env",
]
