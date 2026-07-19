from __future__ import annotations

import json
from pathlib import Path
from threading import Event, Thread

import pytest

import interfaces.composition.research as research_composition
from interfaces.composition.research import (
    ResearchRuntimeComposition,
    ResearchRuntimeProvider,
    build_research_application_service,
    build_research_runtime_composition,
    close_default_research_runtime,
    default_research_runtime_provider,
    reset_default_research_runtime,
)
from interfaces.composition.research_settings import ResearchRuntimeSettings
from interfaces.services.research_service import (
    InMemoryResearchRunStore,
    ResearchAnalyzeInput,
    ResearchApplicationService,
    ResearchRunRecord,
    ResearchServiceError,
)
from interfaces.services.source_runtime import SourceRuntimeProvider
from tests.interfaces.research_fixtures import FakeAnalyzeUseCase


class _ExplicitRunStore:
    def __init__(self) -> None:
        self.records: dict[str, ResearchRunRecord] = {}

    def save(self, record: ResearchRunRecord) -> None:
        self.records[record.run_id] = record

    def get_by_run_id(self, run_id: str) -> ResearchRunRecord | None:
        return self.records.get(run_id)

    def get_latest_by_paper_id(self, paper_id: str) -> ResearchRunRecord | None:
        matches = [record for record in self.records.values() if record.paper_id == paper_id]
        return matches[-1] if matches else None


class _Closable:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _BlockingClosable(_Closable):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.release = Event()

    def close(self) -> None:
        self.close_calls += 1
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("blocking close was not released")


def _settings(tmp_path: Path) -> ResearchRuntimeSettings:
    return ResearchRuntimeSettings.from_env(
        {"DASHSCOPE_API_KEY": "sk-explicit-test-only"},
        cwd=tmp_path,
    )


def test_provider_caches_explicit_composition_and_reuses_source_provider(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    source_provider = SourceRuntimeProvider()
    resources: list[_Closable] = []
    calls: list[tuple[ResearchRuntimeSettings, SourceRuntimeProvider]] = []

    def configured_factory(
        actual_settings: ResearchRuntimeSettings,
        actual_source_provider: SourceRuntimeProvider,
    ) -> ResearchRuntimeComposition:
        calls.append((actual_settings, actual_source_provider))
        resource = _Closable()
        resources.append(resource)
        return ResearchRuntimeComposition(
            settings=actual_settings,
            service=ResearchApplicationService(
                analyze_use_case=FakeAnalyzeUseCase(),
                run_store=_ExplicitRunStore(),
            ),
            source_runtime_provider=actual_source_provider,
            resources=(resource, resource),
        )

    provider = ResearchRuntimeProvider(
        settings_factory=lambda: settings,
        configured_factory=configured_factory,
        source_runtime_provider=source_provider,
    )

    first = provider.get()
    second = provider.get()

    assert first is second
    assert provider.service_factory() is first.service
    assert first.resources == (resources[0],)
    assert calls == [(settings, source_provider)]
    assert provider.initialized is True

    provider.reset()
    assert resources[0].close_calls == 1
    assert provider.initialized is False
    assert provider.get() is not first
    assert calls[-1] == (settings, source_provider)

    provider.close()
    assert resources[1].close_calls == 1
    assert provider.closed is True
    with pytest.raises(RuntimeError, match="ResearchRuntimeProvider is closed"):
        provider.get()

    provider.reset()
    assert provider.closed is False
    assert provider.get().service is not first.service
    provider.close()


def test_missing_configuration_returns_sanitized_typed_unavailable_service(
    tmp_path: Path,
) -> None:
    secret_url = "https://private-research-host.example/v1"
    secret_path = tmp_path / "private-run-root"
    source_provider = SourceRuntimeProvider()
    provider = ResearchRuntimeProvider(
        settings_factory=lambda: ResearchRuntimeSettings.from_env(
            {
                "NEWS_RESEARCH_LLM_BASE_URL": secret_url,
                "NEWS_RESEARCH_LLM_MODEL": "private-model",
                "NEWS_RESEARCH_LLM_API_KEY_ENV": "MISSING_PRIVATE_KEY",
                "NEWS_RESEARCH_RUN_STORE_ROOT": str(secret_path),
            },
            cwd=tmp_path,
        ),
        source_runtime_provider=source_provider,
    )

    composition = provider.get()
    service = composition.service

    assert composition.available is False
    assert composition.settings is None
    assert composition.source_runtime_provider is source_provider
    assert type(service._analyze_use_case).__name__ != "_UnconfiguredAnalyzeUseCase"
    assert not isinstance(service._run_store, InMemoryResearchRunStore)

    with pytest.raises(ResearchServiceError) as exc_info:
        service.analyze_paper(
            ResearchAnalyzeInput(
                paper_id="2607.00001",
                source_url="https://arxiv.org/abs/2607.00001",
            )
        )

    error = exc_info.value
    assert error.code == "research_runtime_unavailable"
    assert error.status_code == 503
    assert error.details == {
        "capabilities": ["research.llm.credential"],
        "remediation": {
            "code": "configure_research_llm_credential",
            "message": (
                "Provide the configured Research LLM credential through deployment secret "
                "management."
            ),
        },
    }
    public = json.dumps(
        {
            "code": error.code,
            "message": error.message,
            "details": error.details,
        },
        sort_keys=True,
    )
    assert secret_url not in public
    assert str(secret_path) not in public
    assert "private-model" not in public
    assert "MISSING_PRIVATE_KEY" not in public


def test_valid_settings_fail_closed_until_every_real_adapter_is_available(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    composition = build_research_runtime_composition(settings=settings)

    assert composition.available is False
    assert composition.settings == settings
    assert composition.availability_error is not None
    assert composition.availability_error.capabilities == (
        "research.candidate_worker",
        "research.rag",
        "research.storage.artifact",
        "research.storage.run_store",
        "research.event_log",
    )
    assert type(composition.service._analyze_use_case).__name__ != (
        "_UnconfiguredAnalyzeUseCase"
    )
    assert not isinstance(composition.service._run_store, InMemoryResearchRunStore)


def test_default_provider_is_lazy_and_reset_does_not_load_live_settings() -> None:
    reset_default_research_runtime()
    provider = default_research_runtime_provider()

    assert provider.initialized is False
    assert provider.closed is False

    reset_default_research_runtime()
    assert provider.initialized is False


def test_public_default_factory_close_and_reset_hooks_are_consistent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    source_provider = SourceRuntimeProvider()
    resources: list[_Closable] = []

    def configured_factory(
        actual_settings: ResearchRuntimeSettings,
        actual_source_provider: SourceRuntimeProvider,
    ) -> ResearchRuntimeComposition:
        resource = _Closable()
        resources.append(resource)
        return ResearchRuntimeComposition(
            settings=actual_settings,
            service=ResearchApplicationService(
                analyze_use_case=FakeAnalyzeUseCase(),
                run_store=_ExplicitRunStore(),
            ),
            source_runtime_provider=actual_source_provider,
            resources=(resource,),
        )

    provider = ResearchRuntimeProvider(
        settings_factory=lambda: settings,
        configured_factory=configured_factory,
        source_runtime_provider=source_provider,
    )
    monkeypatch.setattr(
        research_composition,
        "_DEFAULT_RESEARCH_RUNTIME_PROVIDER",
        provider,
    )

    first = build_research_application_service()
    second = build_research_application_service()
    assert first is second
    assert len(resources) == 1

    close_default_research_runtime()
    close_default_research_runtime()
    assert resources[0].close_calls == 1
    assert provider.closed is True

    reset_default_research_runtime()
    third = build_research_application_service()
    assert third is not first
    assert len(resources) == 2

    close_default_research_runtime()
    assert resources[1].close_calls == 1


def test_reset_finishes_closing_old_resources_before_rebuilding(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    source_provider = SourceRuntimeProvider()
    resources: list[_Closable] = []
    factory_calls: list[int] = []

    def configured_factory(
        actual_settings: ResearchRuntimeSettings,
        actual_source_provider: SourceRuntimeProvider,
    ) -> ResearchRuntimeComposition:
        factory_calls.append(len(factory_calls) + 1)
        resource: _Closable = (
            _BlockingClosable() if len(factory_calls) == 1 else _Closable()
        )
        resources.append(resource)
        return ResearchRuntimeComposition(
            settings=actual_settings,
            service=ResearchApplicationService(
                analyze_use_case=FakeAnalyzeUseCase(),
                run_store=_ExplicitRunStore(),
            ),
            source_runtime_provider=actual_source_provider,
            resources=(resource,),
        )

    provider = ResearchRuntimeProvider(
        settings_factory=lambda: settings,
        configured_factory=configured_factory,
        source_runtime_provider=source_provider,
    )
    provider.get()
    blocking = resources[0]
    assert isinstance(blocking, _BlockingClosable)

    reset_thread = Thread(target=provider.reset)
    reset_thread.start()
    assert blocking.started.wait(timeout=2)

    rebuilt: list[ResearchRuntimeComposition] = []
    get_thread = Thread(target=lambda: rebuilt.append(provider.get()))
    get_thread.start()

    assert factory_calls == [1]
    assert rebuilt == []

    blocking.release.set()
    reset_thread.join(timeout=2)
    get_thread.join(timeout=2)

    assert not reset_thread.is_alive()
    assert not get_thread.is_alive()
    assert factory_calls == [1, 2]
    assert len(rebuilt) == 1
    provider.close()
