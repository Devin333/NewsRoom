from __future__ import annotations

from typing import Protocol, runtime_checkable

from business.research.code_repository.models import CodeRepositoryObservation, CodeRepositoryProfile


@runtime_checkable
class GithubRepositoryPort(Protocol):
    def fetch_profile(self, repo_url: str) -> CodeRepositoryProfile:
        ...

    def fetch_observation(self, repo_url: str) -> CodeRepositoryObservation:
        ...

__all__ = ["GithubRepositoryPort"]
