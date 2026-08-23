from __future__ import annotations

from framework.agent.loop.runner import AgentRunner
from framework.harness.artifacts import RunBoundArtifactPort
from framework.harness.control_plane.activity_execution import (
    HarnessGraphActivityExecutionCommitPort,
)
from framework.harness.control_plane.node_output import HarnessNodeOutputResourcePort
from framework.harness.graph import HarnessContractReference
from interfaces.services.agent_loop_graph_service import (
    AgentLoopGraphApplicationService,
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


__all__ = ["build_agent_loop_graph_application_service"]
