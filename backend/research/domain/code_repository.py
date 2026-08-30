from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from backend.foundation import PrimitiveModel, canonicalize_url
from backend.research.domain.common import ensure_utc, non_negative_int, require_text


class CodeRepositoryObservation(PrimitiveModel):
    repo_url: str
    observed_at: datetime
    stars: int
    forks: int
    watchers: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("repo_url")
    @classmethod
    def _required_repo_url(cls, value: str) -> str:
        return canonicalize_url(require_text(value, "repo url"))

    @field_validator("stars", "forks")
    @classmethod
    def _non_negative_metric(cls, value: int) -> int:
        return non_negative_int(value, "repository metric")

    @field_validator("watchers")
    @classmethod
    def _optional_non_negative_metric(cls, value: int | None) -> int | None:
        return None if value is None else non_negative_int(value, "repository metric")

    @model_validator(mode="after")
    def _normalize_time(self) -> "CodeRepositoryObservation":
        object.__setattr__(self, "observed_at", ensure_utc(self.observed_at))
        return self


class CodeRepositoryProfile(PrimitiveModel):
    repo_url: str
    owner: str
    name: str
    stars: int | None = None
    forks: int | None = None
    watchers: int | None = None
    open_issues: int | None = None
    license: str | None = None
    default_branch: str | None = None
    last_commit_at: datetime | None = None
    release_count: int | None = None
    has_requirements: bool = False
    has_readme: bool = False
    has_examples: bool = False
    has_training_script: bool = False
    has_inference_demo: bool = False
    has_model_checkpoint: bool = False
    install_instructions_ref: str | None = None
    paper_code_alignment: Literal["unknown", "candidate", "verified", "rejected"] = "unknown"
    star_growth_daily: float | None = None
    star_growth_7d: float | None = None
    star_growth_30d: float | None = None
    trend_label: Literal["unknown", "cooling", "steady", "warming", "hot"] = "unknown"
    observations: list[CodeRepositoryObservation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("repo_url", "owner", "name")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "repository profile fields")

    @field_validator("stars", "forks", "watchers", "open_issues", "release_count")
    @classmethod
    def _optional_non_negative_metric(cls, value: int | None) -> int | None:
        return None if value is None else non_negative_int(value, "repository metric")

    @model_validator(mode="after")
    def _normalize(self) -> "CodeRepositoryProfile":
        object.__setattr__(self, "repo_url", canonicalize_url(self.repo_url))
        if self.last_commit_at is not None:
            object.__setattr__(self, "last_commit_at", ensure_utc(self.last_commit_at))
        for observation in self.observations:
            if observation.repo_url != self.repo_url:
                raise ValueError("repository observations must match profile repo_url")
        return self


def compute_star_growth(
    current: CodeRepositoryObservation,
    previous: CodeRepositoryObservation,
) -> dict[str, float | str]:
    if current.repo_url != previous.repo_url:
        raise ValueError("star growth observations must reference the same repo")
    delta_days = max(
        (current.observed_at - previous.observed_at).total_seconds() / 86400.0,
        1.0,
    )
    daily = (current.stars - previous.stars) / delta_days
    if daily >= 100:
        trend = "hot"
    elif daily >= 20:
        trend = "warming"
    elif daily >= 0:
        trend = "steady"
    else:
        trend = "cooling"
    return {"star_growth_daily": round(daily, 4), "trend_label": trend}


__all__ = ["CodeRepositoryObservation", "CodeRepositoryProfile", "compute_star_growth"]
