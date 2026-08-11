from __future__ import annotations

from collections.abc import Callable

from framework.harness.context.planning_models import ContextPhysicalAdmissionEvidence
from framework.harness.context.verification import ContextPhysicalMaterialization
from framework.harness.control_plane.errors import HarnessValidationError
from framework.llm.context.preflight import LLMRequestPreparer
from framework.llm.context.profile import ModelContextProfile


class Change1ContextPhysicalAdmissionVerifier:
    """Adapt Change 1's exact request preparation into the Harness port."""

    def __init__(
        self,
        request_preparer: LLMRequestPreparer,
        profile_resolver: Callable[[str, str], ModelContextProfile],
    ) -> None:
        if not isinstance(request_preparer, LLMRequestPreparer):
            raise HarnessValidationError(
                "request_preparer must be LLMRequestPreparer"
            )
        if not callable(profile_resolver):
            raise HarnessValidationError("profile_resolver must be callable")
        self._request_preparer = request_preparer
        self._profile_resolver = profile_resolver

    def admit(
        self,
        materialization: ContextPhysicalMaterialization,
    ) -> ContextPhysicalAdmissionEvidence:
        if not isinstance(materialization, ContextPhysicalMaterialization):
            raise HarnessValidationError(
                "materialization must be ContextPhysicalMaterialization"
            )
        profile = self._profile_resolver(
            materialization.deployment_id,
            materialization.profile_revision,
        )
        if not isinstance(profile, ModelContextProfile):
            raise HarnessValidationError(
                "profile resolver must return ModelContextProfile"
            )
        if profile.deployment_id != materialization.deployment_id:
            raise HarnessValidationError("resolved deployment does not match materialization")
        if profile.profile_revision != materialization.profile_revision:
            raise HarnessValidationError("resolved profile revision is stale")
        prepared = self._request_preparer.prepare(materialization.request, profile)
        token_count = prepared.token_count
        return ContextPhysicalAdmissionEvidence(
            source_snapshot_id=materialization.result_snapshot.snapshot_id,
            source_snapshot_checksum=materialization.result_snapshot.checksum,
            prepared_fingerprint=prepared.payload_fingerprint,
            physical_profile_revision=prepared.profile_revision,
            tokenizer_revision=token_count.tokenizer_revision,
            normalizer_revision=prepared.normalizer_revision,
            materialization_revision=materialization.materialization_revision,
            admission_status=prepared.admission.status.value,
            admitted=prepared.admission.provider_call_authorized,
            input_tokens=token_count.total_input_tokens,
            max_input_tokens=max(0, prepared.effective_budget.max_input_tokens),
            fixed_input_tokens=materialization.fixed_input_tokens,
            group_input_tokens=materialization.group_input_tokens,
        )


__all__ = ["Change1ContextPhysicalAdmissionVerifier"]
