from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Callable
from urllib.parse import urlsplit

from backend.research.domain.code_repository import (
    CodeRepositoryObservation,
    CodeRepositoryProfile,
    CodeRepositorySignal,
)
from infrastructure.external.sources.github import (
    GITHUB_API_URL,
    GithubConnector,
    GithubRepository,
)
from infrastructure.external.sources.models import (
    SourceDefinition,
    SourceReliability,
    SourceType,
)
from infrastructure.research.errors import (
    ResearchRepositoryError,
    summarize_source_failures,
)


UTC = timezone.utc
_GITHUB_HOSTS = {"github.com", "www.github.com"}


class GithubResearchRepositoryAdapter:
    """Map official GitHub repository metadata into Research code profiles."""

    def __init__(
        self,
        connector: GithubConnector | Any | None = None,
        *,
        api_url: str = GITHUB_API_URL,
        clock: Callable[[], datetime] | None = None,
        file_fetcher: Callable[[GithubRepository, str, str | None], str | None] | None = None,
    ) -> None:
        self._connector = connector or GithubConnector()
        self._api_url = str(api_url).strip() or GITHUB_API_URL
        self._clock = clock or (lambda: datetime.now(UTC))
        self._file_fetcher = file_fetcher

    def fetch_profile(self, repo_url: str) -> CodeRepositoryProfile:
        repository, canonical_url = parse_github_repository_url(repo_url)
        source = SourceDefinition(
            source_id=f"research-github-{_stable_suffix(repository.slug())}",
            name=f"GitHub {repository.slug()}",
            source_type=SourceType.GITHUB,
            url=self._api_url,
            reliability=SourceReliability.HIGH,
            authority_score=1.0,
            metadata={"repository": repository.slug()},
        )
        metadata, errors = self._connector.fetch_repository_metadata(
            source,
            repository=repository,
        )
        if errors or metadata is None:
            failure = summarize_source_failures(
                errors,
                default_error_type="repository_fetch_failed",
            )
            raise ResearchRepositoryError(
                "GitHub repository metadata is unavailable "
                f"({','.join(failure.error_types)})",
                retryable=failure.retryable,
            )
        if metadata.full_name.casefold() != repository.slug().casefold():
            raise ResearchRepositoryError(
                "GitHub repository response identity does not match the request"
            )
        observed_at = self._clock()
        release, release_count = self._latest_release(source, repository)
        commit_sha = self._latest_commit(source, repository)
        reproducibility = self._observe_reproducibility(
            source,
            repository,
            branch=metadata.default_branch,
            observed_at=observed_at,
        )
        observation = CodeRepositoryObservation(
            repo_url=canonical_url,
            observed_at=observed_at,
            stars=metadata.stargazers_count,
            forks=metadata.forks_count,
            watchers=metadata.watchers_count,
            branch=metadata.default_branch,
            commit_sha=commit_sha,
            release=release,
            source_snapshot_refs=[str(reproducibility["source_snapshot_ref"])],
            metadata={
                "metrics_source": "github_repository_api",
                "repository_id": metadata.repository_id,
                "default_branch": metadata.default_branch,
                "commit_sha": commit_sha,
                "release": release,
                "reproducibility": reproducibility,
            },
        )
        signal_snapshot_ref = str(reproducibility["source_snapshot_ref"])
        signals = [
            CodeRepositorySignal(
                signal=signal_name,
                present=bool(reproducibility.get(presence_key)),
                observed_at=observed_at,
                ref=(reproducibility.get("refs") or {}).get(signal_name),
                branch=metadata.default_branch,
                commit_sha=commit_sha,
                source_snapshot_refs=[signal_snapshot_ref],
                metadata={
                    "detection": "github_contents_api",
                    "checked_paths": list(reproducibility.get("checked_paths") or []),
                },
            )
            for signal_name, presence_key in (
                ("readme", "has_readme"),
                ("install", "install_instructions_ref"),
                ("requirements", "has_requirements"),
                ("examples", "has_examples"),
                ("training", "has_training_script"),
                ("inference", "has_inference_demo"),
                ("checkpoint", "has_model_checkpoint"),
            )
        ]
        return CodeRepositoryProfile(
            repo_url=canonical_url,
            canonical_repo_id=str(metadata.repository_id or repository.slug()),
            owner=repository.owner,
            name=repository.name,
            stars=metadata.stargazers_count,
            forks=metadata.forks_count,
            watchers=metadata.watchers_count,
            open_issues=metadata.open_issues_count,
            license=metadata.license_name,
            default_branch=metadata.default_branch,
            commit_sha=commit_sha,
            release=release,
            last_commit_at=metadata.pushed_at,
            release_count=release_count,
            has_requirements=bool(reproducibility["has_requirements"]),
            has_readme=bool(reproducibility["has_readme"]),
            has_examples=bool(reproducibility["has_examples"]),
            has_training_script=bool(reproducibility["has_training_script"]),
            has_inference_demo=bool(reproducibility["has_inference_demo"]),
            has_model_checkpoint=bool(reproducibility["has_model_checkpoint"]),
            install_instructions_ref=(
                str(reproducibility["install_instructions_ref"])
                if reproducibility.get("install_instructions_ref")
                else None
            ),
            readme_ref=_optional_ref(reproducibility, "readme"),
            requirements_ref=_optional_ref(reproducibility, "requirements"),
            examples_ref=_optional_ref(reproducibility, "examples"),
            training_ref=_optional_ref(reproducibility, "training"),
            inference_ref=_optional_ref(reproducibility, "inference"),
            checkpoint_ref=_optional_ref(reproducibility, "checkpoint"),
            install_signal=bool(reproducibility.get("install_instructions_ref")),
            readme_signal=bool(reproducibility["has_readme"]),
            requirements_signal=bool(reproducibility["has_requirements"]),
            examples_signal=bool(reproducibility["has_examples"]),
            training_signal=bool(reproducibility["has_training_script"]),
            inference_signal=bool(reproducibility["has_inference_demo"]),
            checkpoint_signal=bool(reproducibility["has_model_checkpoint"]),
            observed_at=observed_at,
            source_snapshot_refs=[str(reproducibility["source_snapshot_ref"])],
            observations=[observation],
            signals=signals,
            observation_limits={
                "max_files_checked": len(reproducibility.get("checked_paths") or []),
                "max_file_bytes": 256 * 1024,
            },
            metadata={
                "metrics_source": "github_repository_api",
                "repository_id": metadata.repository_id,
                "description": metadata.description,
                "language": metadata.language,
                "topics": list(metadata.topics),
                "archived": metadata.archived,
                "disabled": metadata.disabled,
                "visibility": metadata.visibility,
                "github_updated_at": (
                    metadata.updated_at.isoformat() if metadata.updated_at else None
                ),
                "reproducibility_observation": reproducibility,
            },
        )

    def fetch_observation(self, repo_url: str) -> CodeRepositoryObservation:
        profile = self.fetch_profile(repo_url)
        if not profile.observations:
            raise ResearchRepositoryError("GitHub repository observation is unavailable")
        return profile.observations[-1]

    def _observe_reproducibility(
        self,
        source: SourceDefinition,
        repository: GithubRepository,
        *,
        branch: str | None,
        observed_at: datetime,
    ) -> dict[str, Any]:
        probes = {
            "readme": ("README.md", "README.rst", "README.txt"),
            "requirements": ("requirements.txt", "pyproject.toml", "environment.yml", "setup.py"),
            "examples": ("examples", "example.py", "examples/README.md"),
            "training": ("train.py", "training", "scripts/train.py", "finetune.py"),
            "inference": ("inference.py", "predict.py", "demo.py", "app.py"),
            "checkpoint": ("checkpoints", "weights", "models", "MODEL_CARD.md"),
        }
        matched: dict[str, str] = {}
        readme_text: str | None = None
        checked: list[str] = []
        for signal, paths in probes.items():
            for path in paths:
                checked.append(path)
                content = self._fetch_repository_file(source, repository, path, branch)
                if content is None:
                    continue
                matched[signal] = path
                if signal == "readme" and content != "__directory__":
                    readme_text = content
                break
        install_ref = None
        if readme_text and any(marker in readme_text.casefold() for marker in ("pip install", "conda install", "installation", "getting started")):
            install_ref = f"https://github.com/{repository.slug()}/blob/{branch or 'HEAD'}/{matched['readme']}"
        refs = {
            signal: f"https://github.com/{repository.slug()}/blob/{branch or 'HEAD'}/{path}"
            for signal, path in matched.items()
        }
        revision_key = f"{branch or 'HEAD'}|{observed_at.isoformat()}|{matched}"
        observation_ref = f"github-observation://{repository.slug()}/{_stable_suffix(revision_key)}"
        return {
            "observed_at": observed_at.isoformat(),
            "source": "github_contents_api",
            "branch": branch,
            "checked_paths": checked,
            "matched_paths": matched,
            "refs": refs,
            "source_snapshot_ref": observation_ref,
            "has_readme": "readme" in matched,
            "has_requirements": "requirements" in matched,
            "has_examples": "examples" in matched,
            "has_training_script": "training" in matched,
            "has_inference_demo": "inference" in matched,
            "has_model_checkpoint": "checkpoint" in matched,
            "install_instructions_ref": install_ref,
            "runnable": None,
        }

    def _fetch_repository_file(
        self,
        source: SourceDefinition,
        repository: GithubRepository,
        path: str,
        branch: str | None,
    ) -> str | None:
        try:
            if self._file_fetcher is not None:
                return self._file_fetcher(repository, path, branch)
            fetcher = getattr(self._connector, "fetch_repository_file", None)
            if not callable(fetcher):
                return None
            result = fetcher(
                source,
                repository=repository,
                path=path,
                ref=branch,
            )
            if isinstance(result, tuple) and len(result) == 2:
                content, errors = result
                return None if errors else (str(content) if content is not None else None)
            return str(result) if result is not None else None
        except Exception:
            return None

    def _latest_commit(
        self,
        source: SourceDefinition,
        repository: GithubRepository,
    ) -> str | None:
        fetcher = getattr(self._connector, "fetch_commits", None)
        if not callable(fetcher):
            return None
        try:
            items, errors = fetcher(source, repository=repository, limit=1)
            if errors or not items:
                return None
            value = items[0].metadata.get("sha")
            return str(value) if value else None
        except Exception:
            return None

    def _latest_release(
        self,
        source: SourceDefinition,
        repository: GithubRepository,
    ) -> tuple[str | None, int | None]:
        fetcher = getattr(self._connector, "fetch_releases", None)
        if not callable(fetcher):
            return None, None
        try:
            items, errors = fetcher(source, repository=repository, limit=20)
            if errors:
                return None, None
            tag = items[0].metadata.get("tag_name") if items else None
            return (str(tag) if tag else None), len(items)
        except Exception:
            return None, None


def parse_github_repository_url(value: str) -> tuple[GithubRepository, str]:
    text = str(value or "").strip()
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in _GITHUB_HOSTS:
        raise ResearchRepositoryError("code repository must be an HTTPS GitHub URL")
    if parsed.query or parsed.fragment:
        raise ResearchRepositoryError("GitHub repository URL must not contain query or fragment")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise ResearchRepositoryError("GitHub repository URL must identify owner/repository")
    owner, name = parts
    if name.endswith(".git"):
        name = name[:-4]
    if not owner or not name or owner in {".", ".."} or name in {".", ".."}:
        raise ResearchRepositoryError("GitHub repository identity is invalid")
    repository = GithubRepository(owner=owner, name=name)
    return repository, f"https://github.com/{repository.slug()}"


def _stable_suffix(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:16]


def _optional_ref(observation: dict[str, Any], signal: str) -> str | None:
    refs = observation.get("refs")
    if not isinstance(refs, dict):
        return None
    value = refs.get(signal)
    return str(value) if value else None


__all__ = ["GithubResearchRepositoryAdapter", "parse_github_repository_url"]
