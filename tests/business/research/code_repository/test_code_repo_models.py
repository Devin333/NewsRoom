from __future__ import annotations

from datetime import timedelta

from business.research.code_repository import (
    CodeRepositoryObservation,
    CodeRepositoryProfile,
    compute_star_growth,
)
from business.research.domain.code_repository import (
    CodeRepositoryObservation as DomainCodeRepositoryObservation,
)
from business.research.domain.code_repository import (
    CodeRepositoryProfile as DomainCodeRepositoryProfile,
)
from tests.business.research.helpers import FIXED_NOW


def test_code_repository_public_models_reexport_domain_contracts() -> None:
    assert CodeRepositoryObservation is DomainCodeRepositoryObservation
    assert CodeRepositoryProfile is DomainCodeRepositoryProfile


def test_code_repository_profile_supports_star_growth_observations() -> None:
    previous = CodeRepositoryObservation(
        repo_url="https://github.com/newsroom/harnessed-research",
        observed_at=FIXED_NOW - timedelta(days=2),
        stars=10,
        forks=1,
        watchers=3,
    )
    current = CodeRepositoryObservation(
        repo_url="https://github.com/newsroom/harnessed-research",
        observed_at=FIXED_NOW,
        stars=30,
        forks=2,
        watchers=5,
    )
    growth = compute_star_growth(current, previous)
    profile = CodeRepositoryProfile(
        repo_url="https://github.com/newsroom/harnessed-research",
        owner="newsroom",
        name="harnessed-research",
        stars=current.stars,
        forks=current.forks,
        watchers=current.watchers,
        license="MIT",
        star_growth_daily=growth["star_growth_daily"],
        trend_label=growth["trend_label"],
        observations=[previous, current],
        metadata={"metrics_source": "github_repository_port"},
    )

    payload = profile.to_dict()

    assert payload["star_growth_daily"] == 10.0
    assert payload["trend_label"] == "steady"
    assert len(payload["observations"]) == 2
