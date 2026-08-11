from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from framework.llm.context.profile import ModelContextProfile


TokenCountMethod = Literal[
    "exact",
    "provider_counter",
    "conservative_fallback",
    "unavailable",
]


@dataclass(frozen=True)
class LLMTokenCount:
    message_tokens: int
    tool_tokens: int
    response_schema_tokens: int
    media_tokens: int
    protocol_overhead_tokens: int
    total_input_tokens: int
    method: TokenCountMethod
    tokenizer_family: str
    tokenizer_revision: str
    normalizer_revision: str

    def __post_init__(self) -> None:
        components = (
            self.message_tokens,
            self.tool_tokens,
            self.response_schema_tokens,
            self.media_tokens,
            self.protocol_overhead_tokens,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in components):
            raise ValueError("token count components must be non-negative integers")
        if self.total_input_tokens != sum(components):
            raise ValueError("total_input_tokens must equal the sum of token components")
        if self.method not in {
            "exact",
            "provider_counter",
            "conservative_fallback",
            "unavailable",
        }:
            raise ValueError(f"unsupported token count method: {self.method}")
        for field_name in ("tokenizer_family", "tokenizer_revision", "normalizer_revision"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")

    @classmethod
    def unavailable(cls, profile: ModelContextProfile) -> LLMTokenCount:
        return cls(
            message_tokens=0,
            tool_tokens=0,
            response_schema_tokens=0,
            media_tokens=0,
            protocol_overhead_tokens=0,
            total_input_tokens=0,
            method="unavailable",
            tokenizer_family=profile.tokenizer_family,
            tokenizer_revision=profile.tokenizer_revision,
            normalizer_revision=profile.normalizer_revision,
        )

    def to_dict(self) -> dict[str, int | str]:
        return {
            "message_tokens": self.message_tokens,
            "tool_tokens": self.tool_tokens,
            "response_schema_tokens": self.response_schema_tokens,
            "media_tokens": self.media_tokens,
            "protocol_overhead_tokens": self.protocol_overhead_tokens,
            "total_input_tokens": self.total_input_tokens,
            "method": self.method,
            "tokenizer_family": self.tokenizer_family,
            "tokenizer_revision": self.tokenizer_revision,
            "normalizer_revision": self.normalizer_revision,
        }


class LLMTokenCounter(Protocol):
    def count(
        self,
        payload: dict[str, Any],
        *,
        profile: ModelContextProfile,
        normalizer_revision: str,
    ) -> LLMTokenCount:
        ...


class LLMTokenCounterRegistry:
    def __init__(
        self,
        *,
        conservative_fallback: LLMTokenCounter | None = None,
    ) -> None:
        self._counters: dict[tuple[str, str], LLMTokenCounter] = {}
        self._conservative_fallback = conservative_fallback or ConservativeUTF8ByteTokenCounter()

    def register(
        self,
        *,
        tokenizer_family: str,
        tokenizer_revision: str,
        counter: LLMTokenCounter,
    ) -> None:
        key = (
            _key_text(tokenizer_family, field="tokenizer_family"),
            _key_text(tokenizer_revision, field="tokenizer_revision"),
        )
        if key in self._counters:
            raise ValueError(f"token counter is already registered: {key!r}")
        self._counters[key] = counter

    def count(
        self,
        payload: dict[str, Any],
        *,
        profile: ModelContextProfile,
        normalizer_revision: str,
    ) -> LLMTokenCount | None:
        key = (profile.tokenizer_family.casefold(), profile.tokenizer_revision.casefold())
        counter = self._counters.get(key)
        if counter is not None:
            return counter.count(
                payload,
                profile=profile,
                normalizer_revision=normalizer_revision,
            )
        if not profile.allow_conservative_fallback:
            return None
        return self._conservative_fallback.count(
            payload,
            profile=profile,
            normalizer_revision=normalizer_revision,
        )


@dataclass(frozen=True)
class ConservativeUTF8ByteTokenCounter:
    revision: str = "canonical-utf8-bytes-v1"
    base_protocol_overhead: int = 8
    per_message_protocol_overhead: int = 4

    def count(
        self,
        payload: dict[str, Any],
        *,
        profile: ModelContextProfile,
        normalizer_revision: str,
    ) -> LLMTokenCount:
        messages = list(payload.get("messages") or [])
        text_messages, media_parts = _split_media_parts(messages)
        tools = list(payload.get("tools") or [])
        response_format = payload.get("response_format")
        protocol_fields = {
            key: deepcopy(value)
            for key, value in payload.items()
            if key not in {"messages", "tools", "response_format"}
        }

        message_tokens = _canonical_size(text_messages)
        tool_tokens = _canonical_size(tools) if tools else 0
        response_schema_tokens = _canonical_size(response_format) if response_format is not None else 0
        media_tokens = _canonical_size(media_parts) if media_parts else 0
        protocol_overhead_tokens = (
            self.base_protocol_overhead
            + self.per_message_protocol_overhead * len(messages)
            + (_canonical_size(protocol_fields) if protocol_fields else 0)
        )
        return LLMTokenCount(
            message_tokens=message_tokens,
            tool_tokens=tool_tokens,
            response_schema_tokens=response_schema_tokens,
            media_tokens=media_tokens,
            protocol_overhead_tokens=protocol_overhead_tokens,
            total_input_tokens=(
                message_tokens
                + tool_tokens
                + response_schema_tokens
                + media_tokens
                + protocol_overhead_tokens
            ),
            method="conservative_fallback",
            tokenizer_family=profile.tokenizer_family,
            tokenizer_revision=f"{profile.tokenizer_revision}+{self.revision}",
            normalizer_revision=normalizer_revision,
        )


_MEDIA_TYPES = {
    "audio",
    "image",
    "image_url",
    "input_audio",
    "input_image",
    "input_video",
    "video",
    "video_url",
}


def _split_media_parts(messages: list[Any]) -> tuple[list[Any], list[dict[str, Any]]]:
    media_parts: list[dict[str, Any]] = []

    def visit(value: Any) -> Any:
        if isinstance(value, dict):
            part_type = str(value.get("type") or "").strip().casefold()
            if part_type in _MEDIA_TYPES:
                media_parts.append(deepcopy(value))
                return {"type": part_type, "media_counted_separately": True}
            return {str(key): visit(item) for key, item in value.items()}
        if isinstance(value, list):
            return [visit(item) for item in value]
        if isinstance(value, tuple):
            return [visit(item) for item in value]
        return deepcopy(value)

    return visit(messages), media_parts


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_size(value: Any) -> int:
    return len(canonical_json_bytes(value))


def _key_text(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip().casefold()
