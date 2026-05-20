from __future__ import annotations

from enum import Enum


class ToolStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    APPROVAL_REQUIRED = "approval_required"
    TIMEOUT = "timeout"


class ToolSideEffect(str, Enum):
    READ_ONLY = "read_only"
    WRITES_LOCAL_STATE = "writes_local_state"
    WRITES_EXTERNAL_STATE = "writes_external_state"
    NETWORK_ACCESS = "network_access"
    DANGEROUS = "dangerous"

    def requires_approval(self) -> bool:
        return self in {
            ToolSideEffect.WRITES_LOCAL_STATE,
            ToolSideEffect.WRITES_EXTERNAL_STATE,
            ToolSideEffect.NETWORK_ACCESS,
            ToolSideEffect.DANGEROUS,
        }
