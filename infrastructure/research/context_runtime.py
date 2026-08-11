from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from framework.events.canonical import checksum_for
from framework.harness import (
    ArtifactPort,
    ContextAssembler,
    ContextCompactionRuntime,
    ContextEnvelope,
    ContextGroup,
    ContextGroupKind,
    ContextPhysicalMaterialization,
    ContextSemanticSnapshot,
    HarnessEventPort,
    HarnessValidationError,
)
from framework.llm.context import (
    OPENAI_CHAT_NORMALIZER_REVISION,
    LLMRequestPreparer,
    ModelContextProfile,
    build_default_request_preparer,
)
from framework.llm.context.harness_adapter import (
    Change1ContextPhysicalAdmissionVerifier,
)
from framework.llm.context.tokens import canonical_json_bytes
from framework.llm.models import LLMRequest
from framework.shared.json import stable_json_dumps


RESEARCH_CONTEXT_MATERIALIZATION_REVISION = (
    "newsroom.research-context-ref-request/v1"
)


class ResearchContextPhysicalMaterializer:
    """Build the exact ref-only request represented by a Research envelope."""

    def __init__(
        self,
        envelope: ContextEnvelope,
        *,
        request_preparer: LLMRequestPreparer,
        profile: ModelContextProfile,
    ) -> None:
        if not isinstance(envelope, ContextEnvelope):
            raise HarnessValidationError("envelope must be ContextEnvelope")
        if envelope.budget is None:
            raise HarnessValidationError("Research context envelope requires a budget")
        if not isinstance(request_preparer, LLMRequestPreparer):
            raise HarnessValidationError("request_preparer must be LLMRequestPreparer")
        if not isinstance(profile, ModelContextProfile):
            raise HarnessValidationError("profile must be ModelContextProfile")
        self._envelope = envelope
        self._request_preparer = request_preparer
        self._profile = profile
        self._segments = {
            segment.segment_id: segment for segment in envelope.segments
        }

    def materialize(
        self,
        snapshot: ContextSemanticSnapshot,
        *,
        deployment_id: str,
    ) -> ContextPhysicalMaterialization:
        if deployment_id != self._profile.deployment_id:
            raise HarnessValidationError(
                "Research context deployment does not match the physical profile"
            )
        messages = [self._message(group) for group in snapshot.groups]
        request = LLMRequest(
            messages=messages,
            model=self._profile.model,
            temperature=0,
            # Reserve the deployment maximum so the configured input cap is
            # never widened by a smaller artifact-projection output request.
            max_tokens=self._profile.max_output_tokens,
            metadata={
                "component": "research_context_artifact",
                "run_id": snapshot.run_id,
                "step_id": snapshot.step_id,
            },
        )
        prepared = self._request_preparer.prepare(request, self._profile)
        message_tokens = prepared.token_count.message_tokens
        group_counts = _allocate_tokens(
            message_tokens,
            tuple(
                (group.group_id, len(canonical_json_bytes(message)))
                for group, message in zip(snapshot.groups, messages, strict=True)
            ),
        )
        fixed_tokens = prepared.token_count.total_input_tokens - sum(
            group_counts.values()
        )
        if fixed_tokens < 0:
            raise HarnessValidationError(
                "Research context physical token attribution is inconsistent"
            )
        return ContextPhysicalMaterialization(
            result_snapshot=snapshot,
            deployment_id=deployment_id,
            profile_revision=self._profile.profile_revision,
            materialization_revision=RESEARCH_CONTEXT_MATERIALIZATION_REVISION,
            request=request,
            fixed_input_tokens=fixed_tokens,
            group_input_tokens=group_counts,
            diagnostic_metadata={
                "projection": "research_context_ref_only",
                "token_count_method": prepared.token_count.method,
            },
        )

    def _message(self, group: ContextGroup) -> dict[str, str]:
        segment_id = group.semantic_metadata.get("legacy_segment_id")
        segment = self._segments.get(segment_id) if isinstance(segment_id, str) else None
        payload = {
            "group_id": group.group_id,
            "group_kind": group.group_kind.value,
            "member_refs": [member.content_ref for member in group.members],
            "source_refs": list(group.source_refs),
            "segment": segment.to_dict() if segment is not None else None,
        }
        return {
            "role": _message_role(group),
            "content": stable_json_dumps(payload),
        }


def build_research_context_assembler(
    *,
    artifact_port: ArtifactPort,
    event_port: HarnessEventPort,
    provider: str,
    model: str,
    max_input_tokens: int,
    max_output_tokens: int,
) -> ContextAssembler:
    profile = _research_context_profile(
        provider=provider,
        model=model,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
    )
    request_preparer = build_default_request_preparer((profile,))
    admission_verifier = Change1ContextPhysicalAdmissionVerifier(
        request_preparer,
        lambda deployment_id, profile_revision: _resolve_profile(
            profile,
            deployment_id=deployment_id,
            profile_revision=profile_revision,
        ),
    )

    def runtime_factory(
        envelope: ContextEnvelope,
        request: Mapping[str, Any],
    ) -> ContextCompactionRuntime:
        del request
        materializer = ResearchContextPhysicalMaterializer(
            envelope,
            request_preparer=request_preparer,
            profile=profile,
        )
        return ContextCompactionRuntime(
            materializer=materializer,
            admission_verifier=admission_verifier,
            artifact_port=artifact_port,
            event_port=event_port,
        )

    return ContextAssembler(
        compaction_runtime_factory=runtime_factory,
        deployment_id=profile.deployment_id,
        physical_profile_revision=profile.profile_revision,
    )


def _research_context_profile(
    *,
    provider: str,
    model: str,
    max_input_tokens: int,
    max_output_tokens: int,
) -> ModelContextProfile:
    identity = {
        "schema_revision": "newsroom.research-context-profile/v1",
        "provider": provider,
        "model": model,
        "max_input_tokens": max_input_tokens,
        "max_output_tokens": max_output_tokens,
    }
    digest = checksum_for(identity).removeprefix("sha256:")
    return ModelContextProfile(
        provider=provider,
        model=model,
        deployment_id=f"research-context-{digest[:16]}",
        physical_context_window_tokens=max_input_tokens + max_output_tokens,
        max_output_tokens=max_output_tokens,
        default_output_tokens=min(1_024, max_output_tokens),
        tokenizer_family="research-context-conservative",
        tokenizer_revision="research-context-utf8-upper-bound-v1",
        normalizer_revision=OPENAI_CHAT_NORMALIZER_REVISION,
        profile_revision=f"research-context-profile-{digest}",
        operational_input_fraction=1.0,
        safety_margin_tokens=0,
        allow_conservative_fallback=True,
        provider_auto_truncation=False,
    )


def _resolve_profile(
    profile: ModelContextProfile,
    *,
    deployment_id: str,
    profile_revision: str,
) -> ModelContextProfile:
    if deployment_id != profile.deployment_id:
        raise HarnessValidationError("Research context deployment profile is unknown")
    if profile_revision != profile.profile_revision:
        raise HarnessValidationError("Research context profile revision is stale")
    return profile


def _message_role(group: ContextGroup) -> str:
    if group.group_kind in {
        ContextGroupKind.SYSTEM_INSTRUCTION,
        ContextGroupKind.WORKFLOW_CONTRACT,
        ContextGroupKind.OUTPUT_CONTRACT,
    }:
        return "system"
    member_roles = {
        member.role for member in group.members if member.role in {"user", "assistant"}
    }
    if len(member_roles) == 1:
        return next(iter(member_roles))
    return "user"


def _allocate_tokens(
    total: int,
    weighted_group_ids: tuple[tuple[str, int], ...],
) -> dict[str, int]:
    if not weighted_group_ids:
        return {}
    weight_total = sum(max(1, weight) for _, weight in weighted_group_ids)
    allocated: dict[str, int] = {}
    cumulative_weight = 0
    previous_boundary = 0
    for group_id, weight in weighted_group_ids:
        cumulative_weight += max(1, weight)
        boundary = total * cumulative_weight // weight_total
        allocated[group_id] = boundary - previous_boundary
        previous_boundary = boundary
    return allocated


__all__ = [
    "RESEARCH_CONTEXT_MATERIALIZATION_REVISION",
    "ResearchContextPhysicalMaterializer",
    "build_research_context_assembler",
]
