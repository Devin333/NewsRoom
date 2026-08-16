from __future__ import annotations

from pathlib import Path

from infrastructure.research.artifact_port import FilesystemHarnessArtifactPort
from infrastructure.storage.conversation import LocalJsonConversationStore
from interfaces.services.agent_loop_smoke_service import (
    AgentLoopGraphSmokeApplicationService,
)


def build_agent_loop_graph_smoke_service(
    *,
    artifact_root: str | Path = ".newsroom/smoke",
) -> AgentLoopGraphSmokeApplicationService:
    root = Path(artifact_root)
    return AgentLoopGraphSmokeApplicationService(
        artifact_port=FilesystemHarnessArtifactPort(root),
        conversation_store=LocalJsonConversationStore(
            root / "_state" / "agent-loop-conversations"
        ),
        artifact_root=root,
    )


__all__ = ["build_agent_loop_graph_smoke_service"]
