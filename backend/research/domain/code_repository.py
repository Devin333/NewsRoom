from __future__ import annotations

from datetime import datetime
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from backend.foundation import PrimitiveModel, canonicalize_url
from backend.research.domain.common import ensure_utc, non_negative_int, require_text


class CodeRepositoryObservation(PrimitiveModel):
    repo_url: str | None = None
    repository_url: str | None = None
    observed_at: datetime
    stars: int
    forks: int
    watchers: int | None = None
    branch: str | None = None
    commit_sha: str | None = None
    release: str | None = None
    source_snapshot_refs: list[str] = Field(default_factory=list)
    actor_scope: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("repo_url", "repository_url")
    @classmethod
    def _normalize_repo_url(cls, value: str | None) -> str | None:
        return canonicalize_url(require_text(value, "repo url")) if value else None

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
        repo_url = self.repo_url or self.repository_url
        if not repo_url:
            raise ValueError("repo url is required")
        object.__setattr__(self, "repo_url", repo_url)
        object.__setattr__(self, "repository_url", repo_url)
        object.__setattr__(self, "source_snapshot_refs", _unique_texts(self.source_snapshot_refs))
        scope = _normalized_scope(self.metadata)
        scope.update(_normalized_scope(self.actor_scope))
        object.__setattr__(self, "actor_scope", scope)
        if scope:
            object.__setattr__(self, "metadata", {**dict(self.metadata), "actor_scope": scope})
        object.__setattr__(self, "observed_at", ensure_utc(self.observed_at))
        return self


class CodeRepositorySignal(PrimitiveModel):
    """Typed, non-executable evidence about repository reproducibility."""

    signal: Literal[
        "readme",
        "license",
        "install",
        "requirements",
        "examples",
        "training",
        "inference",
        "checkpoint",
    ]
    present: bool = False
    status: Literal["observed", "not_observed", "unavailable", "denied", "unsupported"] | None = None
    detection_rule: str = "github_contents_allowlist@v1"
    matched_refs: list[str] = Field(default_factory=list)
    observed_at: datetime
    ref: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    source_snapshot_id: str | None = None
    source_snapshot_refs: list[str] = Field(default_factory=list)
    read_paths: list[str] = Field(default_factory=list)
    response_bytes: int | None = None
    content_hashes: dict[str, str] = Field(default_factory=dict)
    redaction_version: str = "github-observation-redaction-v1"
    github_request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize(self) -> "CodeRepositorySignal":
        object.__setattr__(self, "observed_at", ensure_utc(self.observed_at))
        object.__setattr__(self, "source_snapshot_refs", _unique_texts(self.source_snapshot_refs))
        object.__setattr__(self, "matched_refs", _unique_texts(self.matched_refs))
        object.__setattr__(self, "read_paths", _unique_texts(self.read_paths))
        if self.ref is not None:
            object.__setattr__(self, "ref", canonicalize_url(self.ref))
        status = self.status or ("observed" if self.present else "not_observed")
        if status == "observed" and not self.present:
            object.__setattr__(self, "present", True)
        elif status != "observed" and self.present:
            raise ValueError("non-observed repository signal cannot be present")
        object.__setattr__(self, "status", status)
        if self.source_snapshot_id and self.source_snapshot_id not in self.source_snapshot_refs:
            object.__setattr__(
                self,
                "source_snapshot_refs",
                _unique_texts([*self.source_snapshot_refs, self.source_snapshot_id]),
            )
        if self.response_bytes is not None and (
            isinstance(self.response_bytes, bool) or self.response_bytes < 0
        ):
            raise ValueError("repository signal response_bytes must be non-negative")
        if not str(self.detection_rule).strip():
            raise ValueError("repository signal detection_rule is required")
        return self


class CodeRepositoryProfile(PrimitiveModel):
    repo_url: str | None = None
    repository_url: str | None = None
    canonical_repo_id: str | None = None
    owner: str
    name: str
    stars: int | None = None
    forks: int | None = None
    watchers: int | None = None
    open_issues: int | None = None
    license: str | None = None
    default_branch: str | None = None
    observed_branch: str | None = None
    commit_sha: str | None = None
    release: str | None = None
    last_commit_at: datetime | None = None
    release_count: int | None = None
    has_requirements: bool = False
    has_readme: bool = False
    has_examples: bool = False
    has_training_script: bool = False
    has_inference_demo: bool = False
    has_model_checkpoint: bool = False
    install_instructions_ref: str | None = None
    readme_ref: str | None = None
    requirements_ref: str | None = None
    examples_ref: str | None = None
    training_ref: str | None = None
    inference_ref: str | None = None
    checkpoint_ref: str | None = None
    readme_signal: bool = False
    requirements_signal: bool = False
    install_signal: bool = False
    examples_signal: bool = False
    training_signal: bool = False
    inference_signal: bool = False
    checkpoint_signal: bool = False
    paper_code_alignment: Literal["unknown", "candidate", "verified", "rejected"] = "unknown"
    star_growth_daily: float | None = None
    star_growth_7d: float | None = None
    star_growth_30d: float | None = None
    trend_label: Literal["unknown", "cooling", "steady", "warming", "hot"] = "unknown"
    observations: list[CodeRepositoryObservation] = Field(default_factory=list)
    signals: list[CodeRepositorySignal] = Field(default_factory=list)
    observation_limits: dict[str, int] = Field(default_factory=dict)
    source_snapshot_refs: list[str] = Field(default_factory=list)
    actor_scope: dict[str, str] = Field(default_factory=dict)
    observed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("repo_url", "repository_url", "owner", "name")
    @classmethod
    def _required_text(cls, value: str | None) -> str | None:
        return require_text(value, "repository profile fields") if value is not None else None

    @field_validator("stars", "forks", "watchers", "open_issues", "release_count")
    @classmethod
    def _optional_non_negative_metric(cls, value: int | None) -> int | None:
        return None if value is None else non_negative_int(value, "repository metric")

    @model_validator(mode="after")
    def _normalize(self) -> "CodeRepositoryProfile":
        repo_url = self.repo_url or self.repository_url
        if not repo_url:
            raise ValueError("repository profile fields repo_url is required")
        repo_url = canonicalize_url(repo_url)
        object.__setattr__(self, "repo_url", repo_url)
        object.__setattr__(self, "repository_url", repo_url)
        if self.observed_branch is None and self.default_branch:
            object.__setattr__(self, "observed_branch", self.default_branch)
        object.__setattr__(self, "install_signal", bool(self.install_signal or self.install_instructions_ref))
        object.__setattr__(self, "readme_signal", bool(self.readme_signal or self.has_readme))
        object.__setattr__(self, "requirements_signal", bool(self.requirements_signal or self.has_requirements))
        object.__setattr__(self, "examples_signal", bool(self.examples_signal or self.has_examples))
        object.__setattr__(self, "training_signal", bool(self.training_signal or self.has_training_script))
        object.__setattr__(self, "inference_signal", bool(self.inference_signal or self.has_inference_demo))
        object.__setattr__(self, "checkpoint_signal", bool(self.checkpoint_signal or self.has_model_checkpoint))
        if self.last_commit_at is not None:
            object.__setattr__(self, "last_commit_at", ensure_utc(self.last_commit_at))
        if self.observed_at is None:
            observation_times = [item.observed_at for item in self.observations]
            if observation_times:
                object.__setattr__(self, "observed_at", max(observation_times))
        elif self.observed_at is not None:
            object.__setattr__(self, "observed_at", ensure_utc(self.observed_at))
        object.__setattr__(self, "source_snapshot_refs", _unique_texts(self.source_snapshot_refs))
        scope = _normalized_scope(self.metadata)
        scope.update(_normalized_scope(self.actor_scope))
        object.__setattr__(self, "actor_scope", scope)
        if scope:
            object.__setattr__(self, "metadata", {**dict(self.metadata), "actor_scope": scope})
        for observation in self.observations:
            if observation.repo_url != repo_url:
                raise ValueError("repository observations must match profile repo_url")
        for signal in self.signals:
            if signal.status == "observed" and not signal.source_snapshot_refs:
                raise ValueError("observed repository signal requires source snapshot refs")
        forbidden = {
            key
            for key in ("runnable", "reproduced", "training_succeeded", "inference_succeeded")
            if key in self.metadata
        }
        if forbidden:
            raise ValueError("repository profile cannot claim execution outcomes")
        limits = {
            str(key): int(value)
            for key, value in self.observation_limits.items()
            if str(key).strip() and isinstance(value, int) and not isinstance(value, bool) and value >= 0
        }
        object.__setattr__(self, "observation_limits", limits)
        refs = {
            str(item)
            for item in self.source_snapshot_refs
            if str(item).strip()
        }
        for observation in self.observations:
            refs.update(observation.source_snapshot_refs)
        object.__setattr__(self, "source_snapshot_refs", sorted(refs))
        return self


def _unique_texts(values: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            result.append(text)
    return result


def _normalized_scope(value: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    source: dict[str, Any] = dict(value)
    nested = source.get("actor_scope")
    if isinstance(nested, Mapping):
        source.update(dict(nested))
    allowed = {"tenant_id", "user_id", "memory_namespace"}
    return {
        str(key): str(raw).strip()
        for key, raw in source.items()
        if str(key) in allowed and str(raw).strip()
    }


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


__all__ = ["CodeRepositoryObservation", "CodeRepositoryProfile", "CodeRepositorySignal", "compute_star_growth"]
