from __future__ import annotations

from dataclasses import dataclass

from framework.events.canonical import checksum_for
from framework.harness import (
    ContextAssembler,
    ContextCompactionRuntime,
    ContextPhysicalAdmissionEvidence,
    ContextPhysicalMaterialization,
    FakeArtifactPort,
    InMemoryHarnessEventPort,
)


@dataclass
class ReferencePhysicalContext:
    max_input_tokens: int
    profile_revision: str = "profile-reference-context-v1"

    def materialize(self, snapshot, *, deployment_id):
        group_tokens = {
            group.group_id: int(group.semantic_metadata.get("legacy_token_estimate", 2))
            for group in snapshot.groups
        }
        return ContextPhysicalMaterialization(
            result_snapshot=snapshot,
            deployment_id=deployment_id,
            profile_revision=self.profile_revision,
            materialization_revision="materializer-reference-context-v1",
            request={
                "snapshot_id": snapshot.snapshot_id,
                "ordered_group_ids": [group.group_id for group in snapshot.groups],
            },
            fixed_input_tokens=5,
            group_input_tokens=group_tokens,
        )

    def admit(self, materialization):
        input_tokens = materialization.fixed_input_tokens + sum(
            materialization.group_input_tokens.values()
        )
        admitted = input_tokens <= self.max_input_tokens
        return ContextPhysicalAdmissionEvidence(
            source_snapshot_id=materialization.result_snapshot.snapshot_id,
            source_snapshot_checksum=materialization.result_snapshot.checksum,
            prepared_fingerprint=checksum_for(materialization.request),
            physical_profile_revision=materialization.profile_revision,
            tokenizer_revision="tokenizer-reference-context-v1",
            normalizer_revision="normalizer-reference-context-v1",
            materialization_revision=materialization.materialization_revision,
            admission_status="admitted" if admitted else "input_limit_exceeded",
            admitted=admitted,
            input_tokens=input_tokens,
            max_input_tokens=self.max_input_tokens,
            fixed_input_tokens=materialization.fixed_input_tokens,
            group_input_tokens=materialization.group_input_tokens,
        )


def verified_context_assembler(
    *,
    max_input_tokens: int = 4_096,
    artifact_port: FakeArtifactPort | None = None,
) -> tuple[ContextAssembler, FakeArtifactPort, InMemoryHarnessEventPort]:
    artifacts = artifact_port or FakeArtifactPort()
    events = InMemoryHarnessEventPort()
    physical = ReferencePhysicalContext(max_input_tokens=max_input_tokens)
    assembler = ContextAssembler(
        compaction_runtime=ContextCompactionRuntime(
            materializer=physical,
            admission_verifier=physical,
            artifact_port=artifacts,
            event_port=events,
        ),
        deployment_id="deployment-reference-context",
        physical_profile_revision=physical.profile_revision,
    )
    return assembler, artifacts, events


__all__ = ["ReferencePhysicalContext", "verified_context_assembler"]
