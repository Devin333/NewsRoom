from __future__ import annotations

from framework.agent.loop.runner import AgentRunner
from framework.harness.artifacts import RunBoundArtifactPort
from framework.harness.agent_loop import (
    AgentLoopGraphActivityBindingBundle,
    AgentLoopGraphArtifactRecorder,
    build_agent_loop_graph_activity_binding_bundle,
)
from framework.harness.control_plane import (
    HarnessControlPlane,
    HarnessRunResult,
    HarnessRunSpec,
)
from framework.harness.control_plane.activity_execution import (
    HarnessGraphActivityExecutionCommitPort,
)
from framework.harness.control_plane.node_output import HarnessNodeOutputResourcePort
from framework.harness.graph import HarnessContractReference
from framework.harness.ports import HarnessTransitionPort
from framework.harness.runtime import (
    HarnessGraphPhysicalActivityDispatcher,
    HarnessGraphPhysicalActivityExecutor,
)
from framework.harness.side_effects import (
    HarnessSideEffectRegistry,
    HarnessSideEffectStorePort,
)
from framework.shared.attempts import AttemptSupervisor
from framework.shared.time import utc_now
from framework.agent.models import AgentSpec
from framework.execution_environment.composition import RuntimeExecutionComposition
from framework.execution_environment.errors import RuntimeCompositionDriftError
from interfaces.services.agent_loop_graph_service import (
    AgentLoopGraphApplicationService,
)


class AgentLoopGraphRuntimeComposition:
    """Production composition root for one Graph-bound AgentLoop worker.

    It owns only exact runtime registration and physical activity dispatch. The
    Harness control plane remains the sole owner of Graph routing, durable
    wait registration/resume, terminal state, and publication decisions.
    """

    def __init__(
        self,
        *,
        agent_runner: AgentRunner,
        agent: AgentSpec,
        artifact_port: RunBoundArtifactPort,
        node_output_resource: HarnessNodeOutputResourcePort,
        event_port: HarnessTransitionPort,
        worker_ref: HarnessContractReference,
        activity_ref: HarnessContractReference,
        side_effect_registry: HarnessSideEffectRegistry | None = None,
        side_effect_store: HarnessSideEffectStorePort | None = None,
        runtime_execution_composition: RuntimeExecutionComposition | None = None,
    ) -> None:
        if not isinstance(agent_runner, AgentRunner):
            raise TypeError("agent_runner must be AgentRunner")
        if not isinstance(agent, AgentSpec):
            raise TypeError("agent must be AgentSpec")
        if not isinstance(artifact_port, RunBoundArtifactPort):
            raise TypeError("artifact_port must implement RunBoundArtifactPort")
        if not isinstance(node_output_resource, HarnessNodeOutputResourcePort):
            raise TypeError(
                "node_output_resource must implement HarnessNodeOutputResourcePort"
            )
        if not isinstance(event_port, HarnessTransitionPort):
            raise TypeError("event_port must implement HarnessTransitionPort")
        if getattr(event_port, "is_durable", False) is not True:
            raise ValueError(
                "AgentLoop Graph production composition requires a durable "
                "HarnessTransitionPort; InMemoryHarnessEventPort is test-only"
            )
        if runtime_execution_composition is not None:
            if not isinstance(runtime_execution_composition, RuntimeExecutionComposition):
                raise TypeError(
                    "runtime_execution_composition must be RuntimeExecutionComposition"
                )
            runtime_execution_composition.verify_integrity()
            if agent_runner.execution_environment is not runtime_execution_composition.execution_registry:
                raise RuntimeCompositionDriftError(
                    "AgentRunner execution registry does not match runtime composition",
                    details={
                        "composition_fingerprint": runtime_execution_composition.fingerprint,
                    },
                )

        bundle = build_agent_loop_graph_activity_binding_bundle(
            worker_ref=worker_ref,
            activity_ref=activity_ref,
            agent_runner=agent_runner,
            agent=agent,
            artifact_recorder=AgentLoopGraphArtifactRecorder(artifact_port),
            side_effect_registry=side_effect_registry,
        )
        control_plane = HarnessControlPlane(
            event_port=event_port,
            runtime_binding_authority=bundle.authority,
            side_effect_registry=side_effect_registry,
            side_effect_store=side_effect_store,
        )
        executor = HarnessGraphPhysicalActivityExecutor(
            binding_authority=bundle.authority,
            input_resolver=control_plane,
            node_output_resource=node_output_resource,
            result_committer=None,
            supervisor=AttemptSupervisor(clock=lambda: utc_now().timestamp()),
        )
        dispatcher = HarnessGraphPhysicalActivityDispatcher(
            executor=executor,
            graph_resolver=control_plane.graph_for_activity,
            input_resolver=control_plane,
            accept=control_plane.accept_graph_activity_for_execution,
            record_call_marker=control_plane.record_graph_activity_call_marker,
            record_result=control_plane.record_graph_activity_result_event,
            apply_result=control_plane.commit_physical_graph_result,
            durable_recovery_resolver=event_port.recover_graph,
            capabilities_resolver=lambda activity: bundle.authority.resolve_activity(
                activity,
                required_usage="serial",
            ).capabilities,
        )
        control_plane.install_graph_activity_dispatcher(dispatcher)
        self._bundle = bundle
        self._control_plane = control_plane
        self._runtime_execution_composition = runtime_execution_composition

    @property
    def binding_bundle(self) -> AgentLoopGraphActivityBindingBundle:
        return self._bundle

    @property
    def control_plane(self) -> HarnessControlPlane:
        return self._control_plane

    @property
    def runtime_execution_composition(self) -> RuntimeExecutionComposition | None:
        return self._runtime_execution_composition

    def run(self, run_spec: HarnessRunSpec) -> HarnessRunResult:
        if not isinstance(run_spec, HarnessRunSpec):
            raise TypeError("run_spec must be HarnessRunSpec")
        return self._control_plane.run(run_spec)

    def recover_and_run(self, run_spec: HarnessRunSpec) -> HarnessRunResult:
        """Resume a previously committed Graph run from durable history."""

        if not isinstance(run_spec, HarnessRunSpec):
            raise TypeError("run_spec must be HarnessRunSpec")
        return self._control_plane.recover_and_run(run_spec)

    def resume_after_approval(
        self,
        run_spec: HarnessRunSpec,
        *,
        approved: bool,
        approval_ref: str,
        actor_identity_scope_ref: str,
        reason: str | None = None,
    ) -> HarnessRunResult:
        """Resume or cancel an approval wait using durable Harness evidence."""

        if not isinstance(run_spec, HarnessRunSpec):
            raise TypeError("run_spec must be HarnessRunSpec")
        return self._control_plane.resume_after_approval(
            run_spec,
            approved=approved,
            reason=reason,
            approval_ref=approval_ref,
            actor_identity_scope_ref=actor_identity_scope_ref,
        )


def build_agent_loop_graph_application_service(
    *,
    agent_runner: AgentRunner,
    artifact_port: RunBoundArtifactPort,
    node_output_resource: HarnessNodeOutputResourcePort,
    result_committer: HarnessGraphActivityExecutionCommitPort,
    worker_ref: HarnessContractReference,
    activity_ref: HarnessContractReference,
) -> AgentLoopGraphApplicationService:
    """Compose AgentLoop's exact Graph leaf and durable owner ports.

    Storage, conversation, event, and terminal-manifest owners are supplied by
    the surrounding runtime composition. This factory intentionally creates no
    local fallback and has no terminal publication authority.
    """

    return AgentLoopGraphApplicationService(
        agent_runner=agent_runner,
        artifact_port=artifact_port,
        node_output_resource=node_output_resource,
        result_committer=result_committer,
        worker_ref=worker_ref,
        activity_ref=activity_ref,
    )


def build_agent_loop_graph_runtime_composition(
    *,
    agent_runner: AgentRunner,
    agent: AgentSpec,
    artifact_port: RunBoundArtifactPort,
    node_output_resource: HarnessNodeOutputResourcePort,
    event_port: HarnessTransitionPort,
    worker_ref: HarnessContractReference,
    activity_ref: HarnessContractReference,
    side_effect_registry: HarnessSideEffectRegistry | None = None,
    side_effect_store: HarnessSideEffectStorePort | None = None,
    runtime_execution_composition: RuntimeExecutionComposition | None = None,
) -> AgentLoopGraphRuntimeComposition:
    """Compose one durable AgentLoop Graph worker and its Harness dispatcher."""

    return AgentLoopGraphRuntimeComposition(
        agent_runner=agent_runner,
        agent=agent,
        artifact_port=artifact_port,
        node_output_resource=node_output_resource,
        event_port=event_port,
        worker_ref=worker_ref,
        activity_ref=activity_ref,
        side_effect_registry=side_effect_registry,
        side_effect_store=side_effect_store,
        runtime_execution_composition=runtime_execution_composition,
    )


__all__ = [
    "AgentLoopGraphRuntimeComposition",
    "build_agent_loop_graph_application_service",
    "build_agent_loop_graph_runtime_composition",
]
