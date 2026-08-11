from __future__ import annotations

from dataclasses import replace

from framework.llm.cache.in_memory import InMemoryLLMCache
from framework.llm.cache.key import LLMCacheKey
from framework.llm.cache.policy import LLMCachePolicy
from framework.llm.models import LLMClient
from framework.llm.models.request import LLMRequest
from framework.llm.models.response import LLMResponse


class CachedLLMClient:
    """Development/test compatibility cache.

    Production cache orchestration belongs to ``LLMRouter`` so hits can precede
    cooldown and provider-budget admission.
    """

    def __init__(
        self,
        client: LLMClient,
        *,
        provider: str,
        model: str,
        policy: LLMCachePolicy,
        cache: InMemoryLLMCache | None = None,
    ) -> None:
        self._client = client
        self._provider = provider
        self._model = model
        self._policy = policy
        self._cache = cache or InMemoryLLMCache()

    def complete(self, request: LLMRequest) -> LLMResponse:
        if not self._policy.allows(request):
            return self._mark_cache_metadata(self._client.complete(request), cacheable=False, hit=False)

        cache_key = LLMCacheKey.from_request(provider=self._provider, model=self._model, request=request)
        cached_response = self._cache.get(cache_key, ttl_seconds=self._policy.ttl_seconds)
        if cached_response is not None:
            return self._mark_cache_metadata(
                cached_response,
                cacheable=True,
                hit=True,
                budget_cost_counted=False,
                budget_request_counted=True,
            )

        response = self._client.complete(request)
        response = self._mark_cache_metadata(
            response,
            cacheable=True,
            hit=False,
            budget_cost_counted=True,
            budget_request_counted=True,
        )
        self._cache.set(cache_key, response)
        return response

    def _mark_cache_metadata(
        self,
        response: LLMResponse,
        *,
        cacheable: bool,
        hit: bool,
        budget_cost_counted: bool | None = None,
        budget_request_counted: bool = True,
    ) -> LLMResponse:
        metadata = dict(response.metadata)
        metadata.update(
            {
                "llm_cacheable": cacheable,
                "llm_cache_hit": hit,
                "llm_budget_cost_counted": (
                    (not hit) if budget_cost_counted is None else budget_cost_counted
                ),
                "llm_budget_request_counted": budget_request_counted,
            }
        )
        return replace(response, metadata=metadata)
