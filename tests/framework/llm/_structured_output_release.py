from __future__ import annotations

from framework.llm import (
    ProviderStructuredOutputRelease,
    ProviderStructuredOutputRollback,
)


_TEST_DIGEST = "sha256:" + ("1" * 64)


def approved_structured_output_release(
    *,
    provider: str,
    deployment: str,
    capability_revision: str,
    modes: frozenset[str] = frozenset({"native_strict", "constrained"}),
) -> ProviderStructuredOutputRelease:
    return ProviderStructuredOutputRelease(
        release_id=f"test-release:{provider}:{deployment}:{capability_revision}",
        provider=provider,
        deployment=deployment,
        capability_revision=capability_revision,
        approved_modes=modes,
        status="approved",
        rollout_state="enabled",
        workflow_scopes=("*",),
        corpus_revision="test-corpus-v1",
        corpus_digest=_TEST_DIGEST,
        observation_revision="test-observations-v1",
        observation_digest=_TEST_DIGEST,
        baseline_digest=_TEST_DIGEST,
        evaluation_report_digest=_TEST_DIGEST,
        evaluation_passed=True,
        evidence_kind="recorded_transport",
        evidence_refs=("test-evidence://structured-output",),
        decided_by="harness",
        approved_by="test-harness",
        approved_at="2026-08-11T00:00:00Z",
        owner="tests",
        rollout_revision="test-rollout-v1",
        rollback=ProviderStructuredOutputRollback(
            action="reject",
            triggers=("test_regression",),
        ),
        reason="Explicit test-only release fixture.",
    )


__all__ = ["approved_structured_output_release"]
