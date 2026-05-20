from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping, Protocol


class SecretProvider(Protocol):
    def get(self, name: str) -> str | None: ...

    def require(self, name: str) -> str: ...


@dataclass(frozen=True)
class MappingSecretProvider:
    values: Mapping[str, str] = field(repr=False)

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def require(self, name: str) -> str:
        value = self.get(name)
        if value is None:
            raise KeyError(name)
        return value


@dataclass(frozen=True)
class EnvironmentSecretProvider:
    env: Mapping[str, str] = field(default_factory=lambda: os.environ, repr=False)

    def get(self, name: str) -> str | None:
        return self.env.get(name)

    def require(self, name: str) -> str:
        value = self.get(name)
        if value is None:
            raise KeyError(name)
        return value
