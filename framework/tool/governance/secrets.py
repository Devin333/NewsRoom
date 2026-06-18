from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping, Protocol


class SecretProvider(Protocol):
    def get_secret(self, name: str) -> str | None: ...


@dataclass(frozen=True)
class MappingSecretProvider:
    values: Mapping[str, str] = field(repr=False)

    def get_secret(self, name: str) -> str | None:
        return self.values.get(name)


@dataclass(frozen=True)
class EnvironmentSecretProvider:
    env: Mapping[str, str] = field(default_factory=lambda: os.environ, repr=False)

    def get_secret(self, name: str) -> str | None:
        return self.env.get(name)
