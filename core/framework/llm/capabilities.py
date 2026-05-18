from __future__ import annotations

from dataclasses import dataclass


_CAPABILITY_ALIASES = {
    "json": "supports_json_mode",
    "json_mode": "supports_json_mode",
    "multimodal": "supports_multimodal_input",
    "multimodal_input": "supports_multimodal_input",
    "parallel_tool_calls": "supports_parallel_tool_calls",
    "prompt_cache": "supports_prompt_cache",
    "reasoning_tokens": "supports_reasoning_tokens",
    "streaming": "supports_streaming",
    "structured_output": "supports_structured_output",
    "tool_calling": "supports_tool_calling",
    "tools": "supports_tool_calling",
}


@dataclass(frozen=True)
class ModelCapabilities:
    supports_streaming: bool = False
    supports_tool_calling: bool = False
    supports_parallel_tool_calls: bool = False
    supports_structured_output: bool = False
    supports_json_mode: bool = False
    supports_multimodal_input: bool = False
    supports_reasoning_tokens: bool = False
    supports_prompt_cache: bool = False
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None

    def supports(self, capability: str) -> bool:
        attribute = _CAPABILITY_ALIASES.get(capability, _normalize_capability_name(capability))
        return bool(getattr(self, attribute, False))

    def missing(self, required_capabilities: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(capability for capability in required_capabilities if not self.supports(capability))

    def to_dict(self) -> dict[str, bool | int | None]:
        return {
            "supports_streaming": self.supports_streaming,
            "supports_tool_calling": self.supports_tool_calling,
            "supports_parallel_tool_calls": self.supports_parallel_tool_calls,
            "supports_structured_output": self.supports_structured_output,
            "supports_json_mode": self.supports_json_mode,
            "supports_multimodal_input": self.supports_multimodal_input,
            "supports_reasoning_tokens": self.supports_reasoning_tokens,
            "supports_prompt_cache": self.supports_prompt_cache,
            "context_window_tokens": self.context_window_tokens,
            "max_output_tokens": self.max_output_tokens,
        }


def _normalize_capability_name(capability: str) -> str:
    normalized = capability.strip().lower().replace("-", "_")
    normalized = _CAPABILITY_ALIASES.get(normalized, normalized)
    if normalized.startswith("supports_"):
        return normalized
    return f"supports_{normalized}"
