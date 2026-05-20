from __future__ import annotations


class MemoryRuntimeError(RuntimeError):
    """Base error for framework memory runtime failures."""


class MemoryValidationError(ValueError, MemoryRuntimeError):
    """Raised when memory input data is structurally invalid."""


class MemoryPolicyDenied(PermissionError, MemoryRuntimeError):
    """Raised when a memory operation is denied by policy."""


class MemoryStoreError(MemoryRuntimeError):
    """Raised when a memory store operation fails."""


class MemoryRecallError(MemoryRuntimeError):
    """Raised when memory recall cannot complete."""


class MemoryWriteError(MemoryRuntimeError):
    """Raised when memory write cannot complete."""


class MemoryContextAssemblyError(MemoryRuntimeError):
    """Raised when recall context assembly cannot complete."""


class MemoryNotFound(KeyError, MemoryRuntimeError):
    """Raised when a requested memory record does not exist."""
