from __future__ import annotations

from io import BytesIO
import json
from urllib.error import HTTPError, URLError

import pytest

from scripts import probe_prompt_cache as probe


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        (
            "https://llm.example/v1",
            "https://llm.example/v1/chat/completions",
        ),
        (
            "https://llm.example/v1/",
            "https://llm.example/v1/chat/completions",
        ),
        (
            "https://llm.example/v1/chat/completions/",
            "https://llm.example/v1/chat/completions",
        ),
    ],
)
def test_normalize_chat_completions_url(base_url: str, expected: str) -> None:
    assert probe.normalize_chat_completions_url(base_url) == expected


@pytest.mark.parametrize(
    "base_url",
    [
        "llm.example/v1",
        "ftp://llm.example/v1",
        "https://user:password@llm.example/v1",
        "https://llm.example/v1?api_key=secret",
        "https://llm.example/v1#fragment",
        "https://llm.example/v1/responses",
        "https://llm.example:99999/v1",
    ],
)
def test_normalize_chat_completions_url_rejects_unsafe_values(
    base_url: str,
) -> None:
    with pytest.raises(probe.ProbeConfigurationError):
        probe.normalize_chat_completions_url(base_url)


def test_config_from_env_requires_all_values_and_does_not_expose_key() -> None:
    with pytest.raises(probe.ProbeConfigurationError, match="OPENAI_API_KEY"):
        probe.ProbeConfig.from_env(
            {
                "OPENAI_BASE_URL": "https://llm.example/v1",
                "OPENAI_MODEL": "model-a",
                "OPENAI_API_KEY": "  ",
            }
        )

    config = probe.ProbeConfig.from_env(
        {
            "OPENAI_BASE_URL": " https://llm.example/v1/ ",
            "OPENAI_MODEL": " model-a ",
            "OPENAI_API_KEY": " secret-key ",
        }
    )
    assert config.endpoint == "https://llm.example/v1/chat/completions"
    assert config.model == "model-a"
    assert repr(config) == (
        "ProbeConfig(endpoint='https://llm.example/v1/chat/completions', "
        "model='model-a')"
    )
    assert config.api_key == "secret-key"


@pytest.mark.parametrize(
    ("usage", "expected_field"),
    [
        (
            {
                "prompt_tokens": 2000,
                "completion_tokens": 4,
                "prompt_tokens_details": {"cached_tokens": 1536},
            },
            "usage.prompt_tokens_details.cached_tokens",
        ),
        (
            {
                "input_tokens": 2000,
                "output_tokens": 4,
                "input_tokens_details": {"cached_tokens": "1024"},
            },
            "usage.input_tokens_details.cached_tokens",
        ),
        (
            {"prompt_cache_hit_tokens": 999},
            "usage.prompt_cache_hit_tokens",
        ),
        (
            {"cache_read_input_tokens": 800},
            "usage.cache_read_input_tokens",
        ),
    ],
)
def test_extract_cache_observation_supports_provider_shapes(
    usage: dict[str, object],
    expected_field: str,
) -> None:
    observation = probe.extract_cache_observation({"usage": usage})

    assert observation.cached_tokens is not None
    assert observation.cached_tokens > 0
    assert observation.cache_field == expected_field


def test_extract_cache_observation_ignores_invalid_counts_and_missing_usage() -> None:
    negative = probe.extract_cache_observation(
        {
            "usage": {
                "prompt_tokens": "not-a-number",
                "prompt_tokens_details": {"cached_tokens": -1},
                "cached_tokens": True,
            }
        }
    )
    missing = probe.extract_cache_observation({})

    assert negative == probe.CacheObservation(None, None, None, None)
    assert missing == probe.CacheObservation(None, None, None, None)


def test_extract_cache_observation_marks_conflicting_provider_fields() -> None:
    observation = probe.extract_cache_observation(
        {
            "usage": {
                "prompt_tokens_details": {"cached_tokens": 0},
                "cached_tokens": 1200,
            }
        }
    )

    assert observation.cached_tokens == 0
    assert observation.cache_field == "usage.prompt_tokens_details.cached_tokens"
    assert observation.cache_conflict is True


@pytest.mark.parametrize(
    ("cached_values", "expected_status", "expected_code"),
    [
        ([0, 1200, 1400], "hit", 0),
        ([1200, 0, 0], "warm_hit_on_first_request", 0),
        ([0, 0, 0], "miss", 2),
        ([None, None, None], "not_reported", 3),
    ],
)
def test_classify_observations_has_explicit_unknown_state(
    cached_values: list[int | None],
    expected_status: str,
    expected_code: int,
) -> None:
    observations = tuple(
        probe.CacheObservation(
            2000,
            4,
            value,
            "usage.cached_tokens" if value is not None else None,
        )
        for value in cached_values
    )
    assert probe.classify_observations(observations) == (
        expected_status,
        expected_code,
    )


def test_run_probe_keeps_prefix_constant_changes_only_suffix_and_hides_key() -> None:
    requests: list[tuple[str, dict, str, float]] = []
    output: list[str] = []

    def sender(endpoint: str, payload: dict, api_key: str, timeout: float) -> dict:
        requests.append((endpoint, payload, api_key, timeout))
        return {
            "usage": {
                "prompt_tokens": 1700,
                "completion_tokens": 2,
                "prompt_tokens_details": {
                    "cached_tokens": 0 if len(requests) == 1 else 1500
                },
            }
        }

    config = probe.ProbeConfig(
        endpoint="https://llm.example/v1/chat/completions",
        model="model-a",
        api_key="secret-key",
    )
    result = probe.run_probe(
        config,
        probe.ProbeOptions(
            requests=3,
            delay_seconds=0,
            prefix_words=1024,
            max_tokens=8,
            timeout_seconds=12,
        ),
        sender=sender,
        sleeper=lambda _: pytest.fail("sleep should not be called"),
        emit=output.append,
        session_id="test-session",
    )

    assert result.status == "hit"
    assert result.exit_code == 0
    assert len(requests) == 3
    assert {item[0] for item in requests} == {
        "https://llm.example/v1/chat/completions"
    }
    assert {item[2] for item in requests} == {"secret-key"}
    payloads = [item[1] for item in requests]
    assert [payload["messages"][0] for payload in payloads].count(
        payloads[0]["messages"][0]
    ) == 3
    assert len({payload["messages"][1]["content"] for payload in payloads}) == 3
    assert "secret-key" not in "\n".join(output)
    assert "RESULT=HIT" in output


def test_run_probe_redacts_a_key_embedded_in_display_values() -> None:
    output: list[str] = []
    secret = "secret-key"

    result = probe.run_probe(
        probe.ProbeConfig(
            endpoint=f"https://llm.example/{secret}/v1/chat/completions",
            model=f"model-{secret}",
            api_key=secret,
        ),
        probe.ProbeOptions(requests=2, delay_seconds=0, prefix_words=1),
        sender=lambda endpoint, payload, api_key, timeout: {
            "usage": {"cached_tokens": 1}
        },
        emit=output.append,
        session_id="test-session",
    )

    assert result.exit_code == 0
    assert secret not in "\n".join(output)


def test_main_returns_probe_result_code_with_injected_sender() -> None:
    def sender(endpoint: str, payload: dict, api_key: str, timeout: float) -> dict:
        return {"usage": {"prompt_tokens": 10, "cached_tokens": 0}}

    code = probe.main(
        ["--requests", "2", "--delay-seconds", "0", "--prefix-words", "1"],
        {
            "OPENAI_BASE_URL": "https://llm.example/v1",
            "OPENAI_MODEL": "model-a",
            "OPENAI_API_KEY": "secret-key",
        },
        sender=sender,
    )
    assert code == 2


def test_safe_provider_error_extracts_only_bounded_safe_fields() -> None:
    secret = "secret-key"
    error = HTTPError(
        "https://llm.example/v1/chat/completions",
        401,
        "Unauthorized",
        hdrs=None,
        fp=BytesIO(
            json.dumps(
                {
                    "error": {
                        "code": "invalid_api_key",
                        "message": f"bad credential {secret}",
                        "details": "do not retain this body",
                    }
                }
            ).encode("utf-8")
        ),
    )

    summary = probe._safe_provider_error(error, secret)

    assert "invalid_api_key" in summary
    assert secret not in summary
    assert "do not retain" not in summary


def test_post_json_maps_network_errors_without_echoing_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "secret-key"

    def fail(*args: object, **kwargs: object) -> object:
        raise URLError(f"connection failed for {secret}")

    monkeypatch.setattr(probe, "urlopen", fail)
    with pytest.raises(probe.ProbeRequestError) as raised:
        probe.post_json(
            "https://llm.example/v1/chat/completions",
            {"model": "model-a"},
            secret,
            1,
        )

    assert secret not in str(raised.value)
    assert "Network error" in str(raised.value)


def test_post_json_sends_only_expected_headers_and_decodes_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, limit: int) -> bytes:
            captured["limit"] = limit
            return b'{"usage":{"prompt_tokens":12,"cached_tokens":4}}'

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(probe, "urlopen", fake_urlopen)
    response = probe.post_json(
        "https://llm.example/v1/chat/completions",
        {"model": "model-a", "messages": []},
        "secret-key",
        7.5,
    )

    request = captured["request"]
    assert isinstance(request, probe.Request)
    assert request.get_header("Authorization") == "Bearer secret-key"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data.decode("utf-8")) == {
        "model": "model-a",
        "messages": [],
    }
    assert captured["timeout"] == 7.5
    assert response.status_code == 200
    assert response.payload["usage"]["cached_tokens"] == 4


def test_normalize_transport_response_rejects_success_error_payload() -> None:
    with pytest.raises(probe.ProbeRequestError, match="Provider returned an error"):
        probe._normalize_transport_response(
            probe.TransportResponse(
                {"error": {"code": "invalid_request"}, "choices": []}
            )
        )


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (probe.TransportResponse({}, 500), "HTTP 500"),
        (probe.TransportResponse({"usage": []}), "usage must be an object"),
        (probe.TransportResponse({"choices": {}}), "choices must be an array"),
        (
            probe.TransportResponse({"message": "not a completion"}),
            "lacked usage or choices",
        ),
    ],
)
def test_normalize_transport_response_rejects_bad_provider_shapes(
    response: probe.TransportResponse,
    message: str,
) -> None:
    with pytest.raises(probe.ProbeRequestError, match=message):
        probe._normalize_transport_response(response)
