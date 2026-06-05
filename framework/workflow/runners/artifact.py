"""Artifact step runner."""

from __future__ import annotations

import time
from typing import Any

from framework.specs import StepSpec, StepStatus, StepType
from framework.workflow.buffer import StepScopedDataBufferView
from framework.artifacts import ArtifactManager
from framework.artifacts import ArtifactRef as StorageArtifactRef
from framework.workflow.runtime.result import StepOutcome
from framework.artifacts.runtime.publisher import LocalArtifactPublisher
from framework.workflow.runners._utils import (
    contract_metrics,
    failed_outcome,
    json_artifact_bytes,
    validated_outputs,
)
from framework.workflow.runners.base import (
    StepExecutionError,
    StepRunnerCapability,
    StepRunnerSideEffectLevel,
    ValidationErrorItem,
    default_runner_can_resolve,
)


class ArtifactStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.ARTIFACT,
        runner_id="builtin.artifact",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=False,
        side_effect_level=StepRunnerSideEffectLevel.EXTERNAL_WRITE,
        required_dependencies=["artifact_publisher"],
        description="Writes a workflow artifact through ArtifactManager.",
    )

    def __init__(
        self,
        artifact_manager: ArtifactManager | None = None,
        *,
        run_id: str | None = None,
        artifact_publisher: Any | None = None,
    ) -> None:
        self._artifact_manager = artifact_manager
        self._run_id = run_id
        self._artifact_publisher = artifact_publisher

    def configure_run_context(
        self,
        *,
        artifact_manager: ArtifactManager,
        run_id: str,
    ) -> None:
        self._artifact_manager = artifact_manager
        self._run_id = run_id
        if self._artifact_publisher is None:
            self._artifact_publisher = LocalArtifactPublisher(artifact_manager.root)

    def can_resolve(self, step: StepSpec) -> bool:
        return default_runner_can_resolve(self.capability, step)

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        if (
            step.metadata.get("content") is not None
            or step.metadata.get("content_key") is not None
        ):
            return []
        return [
            ValidationErrorItem(
                code="artifact_missing_content",
                message="Artifact step requires metadata.content or metadata.content_key.",
                field="metadata.content",
            )
        ]

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.ARTIFACT:
                raise StepExecutionError(
                    f"unsupported step type for ArtifactStepRunner: {step.step_type}"
                )
            if self._artifact_manager is None or self._run_id is None:
                raise StepExecutionError("ArtifactStepRunner requires run context")
            if self._artifact_publisher is None:
                self._artifact_publisher = LocalArtifactPublisher(
                    self._artifact_manager.root
                )

            content = step.metadata.get("content")
            content_key = step.metadata.get("content_key")
            if content_key is not None:
                content = buffer.read(str(content_key))
            relative_path = str(
                step.metadata.get("relative_path")
                or f"steps/{step.step_id}/output.json"
            )
            content_type = str(step.metadata.get("content_type") or "application/json")
            artifact_type = str(step.metadata.get("artifact_type") or "step_output")
            artifact_id = str(
                step.metadata.get("artifact_id") or f"{step.step_id}:{artifact_type}"
            )
            output_key = str(step.metadata.get("output_key") or "artifact_ref")

            if content_type == "text/plain" or relative_path.endswith((".md", ".txt")):
                data = str(content).encode("utf-8")
            else:
                data = json_artifact_bytes(content)

            publish_result = self._artifact_publisher.publish_artifact(
                run_id=self._run_id,
                step_id=step.step_id,
                key=output_key,
                artifact_type=artifact_type,
                content=data,
                metadata={
                    "artifact_id": artifact_id,
                    "relative_path": relative_path,
                    "content_type": content_type,
                    **dict(step.metadata.get("artifact_metadata") or {}),
                },
            )
            if not publish_result.succeeded or publish_result.artifact_ref is None:
                raise StepExecutionError(
                    publish_result.error or "artifact publish failed"
                )

            workflow_artifact_ref = publish_result.artifact_ref
            artifact_ref = StorageArtifactRef(
                artifact_id=artifact_id,
                run_id=self._run_id,
                step_id=step.step_id,
                artifact_type=artifact_type,
                path=workflow_artifact_ref.uri,
                content_type=content_type,
                size_bytes=workflow_artifact_ref.size_bytes,
                checksum=workflow_artifact_ref.content_hash,
                redacted=bool(step.metadata.get("redacted", True)),
                metadata={
                    "artifact_key": output_key,
                    "workflow_artifact_ref": workflow_artifact_ref.to_dict(),
                },
            )
            outputs = validated_outputs(
                step,
                {output_key: workflow_artifact_ref.to_dict()},
                runner_name="artifact step",
            )
            if output_key in buffer.list_allowed_writes():
                buffer.write(output_key, workflow_artifact_ref.to_dict())
            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                metrics=contract_metrics(
                    step,
                    started=started,
                    outputs=outputs,
                    artifact_count=1,
                ),
                artifacts=[artifact_ref],
            )
        except Exception as exc:
            return failed_outcome(
                step,
                exc,
                started=started,
                runner_name="ArtifactStepRunner",
            )

__all__ = ["ArtifactStepRunner"]


