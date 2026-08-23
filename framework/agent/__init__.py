"""Agent runtime namespace.

The package deliberately avoids importing every Agent subsystem at package
initialization time.  Artifact and Tool modules are also imported by Agent
models, so eager wildcard exports create a circular import before the runtime
can be admitted.  Public names remain available through a small lazy resolver.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_LAZY_MODULES = (
    "framework.agent.diagnostics",
    "framework.agent.loop",
    "framework.agent.messages",
    "framework.agent.models",
    "framework.agent.runtime",
    "framework.agent.skill_call",
    "framework.agent.skill_context",
    "framework.agent.skill_observation",
    "framework.agent.skill_selection",
    "framework.agent.subagents",
)


def __getattr__(name: str) -> Any:
    for module_name in _LAZY_MODULES:
        module = import_module(module_name)
        if hasattr(module, name):
            value = getattr(module, name)
            globals()[name] = value
            return value
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | {name for name in ()})


__all__: list[str] = []
