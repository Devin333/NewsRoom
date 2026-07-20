from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlsplit, urlunsplit

from interfaces.composition.research_errors import (
    ResearchConfigurationError,
    ResearchRemediation,
    ResearchRuntimeUnavailableError,
)


_DEFAULT_ARXIV_API_URL = "https://export.arxiv.org/api/query"
_DEFAULT_LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_DEFAULT_LLM_MODEL = "deepseek-v4-flash"
_DEFAULT_SOURCE_MAX_BYTES = 120_000_000
_DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]*$")
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COLLECTION_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_PARSER_BACKENDS = {"marker", "mineru", "pymupdf"}
_RESEARCH_RUN_SCHEMA_VERSIONS = ("v1", "v2")


@dataclass(frozen=True, slots=True)
class ResearchSourceSettings:
    provider: str
    api_url: str
    cache_size: int
    timeout_seconds: float
    metadata_max_bytes: int
    package_max_bytes: int

    def __post_init__(self) -> None:
        provider = _identifier(self.provider, "research.source.provider", max_length=64)
        if provider != "arxiv":
            _invalid("research.source.provider")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(
            self,
            "api_url",
            _http_url(self.api_url, "research.source.api_url"),
        )
        _bounded_int(self.cache_size, "research.source.cache_size", 1, 4_096)
        _bounded_float(self.timeout_seconds, "research.source.timeout", 1.0, 300.0)
        _bounded_int(
            self.metadata_max_bytes,
            "research.source.metadata_max_bytes",
            1_024,
            20_000_000,
        )
        _bounded_int(
            self.package_max_bytes,
            "research.source.package_max_bytes",
            1_048_576,
            536_870_912,
        )


@dataclass(frozen=True, slots=True)
class ResearchLLMSettings:
    provider: str
    base_url: str
    model: str
    api_key_env: str
    timeout_seconds: float
    max_attempts: int
    max_input_tokens: int
    max_output_tokens: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider",
            _identifier(self.provider, "research.llm.provider", max_length=64),
        )
        object.__setattr__(
            self,
            "base_url",
            _http_url(self.base_url, "research.llm.base_url"),
        )
        object.__setattr__(
            self,
            "model",
            _identifier(self.model, "research.llm.model", max_length=200),
        )
        api_key_env = str(self.api_key_env or "").strip()
        if len(api_key_env) > 128 or _ENVIRONMENT_NAME.fullmatch(api_key_env) is None:
            _invalid("research.llm.credential")
        object.__setattr__(self, "api_key_env", api_key_env)
        _bounded_float(self.timeout_seconds, "research.llm.timeout", 1.0, 300.0)
        _bounded_int(self.max_attempts, "research.llm.max_attempts", 1, 5)
        _bounded_int(
            self.max_input_tokens,
            "research.llm.max_input_tokens",
            512,
            262_144,
        )
        _bounded_int(
            self.max_output_tokens,
            "research.llm.max_output_tokens",
            128,
            32_768,
        )


@dataclass(frozen=True, slots=True)
class ResearchParserSettings:
    backends: tuple[str, ...]
    allow_abstract_fallback: bool
    timeout_seconds: float
    max_document_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.backends, tuple):
            _invalid("research.parser.backends")
        backends = tuple(
            str(value).strip().lower()
            for value in self.backends
            if str(value).strip()
        )
        if (
            not backends
            or len(backends) != len(set(backends))
            or any(backend not in _PARSER_BACKENDS for backend in backends)
            or not any(backend in {"marker", "mineru"} for backend in backends)
        ):
            _invalid("research.parser.backends")
        if not isinstance(self.allow_abstract_fallback, bool):
            _invalid("research.parser.abstract_fallback")
        object.__setattr__(self, "backends", backends)
        _bounded_float(self.timeout_seconds, "research.parser.timeout", 1.0, 1_800.0)
        _bounded_int(
            self.max_document_bytes,
            "research.parser.max_document_bytes",
            1_048_576,
            536_870_912,
        )


@dataclass(frozen=True, slots=True)
class ResearchRAGSettings:
    backend: str
    local_root: Path
    qdrant_url: str | None
    collection: str
    vector_size: int
    max_rounds: int
    max_replans: int
    max_queries: int
    max_source_reads: int
    max_memory_hits: int
    max_context_items: int
    max_context_tokens: int
    max_worker_calls: int

    def __post_init__(self) -> None:
        backend = str(self.backend or "").strip().lower()
        if backend not in {"local", "qdrant"}:
            _invalid("research.rag.backend")
        object.__setattr__(self, "backend", backend)
        _directory_root(self.local_root, "research.rag.local_root")
        if backend == "qdrant":
            if self.qdrant_url is None:
                _invalid("research.rag.vector_backend")
            object.__setattr__(
                self,
                "qdrant_url",
                _http_url(self.qdrant_url, "research.rag.vector_backend"),
            )
        elif self.qdrant_url is not None:
            _invalid("research.rag.vector_backend")
        collection = str(self.collection or "").strip()
        if len(collection) > 128 or _COLLECTION_NAME.fullmatch(collection) is None:
            _invalid("research.rag.collection")
        object.__setattr__(self, "collection", collection)
        _bounded_int(self.vector_size, "research.rag.vector_size", 8, 8_192)
        _bounded_int(self.max_rounds, "research.rag.max_rounds", 1, 8)
        _bounded_int(self.max_replans, "research.rag.max_replans", 0, 4)
        _bounded_int(self.max_queries, "research.rag.max_queries", 1, 16)
        _bounded_int(self.max_source_reads, "research.rag.max_source_reads", 1, 32)
        _bounded_int(self.max_memory_hits, "research.rag.max_memory_hits", 0, 12)
        _bounded_int(self.max_context_items, "research.rag.max_context_items", 1, 32)
        _bounded_int(
            self.max_context_tokens,
            "research.rag.max_context_tokens",
            256,
            32_768,
        )
        _bounded_int(self.max_worker_calls, "research.rag.max_worker_calls", 0, 32)


@dataclass(frozen=True, slots=True)
class ResearchArtifactSettings:
    root: Path
    max_bytes: int

    def __post_init__(self) -> None:
        _directory_root(self.root, "research.storage.artifact_root")
        _bounded_int(
            self.max_bytes,
            "research.storage.artifact_max_bytes",
            1_024,
            536_870_912,
        )


@dataclass(frozen=True, slots=True)
class ResearchRunStoreSettings:
    root: Path
    max_record_bytes: int
    write_schema_version: str = "v2"
    supported_schema_versions: tuple[str, ...] = _RESEARCH_RUN_SCHEMA_VERSIONS
    rollback_schema_versions: tuple[str, ...] = _RESEARCH_RUN_SCHEMA_VERSIONS
    reconciliation_max_runs: int = 100

    def __post_init__(self) -> None:
        _directory_root(self.root, "research.storage.run_store_root")
        _bounded_int(
            self.max_record_bytes,
            "research.storage.run_record_max_bytes",
            1_024,
            536_870_912,
        )
        write_version = _research_run_schema_version(
            self.write_schema_version,
            "research.storage.run_store",
        )
        supported = _research_run_schema_versions(
            self.supported_schema_versions,
            "research.storage.run_store",
        )
        rollback = _research_run_schema_versions(
            self.rollback_schema_versions,
            "research.storage.run_store",
        )
        if write_version not in supported:
            _invalid("research.storage.run_store")
        if write_version == "v2":
            required = set(_RESEARCH_RUN_SCHEMA_VERSIONS)
            if set(supported) != required:
                _invalid("research.storage.run_store")
            if set(rollback) != required:
                _invalid("research.storage.run_store")
        _bounded_int(
            self.reconciliation_max_runs,
            "research.storage.run_store",
            1,
            10_000,
        )
        object.__setattr__(self, "write_schema_version", write_version)
        object.__setattr__(self, "supported_schema_versions", supported)
        object.__setattr__(self, "rollback_schema_versions", rollback)


@dataclass(frozen=True, slots=True)
class ResearchRuntimeSettings:
    research_root: Path
    source: ResearchSourceSettings
    llm: ResearchLLMSettings
    parser: ResearchParserSettings
    rag: ResearchRAGSettings
    artifact: ResearchArtifactSettings
    run_store: ResearchRunStoreSettings

    def __post_init__(self) -> None:
        _directory_root(self.research_root, "research.storage.root")
        expected_types = (
            (self.source, ResearchSourceSettings, "research.source"),
            (self.llm, ResearchLLMSettings, "research.llm"),
            (self.parser, ResearchParserSettings, "research.parser"),
            (self.rag, ResearchRAGSettings, "research.rag"),
            (self.artifact, ResearchArtifactSettings, "research.storage.artifact"),
            (self.run_store, ResearchRunStoreSettings, "research.storage.run_store"),
        )
        for value, expected_type, capability in expected_types:
            if not isinstance(value, expected_type):
                _invalid(capability)

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        cwd: str | os.PathLike[str] | None = None,
    ) -> "ResearchRuntimeSettings":
        values = os.environ if env is None else env
        base = _base_path(cwd)
        artifact_root = _root_from_env(
            values,
            ("NEWS_RESEARCH_ARTIFACT_ROOT", "NEWS_ARTIFACT_ROOT"),
            base / ".newsroom" / "runs",
            base=base,
            capability="research.storage.artifact_root",
        )
        research_root = _root_from_env(
            values,
            ("NEWS_RESEARCH_ROOT",),
            artifact_root.parent / "research",
            base=base,
            capability="research.storage.root",
        )
        run_store_root = _root_from_env(
            values,
            ("NEWS_RESEARCH_RUN_STORE_ROOT",),
            research_root / "runs",
            base=base,
            capability="research.storage.run_store_root",
        )
        rag_local_root = _root_from_env(
            values,
            ("NEWS_RESEARCH_RAG_LOCAL_ROOT",),
            research_root / "chunks",
            base=base,
            capability="research.rag.local_root",
        )

        llm = ResearchLLMSettings(
            provider=_first_text(
                values,
                ("NEWS_RESEARCH_LLM_PROVIDER", "NEWS_LLM_PROVIDER"),
                "openai-compatible",
            ),
            base_url=_first_text(
                values,
                (
                    "NEWS_RESEARCH_LLM_BASE_URL",
                    "NEWS_LLM_BASE_URL",
                    "OPENAI_BASE_URL",
                ),
                _DEFAULT_LLM_BASE_URL,
            ),
            model=_first_text(
                values,
                ("NEWS_RESEARCH_LLM_MODEL", "NEWS_LLM_MODEL", "OPENAI_MODEL"),
                _DEFAULT_LLM_MODEL,
            ),
            api_key_env=_first_text(
                values,
                ("NEWS_RESEARCH_LLM_API_KEY_ENV", "NEWS_LLM_API_KEY_ENV"),
                _default_api_key_env(values),
            ),
            timeout_seconds=_env_float(
                values,
                "NEWS_RESEARCH_LLM_TIMEOUT_SECONDS",
                90.0,
                capability="research.llm.timeout",
            ),
            max_attempts=_env_int(
                values,
                "NEWS_RESEARCH_LLM_MAX_ATTEMPTS",
                2,
                capability="research.llm.max_attempts",
            ),
            max_input_tokens=_env_int(
                values,
                "NEWS_RESEARCH_LLM_MAX_INPUT_TOKENS",
                8_192,
                capability="research.llm.max_input_tokens",
            ),
            max_output_tokens=_env_int(
                values,
                "NEWS_RESEARCH_LLM_MAX_OUTPUT_TOKENS",
                2_048,
                capability="research.llm.max_output_tokens",
            ),
        )
        rag_backend = _first_text(
            values,
            ("NEWS_RESEARCH_RAG_BACKEND",),
            "local",
        ).lower()
        qdrant_url = None
        if rag_backend == "qdrant":
            qdrant_url = _first_text(
                values,
                ("NEWS_RESEARCH_RAG_QDRANT_URL", "NEWS_QDRANT_URL"),
                _DEFAULT_QDRANT_URL,
            )
        vector_size = 64
        if rag_backend == "qdrant":
            vector_size = _env_int_from_names(
                values,
                (
                    "NEWS_RESEARCH_RAG_VECTOR_SIZE",
                    "NEWS_VECTOR_SIZE",
                    "NEWS_EMBEDDING_DIMENSIONS",
                ),
                64,
                capability="research.rag.vector_size",
            )

        settings = cls(
            research_root=research_root,
            source=ResearchSourceSettings(
                provider=_first_text(
                    values,
                    ("NEWS_RESEARCH_SOURCE_PROVIDER",),
                    "arxiv",
                ),
                api_url=_first_text(
                    values,
                    ("NEWS_RESEARCH_ARXIV_API_URL",),
                    _DEFAULT_ARXIV_API_URL,
                ),
                cache_size=_env_int(
                    values,
                    "NEWS_RESEARCH_SOURCE_CACHE_SIZE",
                    128,
                    capability="research.source.cache_size",
                ),
                timeout_seconds=_env_float(
                    values,
                    "NEWS_RESEARCH_SOURCE_TIMEOUT_SECONDS",
                    90.0,
                    capability="research.source.timeout",
                ),
                metadata_max_bytes=_env_int(
                    values,
                    "NEWS_RESEARCH_SOURCE_METADATA_MAX_BYTES",
                    1_000_000,
                    capability="research.source.metadata_max_bytes",
                ),
                package_max_bytes=_env_int(
                    values,
                    "NEWS_RESEARCH_SOURCE_PACKAGE_MAX_BYTES",
                    _DEFAULT_SOURCE_MAX_BYTES,
                    capability="research.source.package_max_bytes",
                ),
            ),
            llm=llm,
            parser=ResearchParserSettings(
                backends=_parser_backends(
                    _first_text(
                        values,
                        (
                            "NEWS_RESEARCH_PARSER_BACKENDS",
                            "NEWSROOM_PDF_PARSER_CASCADE",
                        ),
                        "mineru,marker",
                    )
                ),
                allow_abstract_fallback=_env_bool(
                    values,
                    "NEWS_RESEARCH_ALLOW_ABSTRACT_FALLBACK",
                    True,
                    capability="research.parser.abstract_fallback",
                ),
                timeout_seconds=_env_float(
                    values,
                    "NEWS_RESEARCH_PARSER_TIMEOUT_SECONDS",
                    300.0,
                    capability="research.parser.timeout",
                ),
                max_document_bytes=_env_int(
                    values,
                    "NEWS_RESEARCH_PARSER_MAX_DOCUMENT_BYTES",
                    _DEFAULT_SOURCE_MAX_BYTES,
                    capability="research.parser.max_document_bytes",
                ),
            ),
            rag=ResearchRAGSettings(
                backend=rag_backend,
                local_root=rag_local_root,
                qdrant_url=qdrant_url,
                collection=_first_text(
                    values,
                    ("NEWS_RESEARCH_RAG_COLLECTION",),
                    "research_paper_chunks",
                ),
                vector_size=vector_size,
                max_rounds=_env_int(
                    values,
                    "NEWS_RESEARCH_RAG_MAX_ROUNDS",
                    6,
                    capability="research.rag.max_rounds",
                ),
                max_replans=_env_int(
                    values,
                    "NEWS_RESEARCH_RAG_MAX_REPLANS",
                    1,
                    capability="research.rag.max_replans",
                ),
                max_queries=_env_int(
                    values,
                    "NEWS_RESEARCH_RAG_MAX_QUERIES",
                    12,
                    capability="research.rag.max_queries",
                ),
                max_source_reads=_env_int(
                    values,
                    "NEWS_RESEARCH_RAG_MAX_SOURCE_READS",
                    24,
                    capability="research.rag.max_source_reads",
                ),
                max_memory_hits=_env_int(
                    values,
                    "NEWS_RESEARCH_RAG_MAX_MEMORY_HITS",
                    8,
                    capability="research.rag.max_memory_hits",
                ),
                max_context_items=_env_int(
                    values,
                    "NEWS_RESEARCH_RAG_MAX_CONTEXT_ITEMS",
                    8,
                    capability="research.rag.max_context_items",
                ),
                max_context_tokens=_env_int(
                    values,
                    "NEWS_RESEARCH_RAG_MAX_CONTEXT_TOKENS",
                    4_096,
                    capability="research.rag.max_context_tokens",
                ),
                max_worker_calls=_env_int(
                    values,
                    "NEWS_RESEARCH_RAG_MAX_WORKER_CALLS",
                    16,
                    capability="research.rag.max_worker_calls",
                ),
            ),
            artifact=ResearchArtifactSettings(
                root=artifact_root,
                max_bytes=_env_int(
                    values,
                    "NEWS_RESEARCH_ARTIFACT_MAX_BYTES",
                    16_777_216,
                    capability="research.storage.artifact_max_bytes",
                ),
            ),
            run_store=ResearchRunStoreSettings(
                root=run_store_root,
                max_record_bytes=_env_int(
                    values,
                    "NEWS_RESEARCH_RUN_RECORD_MAX_BYTES",
                    16_777_216,
                    capability="research.storage.run_record_max_bytes",
                ),
                write_schema_version=_first_text(
                    values,
                    ("NEWS_RESEARCH_RUN_WRITE_SCHEMA_VERSION",),
                    "v2",
                ),
                supported_schema_versions=_research_run_schema_versions_from_text(
                    _first_text(
                        values,
                        ("NEWS_RESEARCH_RUN_SUPPORTED_SCHEMA_VERSIONS",),
                        "v1,v2",
                    ),
                    "research.storage.run_store",
                ),
                rollback_schema_versions=_research_run_schema_versions_from_text(
                    _first_text(
                        values,
                        ("NEWS_RESEARCH_RUN_ROLLBACK_SCHEMA_VERSIONS",),
                        "v1,v2",
                    ),
                    "research.storage.run_store",
                ),
                reconciliation_max_runs=_env_int(
                    values,
                    "NEWS_RESEARCH_RUN_RECONCILIATION_MAX_RUNS",
                    100,
                    capability="research.storage.run_store",
                ),
            ),
        )
        if not _secret_is_present(values, settings.llm.api_key_env):
            raise ResearchRuntimeUnavailableError(
                ("research.llm.credential",),
                remediation=ResearchRemediation.CONFIGURE_LLM_CREDENTIAL,
                retryable=False,
            )
        return settings


def _base_path(value: str | os.PathLike[str] | None) -> Path:
    try:
        if value is None:
            raw = Path.cwd()
        else:
            raw_value = os.fspath(value)
            if "\x00" in raw_value:
                _invalid("research.storage.root")
            raw = Path(raw_value)
        return raw.expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        _invalid("research.storage.root")


def _root_from_env(
    values: Mapping[str, str],
    names: tuple[str, ...],
    default: Path,
    *,
    base: Path,
    capability: str,
) -> Path:
    raw = _first_text(values, names, os.fspath(default))
    if "\x00" in raw:
        _invalid(capability)
    try:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = base / path
        path = path.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        _invalid(capability)
    _directory_root(path, capability)
    return path


def _directory_root(path: Path, capability: str) -> None:
    if not isinstance(path, Path) or not path.is_absolute():
        _invalid(capability)
    if path == Path(path.anchor):
        _invalid(capability)
    try:
        if path.exists() and not path.is_dir():
            _invalid(capability)
        ancestor = path
        while not ancestor.exists() and ancestor.parent != ancestor:
            ancestor = ancestor.parent
        if ancestor.exists() and not ancestor.is_dir():
            _invalid(capability)
    except OSError:
        _invalid(capability)


def _first_text(
    values: Mapping[str, str],
    names: tuple[str, ...],
    default: str,
) -> str:
    for name in names:
        value = values.get(name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _env_int(
    values: Mapping[str, str],
    name: str,
    default: int,
    *,
    capability: str,
) -> int:
    raw = values.get(name)
    if raw is None or not str(raw).strip():
        return default
    text = str(raw).strip()
    if len(text) > 16 or re.fullmatch(r"[+-]?\d+", text) is None:
        _invalid(capability)
    try:
        return int(text)
    except ValueError:
        _invalid(capability)


def _env_int_from_names(
    values: Mapping[str, str],
    names: tuple[str, ...],
    default: int,
    *,
    capability: str,
) -> int:
    for name in names:
        raw = values.get(name)
        if raw is not None and str(raw).strip():
            return _env_int(values, name, default, capability=capability)
    return default


def _env_float(
    values: Mapping[str, str],
    name: str,
    default: float,
    *,
    capability: str,
) -> float:
    raw = values.get(name)
    if raw is None or not str(raw).strip():
        return default
    text = str(raw).strip()
    if len(text) > 32:
        _invalid(capability)
    try:
        value = float(text)
    except ValueError:
        _invalid(capability)
    if not math.isfinite(value):
        _invalid(capability)
    return value


def _env_bool(
    values: Mapping[str, str],
    name: str,
    default: bool,
    *,
    capability: str,
) -> bool:
    raw = values.get(name)
    if raw is None or not str(raw).strip():
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    _invalid(capability)


def _parser_backends(value: str) -> tuple[str, ...]:
    if len(value) > 256:
        _invalid("research.parser.backends")
    return tuple(part.strip().lower() for part in value.split(",") if part.strip())


def _research_run_schema_version(value: str, capability: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _RESEARCH_RUN_SCHEMA_VERSIONS:
        _invalid(capability)
    return normalized


def _research_run_schema_versions(
    value: tuple[str, ...],
    capability: str,
) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        _invalid(capability)
    normalized = tuple(
        _research_run_schema_version(item, capability)
        for item in value
    )
    if len(normalized) != len(set(normalized)):
        _invalid(capability)
    return normalized


def _research_run_schema_versions_from_text(
    value: str,
    capability: str,
) -> tuple[str, ...]:
    if len(value) > 64:
        _invalid(capability)
    return _research_run_schema_versions(
        tuple(part.strip() for part in value.split(",") if part.strip()),
        capability,
    )


def _identifier(value: str, capability: str, *, max_length: int) -> str:
    normalized = str(value or "").strip()
    if len(normalized) > max_length or _IDENTIFIER.fullmatch(normalized) is None:
        _invalid(capability)
    return normalized.lower() if capability.endswith("provider") else normalized


def _http_url(value: str | None, capability: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 2_048 or any(char.isspace() for char in text):
        _invalid(capability)
    try:
        parsed = urlsplit(text)
        _ = parsed.port
    except ValueError:
        _invalid(capability)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        _invalid(capability)
    normalized = urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc,
            parsed.path.rstrip("/"),
            "",
            "",
        )
    )
    return normalized


def _secret_is_present(values: Mapping[str, str], name: str) -> bool:
    value = values.get(name)
    return isinstance(value, str) and any(not char.isspace() for char in value)


def _default_api_key_env(values: Mapping[str, str]) -> str:
    if _secret_is_present(values, "DASHSCOPE_API_KEY"):
        return "DASHSCOPE_API_KEY"
    if _secret_is_present(values, "OPENAI_API_KEY"):
        return "OPENAI_API_KEY"
    return "DASHSCOPE_API_KEY"


def _bounded_int(value: int, capability: str, minimum: int, maximum: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        _invalid(capability)


def _bounded_float(value: float, capability: str, minimum: float, maximum: float) -> None:
    if isinstance(value, bool):
        _invalid(capability)
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        _invalid(capability)
    if not math.isfinite(numeric) or not minimum <= numeric <= maximum:
        _invalid(capability)


def _invalid(capability: str) -> NoReturn:
    raise ResearchConfigurationError((capability,)) from None


__all__ = [
    "ResearchArtifactSettings",
    "ResearchLLMSettings",
    "ResearchParserSettings",
    "ResearchRAGSettings",
    "ResearchRunStoreSettings",
    "ResearchRuntimeSettings",
    "ResearchSourceSettings",
]
