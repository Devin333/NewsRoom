# 阶段 23：LLM Response Cache 生产化硬化 PRD

> Document status: FINAL
>
> Implementation status: IMPLEMENTED
>
> Version: v1.0
>
> Priority: P1（成本、路由正确性、租户隔离与流式可靠性）
>
> Scope: `framework/llm/cache`、`framework/llm/routing`、LLM composition、Redis cache adapter、相关配置、事件与测试
>
> Proposed OpenSpec change: `llm-cache-production-hardening`
>
> Last updated: 2026-08-11

## 0. 一句话结论

NewsRoom 需要的是**精确请求 -> 完整 `LLMResponse`**的受控响应缓存，而不是语义相似缓存、prompt/prefix cache 或业务事实存储。缓存只能复用确定性且经过 allowlist 授权的结果；`LLM` 仍然只是生成候选的 worker，`Harness/LLMRouter` 仍然拥有 routing、budget、cooldown、tool authorization、durable event 和 publication 的控制权。

当前实现只完成了开发期的 `InMemoryLLMCache + CachedLLMClient.complete()`。本阶段要把它收敛为可注入的 cache port，并在 router 的 deployment 尝试边界完成 cache lookup，再接入隔离的 Redis backend、bounded single-flight、完整流式响应回放、预算/观测语义和 fail-open 运行策略。

## 1. 当前基线与已确认缺口

### 1.1 当前代码路径

| 组件 | 当前事实 | 证据 |
| --- | --- | --- |
| Cache policy | 只检查 `enabled`、`metadata.task_type` 和 `no_cache_agent_ids`，默认关闭 | `framework/llm/cache/policy.py` |
| Cache key | 对 `provider`、`model`、完整 `LLMRequest.to_dict(redact=False)` 做 JSON + SHA-256；没有 namespace、scope、deployment revision 或 key secret | `framework/llm/cache/key.py` |
| Cache store | `dict[str, _CacheEntry]`，使用 wall clock TTL 和 `deepcopy`，无容量上限、无跨进程共享、无并发协调 | `framework/llm/cache/in_memory.py` |
| Client wrapper | `CachedLLMClient` 的构造参数固定为 `InMemoryLLMCache`，只实现 `complete()`，命中后通过 metadata 标记预算字段 | `framework/llm/cache/cached_client.py` |
| LLM model | `LLMClient` 同时声明 `complete()` 与 `stream()`；`LLMResponse`、`LLMStreamEvent` 和 `LLMStreamAccumulator` 已有可复用的归一化模型 | `framework/llm/models/client.py`、`response.py`、`stream.py` |
| Router | 每个 deployment 先检查 enabled/cooldown/capabilities，再调用 global budget preflight，最后调用 `deployment.client.complete()`；cache wrapper 在 client 内时无法绕过前置检查 | `framework/llm/routing/router.py:121-464` |
| Redis runtime | 已有 `RedisRuntimeStore`、`NEWS_REDIS_URL` 和 optional `redis` 依赖，但该 store 服务 runtime pointer/lock，不是可任意淘汰的 LLM cache | `infrastructure/storage/redis_runtime.py` |
| Composition | 生产代码目前没有统一的 cache-enabled LLM route composition；缓存只在测试中显式构造 | `tests/framework/llm/test_clients_cache_prompt_redaction.py` |

### 1.2 生产缺口

1. **缓存层级错误**：cache hit 发生在 router 的 cooldown 和预算预占之后，provider cooldown 时无法复用已有结果，命中还会被误算成一次 provider 调用。
2. **职责耦合**：framework 依赖具体的 `InMemoryLLMCache`，没有允许 Redis、测试 fake 和未来其他 backend 的稳定 port。
3. **数据边界不足**：key 没有租户/项目 scope、deployment identity、schema/prompt revision；也没有防止 key 暴露原始输入的 HMAC 约束。
4. **资格判断不足**：当前 policy 不拒绝工具、实时任务、非零或未知 temperature、动态 evidence revision、过大的响应和不完整的输出。
5. **生命周期不足**：Redis key 没有强制 TTL、entry size 上限、版本失效策略或专用 eviction boundary；不能把 Redis persistence 当作 durable workflow state。
6. **并发不足**：没有跨 worker single-flight；相同 miss 会击穿 provider，也没有 owner-token 原子释放锁的契约。
7. **流式缺口**：没有 `stream()` cache；如果缓存 provider chunk，容易保存半截、绑定 provider 分片格式，或者回放旧 tool call。
8. **审计不足**：没有 cache lookup/hit/miss/write/bypass/error 的 router event、指标和不泄露 prompt 的诊断字段。

### 1.3 不可回退的架构护栏

- 保留 `source collection -> evidence -> agent analysis -> report -> quality gate -> artifacts/storage` 主路径。
- `LLM` 只产生候选文本、结构化输出或 tool-call 候选；不得决定 cache eligibility、routing、budget pass/fail、tool authorization、memory write 或 publication。
- Harness 仍执行有界 `PLAN -> EXECUTE -> VERIFY`；cache hit 只改变 provider side effect，不跳过本次 Harness 的 deterministic gate、durable transcript 或最终 artifact integrity gate。
- `Redis` cache 丢失、淘汰、短暂不可用或 payload 损坏只能导致 miss/bypass；不能成为 workflow state、evidence、memory、report 或 artifact 的唯一来源。
- `business/research` 不得反向依赖 legacy `business/boards/paper_radar`、`interfaces` 或 `infrastructure`；cache port 属于 framework，adapter 由 composition/infrastructure 注入。

## 2. 目标与非目标

### 2.1 目标

| ID | 目标 |
| --- | --- |
| G1 | 对明确 allowlist 的确定性任务提供 exact response cache；默认关闭，按 route/task/agent 显式开启。 |
| G2 | cache lookup 位于每个 deployment 的 cooldown 与 provider budget admission 之前；命中不调用 provider、不消耗 provider cost/token budget。 |
| G3 | 通过稳定、版本化、scope-bound、不可从 key 反推出 prompt 的 key 生成规则避免误命中和跨租户读取。 |
| G4 | 以完整、验证通过的 `LLMResponse` 作为唯一缓存粒度；流式请求只在正常收到 `message_complete` 后写入。 |
| G5 | 为多 worker 提供专用 Redis backend、TTL、容量上限、原子 single-flight 和可观测的故障降级。 |
| G6 | 保留每次 logical LLM request 的 durable routing/cache event，使命中、绕过、provider call 和 replay 可回放、可审查。 |
| G7 | 提供 disabled/observe/write-only/read-write 分阶段发布、版本 bump 和一键回滚路径。 |

### 2.2 非目标

- 不实现语义相似、embedding、fuzzy 或跨 prompt 的 cache。
- 不实现 vLLM prefix/prompt cache；provider 内部 token cache 不等于 NewsRoom response cache。
- 不缓存带 `tools` 的请求或任何会产生副作用的 tool-call 候选；本阶段不为 tool-call replay 建立授权协议。
- 不把 Redis/AOF/RDB 当作 durable transcript、TaskPlan、memory、evidence、report 或 artifact store。
- 不在普通 business run 中写 active skill；cache 命中不触发 memory consolidation 或 skill evolution。
- 不引入 UI、运营控制台或长期缓存审计数据库；只提供 framework port、adapter、配置和事件/指标。
- 不同时引入进程内 L1 + Redis L2；第一版先验证单一共享 backend 的正确性。

## 3. 用户、场景与结果

### 3.1 目标角色

| 角色 | 需要的结果 |
| --- | --- |
| Harness maintainer | 能证明 cache 只影响 provider side effect，不改变 workflow routing、quality gate 和 publication。 |
| Workflow/Research author | 能声明任务是否允许 exact reuse，并提供 evidence/prompt/deployment revision。 |
| LLM route owner | 能在 primary cooldown 或 global provider budget 紧张时复用已经批准的结果，同时保持 fallback 语义正确。 |
| Security/operator | 能确认租户隔离、密钥/响应不泄露、Redis 淘汰不会删除 runtime state，并能观测故障。 |
| Reviewer | 能从 durable event 和 metadata 区分 cache hit、provider call、fallback、bypass 与 backend failure。 |

### 3.2 核心场景

1. **确定性抽取命中**：同一 `source_version`、同一 prompt revision、同一 deployment 和 `temperature=0` 的结构化抽取，第二次请求直接返回上次已验证的 `LLMResponse`。
2. **provider cooldown 命中**：primary deployment 处于 cooldown，但该 deployment 的 exact cache 有效；router 在 cooldown 检查前命中并返回，不访问 provider，也不切换到 fallback。
3. **fallback 隔离**：primary miss 后失败，fallback 成功；fallback 结果只能以 fallback deployment identity 写入，不能污染 primary 的缓存命名空间。
4. **跨 worker 共享**：两个进程使用同一专用 Redis，第二个进程可以读取第一个进程写入的完整 response；Redis 重启后缓存丢失只造成 miss。
5. **并发击穿抑制**：多个 worker 同时 miss 时，只有获得 single-flight lease 的 worker 调 provider；其他 worker 在有界等待后复读，超时才按明确策略 bypass。
6. **流式完整回放**：首次 `stream()` 正常结束后缓存完整 response；命中时生成协议合法的 `message_start -> text_delta* -> usage_delta? -> message_complete` 事件序列，分片边界不承诺与 provider 相同。
7. **故障降级**：Redis timeout、序列化失败、MAC 校验失败或过期都只记录结构化 bypass/error 并继续真实 provider 路径；不会返回不可信的旧值。

## 4. 不变量与验收原则

以下不变量必须由 deterministic code 和测试保证，不能交给 LLM 判断：

1. 相同 canonical request、相同 cache scope、相同 deployment identity 和相同 cache version 才可能命中；任何一项变化都必须 miss。
2. 不同 tenant/project/security scope 永远不能读取同一个 cache entry。
3. cache hit 不得调用 provider，不得更新 provider cooldown success/failure，不得消耗 provider token/cost budget。
4. cache hit 仍算一次 logical request，并产生当前调用的 route/cache event；不得跳过 Harness 的后续 VERIFY 或 durable transcript。
5. 未通过 eligibility、cache backend error、entry 过期、schema 不兼容、MAC 不匹配、entry 过大或 response 不完整时不得 replay。
6. 只有收到完整且由 cache write owner 重新执行 deterministic output-contract validation 的 `LLMResponse`（同步返回，或流中唯一的 `message_complete` 之后）才允许写入；不能只相信 client metadata 声称“已验证”。
7. 任何 `tool_calls`、`request.tools`、外部副作用候选、实时/时效性 task 或未声明 dependency revision 的请求都不得进入缓存。
8. cache lock 的获得、续租和释放必须有 owner token；释放只能原子地删除自己的 lock，旧 worker 不得删除新 owner 的 lock。
9. Redis eviction、RDB/AOF 恢复和 cache namespace 不能影响 durable runtime、event、artifact 或业务事实。
10. cache key、响应 raw payload、prompt、tool arguments、tenant 原文和 secret 不得写入普通日志、指标 label 或 durable event。

## 5. 目标架构

### 5.1 控制流

```text
Harness / AgentLoop
        |
        v
LLMRouter.resolve route + deployment identity
        |
        +--> deterministic CachePolicy.eligibility
        |         |
        |         +--> rejected: record bypass -> cooldown/budget -> provider
        |         |
        |         +--> eligible: exact lookup (before cooldown/budget)
        |                    |
        |                    +--> valid hit: decorate response/events -> return
        |                    |
        |                    +--> miss: bounded single-flight admission
        |                               |
        |                               +--> recheck hit -> return
        |                               +--> owner: cooldown/budget -> provider
        |                                              |
        |                                              +--> complete + validate
        |                                              +--> budget/gate pass
        |                                              +--> encode + bounded write
        |                                              +--> return provider response
        |
        +--> durable router/cache events -> existing event/transcript projection
```

Cache is an optimization service under router control. It is not a second router, an agent memory, or an authorization layer.

### 5.2 模块所有权

| 层 | 负责 | 禁止 |
| --- | --- | --- |
| `framework/llm/cache` | `CacheKey`、eligibility contract、entry schema、store/coordinator protocols、in-memory test backend | 导入 Redis client、读取环境变量、决定 workflow route 或 provider fallback |
| `framework/llm/routing` | 在 deployment loop 中调用 cache port；决定 hit 是否绕过 cooldown/budget；生成 routing/cache metadata 与 events | 直接序列化 Redis、执行 tool、让 LLM 决定 cache policy |
| `infrastructure/storage` | Redis connection、专用 key prefix、TTL、原子 lock、codec/encryption adapter | 存 durable business facts；自行决定是否 replay |
| `interfaces/composition` | 读取配置、组装 `LLMRouter` 和 cache adapter、注入 tenant/project scope | 在 endpoint 中直接调用 Redis 或 executor |
| `Harness` | workflow phase、retry/replan/halt、VERIFY、transcript 与 publication | 把 cache hit 当作 quality pass，或允许旧 tool call 执行 |

### 5.3 具体落点建议

实现可以按现有命名微调，但必须保留以下职责边界：

```text
framework/llm/cache/contracts.py       # ports、CacheLookup、CacheWriteResult、lease contract
framework/llm/cache/key.py             # versioned canonical key / HMAC digest
framework/llm/cache/policy.py          # deterministic eligibility 与 reason codes
framework/llm/cache/entry.py           # versioned response envelope
framework/llm/cache/in_memory.py       # bounded、thread-safe test/development store
framework/llm/routing/router.py        # route-aware lookup、budget/cooldown ordering、events
infrastructure/storage/redis_llm_cache.py # Redis store/coordinator/codec adapter
interfaces/composition/llm.py          # production wiring；名称可按现有 composition 结构调整
tests/framework/llm/...                # contract/router/stream tests
tests/infrastructure/storage/...        # Redis adapter and optional real Redis tests
```

`framework` 不得为了复用 `RedisRuntimeStore` 而反向 import `infrastructure`。`RedisRuntimeStore` 的连接工厂和 key validation 可以提炼为共享基础设施，但 LLM cache 必须有独立 adapter 和 cache-specific tests。

## 6. Domain contract

### 6.1 Cache scope

每次调用必须传入不可为空的 `CacheScope`，至少包含：

```text
tenant_id       # 租户边界
project_id      # 项目/工作区边界
policy_scope    # 可选的权限/数据可见性版本
```

缺少任何必需 scope 时，eligibility 返回 `missing_cache_scope` 并 bypass；不得使用全局默认 scope。scope 只用于 key HMAC 和诊断哈希，不写入 entry 明文。

### 6.2 Cache key

建议的逻辑模型：

```python
CacheKey(
    namespace="newsroom:llm-cache",
    key_version="v1",
    scope_digest="...",
    deployment_id="dashscope-deepseek-v4-flash",
    provider="dashscope",
    model="deepseek-v4-flash",
    cache_generation="prompt-2026-08-10",
    request_digest="...",
)
```

`request_digest` 的输入必须是 canonical payload，而不是 Python `repr`。canonical payload 至少包括：

- `LLMRequest.messages` 的 role、content 和多模态结构；
- `model`、`temperature`、`max_tokens`；
- 完整 tool schema（即使本阶段 policy 默认拒绝带 tool 的请求，也必须纳入 key，防止未来放开后碰撞）；
- `response_format`、`output_schema`、`output_schema_name`；
- 经 policy 标记为语义相关的稳定 metadata；
- `prompt_revision`、`evidence_revision`、`retrieval_snapshot_id` 等显式 dependency fingerprint；
- deployment/provider/cache generation。

字段排序、数值类型、Unicode、缺省值和列表顺序必须有版本化 canonicalization 规则。`None`、缺失和空字符串不能在未经定义的情况下互换。

外部 Redis key 不得包含原始 prompt、原始 tenant、完整 request JSON 或 secret。推荐格式：

```text
newsroom:llm-cache:v1:<scope_hmac_16>:<deployment_id_hash_16>:<request_hmac_64>
```

其中 HMAC key 来自专用 `NEWS_LLM_CACHE_KEY_SECRET`，并使用 domain separation（`scope`、`deployment`、`request` 三种 context 不复用裸 hash）。secret 轮换或 `key_version` 变更会自然失效旧缓存。

### 6.3 Cache entry

缓存值是版本化 envelope，而不是直接 dump `LLMResponse`：

```text
entry_schema_version
cache_key_version
created_at
source_deployment_id
source_provider
source_model
source_response_usage       # 仅作为结果来源信息，不等于本次 provider usage
response                    # content/structured_output/tool_calls(empty)/safe metadata
payload_mac / encrypted_payload
```

写入前必须删除或明确过滤：`LLMResponse.raw`、请求原文、API response headers、credential、内部 traceback、request-scoped run id 和可能导致跨调用误判的 routing event 列表。entry 必须可由 `LLMResponse.from_dict()` 重新构造，并在 schema/version/MAC 校验失败时视为 miss。

Cache write owner 必须依据当前 `LLMRequest.output_schema`、`response_format` 和 `output_schema_name` 调用 shared deterministic validator 复验结果。`OpenAICompatibleClient` 当前会在自己的 normalize 路径校验 structured output，但 `LLMClient` protocol、fake 或其他未来 adapter 不承诺已经执行同一验证，因此不得把 `metadata.structured_output_validation` 当成可信证明。文本/JSON/structured response 的验证结果必须由当前调用重新计算，验证失败按现有 provider/schema error contract 处理且不得写 cache。

Redis backend 强制设置有限 TTL；`ttl_seconds=None` 只允许测试内存 backend，不得进入 production composition。`max_entry_bytes` 超限时 bypass write 并记录 `entry_too_large`。

### 6.4 Store and coordinator ports

Framework port 至少提供：

```text
get(key) -> CacheEntry | CacheMiss | CacheCorrupt
put(key, entry, ttl_seconds) -> CacheWriteResult
delete(key) -> None
acquire_singleflight(key, owner_token, ttl_seconds) -> Lease | None
release_singleflight(lease) -> bool
```

`get` 必须区分 miss、expired、corrupt、backend_error，不能把所有异常静默成普通 hit。`release_singleflight` 必须是 owner-token compare-and-delete；不能先 `GET` 再无条件 `DEL`。

Store API 采用同步接口以匹配现有 `LLMClient`/router；adapter 内部不得偷偷启动无界线程或后台任务。所有等待都受调用方 deadline 和 `singleflight_wait_timeout_ms` 双重限制。

### 6.5 Cache response metadata

每次返回的 response 都要由 router 重新 decorate，至少包含：

```text
llm_cacheable: bool
llm_cache_hit: bool
llm_cache_source: "provider" | "cache" | "bypass"
llm_cache_reason: stable reason code
llm_cache_key_version: str
llm_cache_age_seconds: float | None
llm_provider_call: bool
llm_budget_cost_counted: bool
llm_budget_request_counted: bool
llm_cache_backend: str
```

不得直接复用缓存 entry 中上一次调用的 `llm_route_events`、`llm_call_id`、fallback 计数或 run id。

## 7. Eligibility policy

### 7.1 默认规则

默认 `disabled`。即使 `task_type` 在 allowlist 中，也必须同时满足：

| 条件 | 默认要求 | 不满足时 reason code |
| --- | --- | --- |
| policy enabled/mode | `read_write` 或明确的 `observe`/`write_only` | `cache_disabled` |
| task type | 在显式 allowlist | `task_type_not_allowlisted` |
| agent | 不在 denylist；live/research agent 默认 deny | `agent_not_cacheable` |
| cache scope | tenant/project/policy scope 完整 | `missing_cache_scope` |
| temperature | 明确为 `0`，除非 task policy 提供 deterministic seed contract | `nondeterministic_temperature` |
| tools | `request.tools` 为空；任何 tool-call 候选都拒绝 | `tool_capability_present` |
| freshness | 不是 latest/live/current-time 或动态对话任务 | `freshness_sensitive_task` |
| dependency | prompt/evidence/retrieval revision 已提供且稳定 | `missing_dependency_revision` |
| output | response format/schema 可归一化；不含未验证结构 | `unsupported_output_contract` |
| size | encoded entry 不超过 `max_entry_bytes` | `entry_too_large` |

`metadata.task_type` 仅作为 route policy 输入，不得单独授权缓存。生产 policy 必须能够区分 `cache_mode`、`cache_dependencies` 和 `data_visibility_scope`。

### 7.2 metadata 与 dependency fingerprint

当前 `LLMCacheKey` 把全部 `request.metadata` 放入 digest，虽然保守但会把 run-specific 字段造成大量 false miss。阶段 23 不允许通过“随意删除 metadata 字段”提升命中率。必须建立显式分类：

- **semantic fields**：会改变回答的字段，必须进入 canonical payload；例如 `prompt_revision`、`evidence_revision`、`retrieval_snapshot_id`、语言、输出 schema version。
- **request-scoped diagnostic fields**：只用于观测，不进入 key；例如 `run_id`、`llm_call_id`、trace/span id。
- **security fields**：作用域必须进入 key，但原文只做 HMAC；例如 tenant/project/permission snapshot。
- **unknown fields**：默认按 semantic 处理并导致 miss，不能静默丢弃。

分类器本身需要 `cache_key_version`；分类规则变化必须 bump version。任何由 agent 自己生成的“可以忽略 metadata”意见都不是授权。

### 7.3 Tool 与副作用边界

本阶段凡是 `request.tools` 非空、`response.tool_calls` 非空、或 task policy 标记为 `side_effect_candidate`，都不得写入或 replay。即使工具 schema 和参数看起来相同，也不能把旧 tool call 当成当前授权决定。普通文本回答可以缓存，但只要同一请求携带工具说明，就按不缓存处理。

## 8. Router、cooldown 与 budget 语义

### 8.1 必须调整的顺序

对 deployment chain 中的每个候选，顺序必须是：

```text
1. deployment enabled/capability deterministic validation
2. cache eligibility + exact lookup
3. valid cache hit -> record logical request + return
4. miss/coordinator admission + bounded recheck
5. active cooldown check
6. global provider budget reserve
7. provider complete/stream
8. shared deterministic response/output-schema validation and route budget check
9. global provider budget settlement
10. cache write (only after all gates pass)
11. durable success event and return
```

`deployment in cooldown` 不得阻止该 deployment 的有效 cache hit。只有 miss 才进入 cooldown/fallback。enabled/capability 检查仍在 cache lookup 前执行，防止已禁用 deployment 的结果被继续消费；如果产品需要紧急撤销某 deployment 的所有缓存，使用 `cache_generation` bump/invalidation，而不是绕过 enabled gate。

### 8.2 Fallback identity

每个 cache entry 必须绑定 `deployment_id` 和 `cache_generation`：

- primary miss + provider failure + fallback success：只写 fallback identity；
- 下次 primary 可用时，只查 primary identity；不会把 fallback response 当成 primary response；
- primary cooldown 时，router 可以查 primary entry；命中则不走 fallback；
- fallback deployment 自己被选中时，才查其 entry；
- route policy、deployment model/provider、prompt revision 变化必须产生新 identity 或新 key version。

### 8.3 Budget accounting

现有 `GlobalBudgetTracker` 的 provider cost/token budget 必须改为区分两类计数：

| 事件 | logical request | provider `llm_calls` | provider token/cost | cooldown success/failure |
| --- | ---: | ---: | ---: | ---: |
| cache hit | +1 | +0 | +0 | 不更新 |
| cache miss + provider success | +1 | +1 | 按真实 usage 结算 | success |
| cache miss + provider failure | +1 | +1（若已实际发起） | 按现有失败计费策略 | failure（按 retryability） |
| eligibility bypass | +1 | 按真实 provider 路径 | 按真实 usage | 按真实 provider 路径 |
| Redis unavailable | +1 | 按 bypass 后真实路径 | 按真实 usage | 按真实 provider 路径 |

`max_llm_calls` 的兼容语义继续限制实际 provider call；如需限制 logical request，新增独立的 `max_logical_llm_requests`，不得把 cache hit 偷换成 provider call。`LLMCallTrace` 和 route event 要同时记录 `cache_hit`、`provider_call` 与两类 usage，避免旧字段误导成本分析。

## 9. Streaming contract

### 9.1 Miss path

`stream()` miss 的处理必须是：

```text
source stream
  -> normalize to LLMStreamEvent
  -> yield each event to caller
  -> LLMStreamAccumulator.add_event(event)
  -> observe exactly one valid message_complete
  -> accumulator.to_response()
  -> deterministic output-contract + route/local/global gates pass
  -> cache complete response
```

必须处理以下情况：

- source stream 抛异常、产生 `error`、缺少 `message_start`、重复/缺少 `message_complete`：不写 cache；
- 调用方提前停止迭代、取消 task 或 generator close：不写 cache；
- provider 返回 tool call 或请求携带 tools：eligibility 直接 bypass，按正常 provider stream；
- cache write 失败：已经发出的完整 stream 不回滚，记录 `cache_write_failed`。

`LLMStreamAccumulator.to_response()` 不是完成判定；实现必须额外维护 `saw_message_start`、`saw_message_complete` 和 `terminated_normally`。

### 9.2 Hit replay path

缓存命中只需保持事件**语义**，不承诺原 provider chunk 边界：

```text
message_start(metadata={cache_hit:true, provider_call:false})
text_delta(text chunks of bounded size)
usage_delta(source response usage, metadata usage_origin=cached_response)  # 可选
message_complete(metadata={cache_hit:true, provider_call:false})
```

回放必须满足：首事件为 `message_start`、尾事件为唯一 `message_complete`、顺序稳定、事件字段可由 `LLMStreamEvent.from_any()` 解析。由于 `usage_delta` 表示来源 response 的语义 usage，budget settlement 必须读取 `provider_call=false`，不能按 replay usage 计 provider 成本；如现有调用方无法区分两者，先扩展 event metadata/accumulator contract 再开启 stream cache。

第一版只允许无 tool-call 的 response，因此不生成 `tool_call_*` 回放事件。未来若放开，必须另建授权、去重和 replay contract，并通过独立 OpenSpec change。

## 10. Redis backend 与容量策略

### 10.1 专用 Redis boundary

LLM cache 不得和 `RedisRuntimeStore`、`RedisStreamTaskQueue`、durable event 或业务 pointer 共用一个可淘汰 namespace/实例。生产默认使用 `NEWS_LLM_CACHE_REDIS_URL` 指向专用实例/cluster；开发环境可以显式使用独立 database，但不得依赖共享实例的 `allkeys-*` eviction 来承载 durable state。

Redis cache backend 必须：

- 使用 `rediss://`、ACL、最小权限账号和连接 timeout（生产）；
- 设置 `maxmemory` 与 `allkeys-lfu` 或经压测证明的等价策略；
- 所有 entry 设置有限 `EX` TTL；不依赖 RDB/AOF 保证业务正确性；
- 使用 `SET key value NX EX` 或等价原子命令实现 single-flight lease；
- 用 Lua compare-and-delete 或 Redis transaction + owner check 原子释放 lease；
- 禁止请求路径使用 `KEYS`；管理清理使用 versioned namespace 或受控 `SCAN`；
- 对 `get`、`set`、lock wait 设置独立低 timeout，不能占满 LLM request deadline。

### 10.2 In-memory backend

`InMemoryLLMCache` 继续保留作为 unit test backend，但必须改为 bounded、thread-safe、monotonic TTL 实现：

- `max_entries` 和可选 `max_bytes` 必须有上限校验；
- get 命中更新 LRU 顺序，过期项惰性删除并可定期清理；
- `deepcopy` 或序列化 round-trip 隔离调用方对象；
- lock/lease 语义与 Redis backend 一致；
- 测试时注入 clock 和 deterministic owner token。

## 11. Security 与数据治理

1. **输入不落盘**：cache entry 不保存 request messages、prompt、tool schema、headers 或 API key；key 只保存 HMAC digest。
2. **响应最小化**：默认丢弃 `LLMResponse.raw` 和 provider 原始扩展字段；只保存重建 `LLMResponse` 所需的 safe fields。
3. **机密性**：项目已经声明 `cryptography` 依赖，但尚无 LLM cache codec；本阶段必须新增 cache-specific authenticated-encryption 实现并使用独立 `NEWS_LLM_CACHE_ENCRYPTION_KEY`，Redis transport 使用 TLS。不得复用 activity/event 密钥；密钥从 secret manager/environment 注入，不写 YAML。
4. **完整性**：payload 使用 domain-separated MAC/AEAD；MAC 不匹配必须删除该 entry 并走 provider，不得尝试宽松解析。
5. **scope 隔离**：scope 缺失、权限 snapshot 变化或 tenant/project 不同必须 miss；不得用“相同 prompt”跨 scope 共享。
6. **日志红action**：event/metric 只允许 `key_version`、短 digest、reason code、大小、延迟和部署 ID 的稳定哈希；禁止 prompt、response、tenant 原文和完整 key。
7. **访问控制**：cache adapter 的 Redis ACL 只能访问专用 prefix；运维清理接口必须由 Harness/operator authority 调用，不能由 LLM tool 直接调用。
8. **密钥轮换**：轮换 `NEWS_LLM_CACHE_KEY_SECRET` 或 encryption key 时 bump `key_version`/namespace；允许短期双读仅在明确 migration window，旧值仍须验证 MAC，不能无限兼容。

## 12. Configuration contract

建议新增独立的 runtime cache settings（实际字段名可与现有 config loader 对齐）：

```yaml
llm_cache:
  mode: disabled            # disabled | observe | write_only | read_write
  backend: memory           # memory | redis
  namespace: newsroom:llm-cache
  key_version: v1
  cache_generation: v1
  default_ttl_seconds: 300
  max_entry_bytes: 1048576
  singleflight:
    enabled: true
    lock_ttl_seconds: 120
    wait_timeout_ms: 2500
    poll_interval_ms: 50
  security:
    require_encryption: true
    key_secret_env: NEWS_LLM_CACHE_KEY_SECRET
    encryption_key_env: NEWS_LLM_CACHE_ENCRYPTION_KEY
  task_policies:
    classify:
      enabled: true
      require_temperature_zero: true
      required_dependencies: [prompt_revision, source_version]
    live_research:
      enabled: false
```

配置规则：

- `mode=disabled` 时不创建 Redis connection；
- `backend=redis` 且 mode 非 disabled 时，缺少 URL、HMAC secret、encryption key 或非法 TTL/size 必须在 composition 启动时 fail-fast；
- 当前 `framework/llm/clients/config.py` 对 top-level、route 和 deployment key 执行严格 allowlist；实现必须显式扩展 typed schema/validator，或使用独立的 cache settings loader，不能让 YAML 示例成为 parser 不认识的死配置；
- Redis transient error 由 `cache_failure_mode=fail_open`（默认）处理为 bypass；不允许把 cache error 当作 provider success；
- `default_ttl_seconds`、`lock_ttl_seconds`、`wait_timeout_ms` 必须有最小/最大范围，lock TTL 必须大于 provider timeout + safety margin；
- cache policy 不应散落在 endpoint；由 route/task configuration 和 typed `LLMCachePolicy` 注入；
- 更新 prompt、model、provider、route fallback、output schema 或 policy semantics 时必须显式 bump `cache_generation` 或 `key_version`。

建议新增 `.env.example` 变量：

```text
NEWS_LLM_CACHE_REDIS_URL=rediss://...
NEWS_LLM_CACHE_KEY_SECRET=
NEWS_LLM_CACHE_ENCRYPTION_KEY=
```

不得将真实值写入 `configs/models.yaml`、日志、测试快照或 PRD。

## 13. Durable events、metrics 与诊断

复用现有 `LLMRouterEvent`/event sink，不新建第二套 transcript model。新增稳定 event type 或等价 metadata：

```text
llm_cache_eligibility_evaluated
llm_cache_lookup_started
llm_cache_hit
llm_cache_miss
llm_cache_singleflight_waited
llm_cache_bypassed
llm_cache_write_succeeded
llm_cache_write_failed
llm_cache_corrupt_entry
```

每个 event 至少包含：`route_id`、`deployment_id`、`cache_mode`、`key_version`、`reason_code`、`provider_call`、`logical_request_id`、`duration_ms`；不得包含 raw request/response。phase transition 的 durable transcript 仍由 Harness/event runtime 负责，cache event 是该调用的证据，不是 workflow decision。

指标至少包括：

| 指标 | 维度限制 | 用途 |
| --- | --- | --- |
| `llm_cache_lookup_total` | backend、mode、reason | 总体行为 |
| `llm_cache_hit_total` / `miss_total` | route、deployment、task_type | 命中率与误配置 |
| `llm_cache_lookup_latency_ms` | backend、result | 延迟 |
| `llm_cache_write_total` | result、size_bucket | 写入质量 |
| `llm_cache_singleflight_wait_ms` | result | 击穿控制 |
| `llm_cache_provider_calls_avoided_total` | route、deployment | 实际节省 |
| `llm_cache_estimated_cost_avoided_usd` | 不带 tenant label | 成本估算 |
| `llm_cache_backend_error_total` | error class | Redis 健康 |

禁止使用完整 digest、prompt、tenant ID、response 内容作为高基数 label。审计查询必须依赖 `logical_request_id`/durable event 的关联，而不是把 response 复制到 metrics。

## 14. Failure matrix

| 故障 | deterministic result | 是否 provider fallback | 是否写 cache |
| --- | --- | --- | --- |
| policy disabled/not eligible | `cache_bypassed` | 是，按正常 router | 仅 `write_only` 且 policy 明确允许时，否则否 |
| Redis timeout/unavailable | `cache_backend_error` + fail-open | 是 | 否；可异步重试但不阻塞请求 |
| key/codec configuration invalid | composition startup failure | 不启动该 cache composition | 否 |
| key expired/evicted | miss | 是 | provider 成功后是 |
| payload schema/version unknown | corrupt miss，删除 entry | 是 | provider 成功后按新 version 写 |
| MAC/AEAD verification failed | corrupt miss，删除 entry并告警 | 是 | provider 成功后是 |
| single-flight lock busy | bounded wait + recheck | wait 命中则否；超时按配置 bypass provider | 非 owner 不写；owner 成功可写 |
| provider stream interrupted/cancelled | error/incomplete | 按现有 provider retry/fallback policy | 否 |
| provider response schema/tool/structured validation failed | provider error | 按现有 route policy | 否 |
| route/local/global budget gate failed | deterministic budget error | 否（除非现有 fallback policy允许） | 否 |
| response exceeds max bytes | provider response returned，`entry_too_large` | 不需要 | 否 |
| primary miss + fallback success | fallback response | 已按 route policy fallback | 只写 fallback identity |

Cache failure 不得改变既有 provider error taxonomy、retry budget、cooldown 或 Harness halt/replan 语义。

## 15. 实施切片与交付物

实施必须拆成可独立审查的 OpenSpec tasks；不得先做一个跨层 compatibility wrapper 再长期保留。

### Slice A：Contract and policy

- `CACHE-001`：定义 `CacheScope`、`CacheKey`、`CacheEntry`、`LLMCacheStore`、single-flight lease 和 reason code。
- `CACHE-002`：实现 versioned canonicalization、HMAC key、scope/deployment/cache-generation 隔离和 unknown metadata fail-safe。
- `CACHE-003`：重写 `LLMCachePolicy` eligibility，覆盖 temperature、tools、freshness、dependency revision、size 与 mode。
- `CACHE-004`：实现 bounded/thread-safe `InMemoryLLMCache`、TTL、codec round-trip 和 fake coordinator。
- `CACHE-005`：定义 safe response projection 和 cache-write deterministic validator；依据当前 request 复验 `output_schema/response_format`，禁止 `raw`/secret/request-scoped metadata 落 entry。

### Slice B：Router and budget integration

- `CACHE-010`：把 lookup 接入 `LLMRouter` deployment loop，确保顺序为 lookup -> cooldown -> budget -> provider。
- `CACHE-011`：按 deployment identity 处理 primary/fallback cache，补齐 hit/miss/bypass routing metadata。
- `CACHE-012`：扩展 `GlobalBudgetTracker`/`LLMCallTrace` 的 logical request、provider call、provider usage 语义；保持旧字段兼容但不改变其 provider budget 含义。
- `CACHE-013`：复用 `LLMRouterEvent` sink 记录 cache lifecycle event，并接入 durable projection。
- `CACHE-014`：在 composition root 注入 cache；禁止 endpoint、business worker 或 LLM client 私自创建全局 Redis/cache singleton。

### Slice C：Redis and single-flight

- `CACHE-020`：实现专用 `RedisLLMCache`，有限 TTL、max entry bytes、serialization/version/MAC 校验和 fail-open adapter。
- `CACHE-021`：实现 owner-token atomic lease、bounded wait、double-check、safe release、stale lock recovery 与 metrics。
- `CACHE-022`：加入 `NEWS_LLM_CACHE_REDIS_URL`、secret/encryption config、启动校验和 `.env.example` 文档。
- `CACHE-023`：为 Redis 连接、ACL/TLS、namespace、eviction 和运行态探针提供 operator contract；不依赖 `KEYS`。

### Slice D：Streaming

- `CACHE-030`：实现 cache-aware `stream()` miss accumulation，严格要求正常 completion 后才写。
- `CACHE-031`：实现完整 `LLMResponse` 到合法 `LLMStreamEvent` 的 bounded replay；区分 source usage 与 provider usage。
- `CACHE-032`：覆盖 cancellation、early close、error、duplicate completion、tool-call refusal 与 replay metadata。

### Slice E：Rollout and removal

- `CACHE-040`：实现 disabled/observe/write-only/read-write 运行模式和 per-task allowlist。
- `CACHE-041`：更新配置/README/runbook，增加 key-generation bump 和 targeted invalidation 操作。
- `CACHE-042`：删除旧的“只在 client 内包 `InMemoryLLMCache`”生产接线路径；保留 in-memory 只作为测试/development adapter。
- `CACHE-043`：完成 focused/broad/strict/smoke evidence，并归档 OpenSpec change；未通过 deterministic gate 不得标记 implemented。

## 16. 测试与验证计划

### 16.1 Framework unit/contract

1. canonical payload 对字典顺序、Unicode、缺省值和字段类型稳定；任一 semantic field、scope、deployment、model、generation 或 version 变化都 miss。
2. key 不包含原始 prompt/tenant，HMAC secret 不出现在 `to_string()`、event、exception 或 metrics。
3. eligibility 对默认关闭、unknown metadata、temperature、tools、live task、missing dependency、missing scope、oversized response 给出稳定 reason code。
4. entry projection round-trip 保留 content、structured output、usage、model 和空 tool calls；`raw`/secret/request metadata 被剥离。
5. in-memory TTL、LRU、max bytes、deep copy、并发 get/set 和 lease owner semantics。

### 16.2 Router/budget/fallback

1. 有效 hit 在 deployment cooldown 时仍返回；provider call count、cooldown state 和 provider budget 均不变。
2. hit 不执行 global preflight；logical request 计数增加，`max_llm_calls` 不增加。
3. miss 仍执行现有 cooldown、local budget、global budget、provider retry/fallback、shared deterministic output validation 和 route budget；任意 client 的 metadata 不能代替当前 request 的 schema/response-format 复验，任何 gate 失败不写入。
4. primary/fallback identity 隔离；fallback response 不污染 primary cache。
5. Redis error/corrupt/expired/oversized 均 fail-open 并记录 event；禁用 cache 时行为与基线一致。
6. two router instances sharing a fake/real Redis observe one valid entry and no cross-scope hit。

### 16.3 Streaming

1. 首次完整 stream 写入一次；回放事件可被 `LLMStreamAccumulator` 重建，且首尾/顺序合法。
2. source error、缺 start、重复或缺 complete、consumer early close/cancel 都不写。
3. replay does not emit tool events for phase-1 cache; source usage is not charged as provider usage。
4. cache write failure does not corrupt already yielded events or turn a successful provider response into a failed request。

### 16.4 Security/operations

1. encryption/MAC tamper test、wrong key/version、rotation invalidation、TLS/ACL configuration validation；generic/fake client 返回未验证 structured output 时必须被 cache-write validator 拒绝。
2. atomic lock release race test：旧 owner 不能删除新 owner lock；lock expiry 后新 owner 可接管。
3. maxmemory/eviction 只影响 cache namespace；runtime queue/pointer/event fixture 不被 cache tests 删除。
4. metrics/event snapshot 无 raw prompt、response、tool args、tenant 原文和完整 key。

### 16.5 Required checks

代码切片合入前按范围运行：

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/llm tests/infrastructure/storage/test_redis_llm_cache.py tests/infrastructure/storage/test_redis_runtime_store.py -q
python -m scripts.dev smoke
openspec validate llm-cache-production-hardening --strict
```

Redis live tests 必须显式 marker 和环境变量；默认本地测试不得因为没有 Redis 而失败。文档-only 阶段只需运行 `git diff --check`、Markdown link/path 检查和 OpenSpec 文档审查，不把当前无关 dirty tree 的 source failure 伪装成阶段 23 通过。

## 17. 验收标准（Definition of Done）

阶段 23 只有同时满足以下条件才可标记 `IMPLEMENTED`：

- [ ] `framework` 只依赖 cache port，production composition 显式注入 backend；不存在 framework -> infrastructure 反向依赖。
- [ ] exact key 包含 scope/deployment/model/provider/revision/schema，并使用 HMAC；没有 raw request key。
- [ ] 默认关闭，task/agent/freshness/temperature/tools/dependency/size policy 全部 deterministic 且有测试。
- [ ] router hit 在 cooldown/budget 前发生；hit 不产生 provider call/cost，仍产生 logical request 和 durable cache event。
- [ ] primary/fallback、cache generation、TTL、schema、MAC、entry size 和 invalidation 语义已验证。
- [ ] Redis backend 使用专用 URL/namespace、TLS/ACL 配置、有限 TTL、eviction boundary 和 fail-open 降级。
- [ ] single-flight lock 的 acquire/recheck/release/timeout 全部 bounded，owner release 原子且有并发测试。
- [ ] stream cache 只保存完整 response，正常 replay 协议合法；中断、错误和 tool-call 均不写/replay。
- [ ] cache write owner 会依据当前 request 重新执行 deterministic output-contract validation；不能依赖 provider client 或 metadata 自证，验证失败不会写入。
- [ ] response raw、prompt、secret、tenant 原文未进入 cache value、event、metric label 或异常。
- [ ] focused、broad、strict、smoke 检查全部通过；OpenSpec change 已归档；旧 client-only production wiring 已删除。

建议的硬门指标：

| 指标 | 目标 |
| --- | ---: |
| 跨 scope 错误命中 | `0` |
| 未完成 stream 写入 | `0` |
| cache hit 的 provider call | `0` |
| corrupt payload 被 replay | `0` |
| 旧 owner 删除新 lock | `0` |
| cache backend error 导致 workflow 失败 | `0`（除非 provider 本身失败） |
| cache lookup p95（同区 Redis，staging） | `<= 20 ms` |
| single-flight wait 超过调用 deadline | `0` |

命中率和成本节省只是运营指标，不能替代上述正确性 gate。

## 18. 发布、回滚与失效

### 18.1 发布顺序

```text
disabled
  -> observe（只评估资格与 key，不读写）
  -> write_only（填充，不服务 hit）
  -> read_write（仅对已审查 task allowlist）
```

每次扩大 allowlist 都要有 task owner、dependency revision、TTL、数据敏感性审查和 hit/miss/error 观测窗口。不要一次性为所有 Research/agent 请求打开。

### 18.2 回滚

- 将 mode 切回 `disabled`，provider 正常路径继续工作；
- 对不可信或错误 prompt/model 变更，优先 bump `cache_generation`，不在请求路径执行全库删除；
- 安全事件时撤销 Redis ACL/secret、切换 namespace，并保留 durable event 供审查；
- cache Redis 全部不可用时不暂停 Harness workflow，除非 provider/budget 本身触发既有 halt。

### 18.3 失效触发器

以下任何变化都必须 bump generation/version 或明确写入 dependency fingerprint：

- system/user prompt 模板或 parser/normalizer 改变；
- provider、model、deployment 配置、route fallback 顺序或 pricing 语义改变；
- output schema/response format/tool policy 改变；
- source/evidence/retrieval snapshot 改变；
- tenant visibility/permission policy 改变；
- cache entry schema、codec、redaction 或 eligibility 规则改变。

## 19. 风险与明确决策

| 风险/争议 | 本 PRD 的决定 | 原因 |
| --- | --- | --- |
| 只在 `CachedLLMClient` 里套 Redis | 拒绝；lookup 必须由 router 协作 | 否则无法绕过 cooldown/preflight，也无法区分 deployment/fallback identity |
| 直接复用 `RedisRuntimeStore` | 只复用连接配置/通用安全约定，不复用其 runtime lock/eviction 语义 | runtime data 不能被 cache eviction 影响，已有 release 也未承诺原子 compare-delete |
| 缓存 provider stream chunks | 拒绝；只缓存完整 response | chunk 协议/provider 绑定且容易留下半截结果 |
| cache hit 是否计 budget | logical request +1，provider calls/cost/tokens +0 | 保持成本预算真实，同时保留工作负载观测 |
| Redis 挂掉是否 fail closed | cache fail-open，provider 仍按既有 gate | cache 是优化，不应成为业务可用性单点；不可信 entry 仍 fail closed 为 miss |
| 缓存带 tools 的 response | 阶段 1 完全拒绝 | 旧 tool call 不能代替当前 Harness authorization/side-effect decision |
| semantic cache | 不在本阶段 | 误命中风险高于漏命中，且不适合多轮/agentic/live Research |
| unlimited TTL / AOF 当数据库 | 拒绝 | 数据新鲜度和 durable ownership 必须分离 |

## 20. OpenSpec 边界与后续工作

本文件是需求与落地边界，不直接创建代码或 compatibility layer。实施前创建 `llm-cache-production-hardening` OpenSpec change，并把 Slice A-E 映射为 tasks；每个 task 必须声明 owner、受影响的 port、migration/deletion、测试和回滚证据。

OpenSpec 不得把以下内容偷偷纳入本 change：

- workflow durable event schema 的第二套实现；
- Research domain 的业务 cache 或 evidence persistence；
- active skill/memory 自动演进；
- provider native prompt cache 的控制权；
- UI 或跨租户运营后台。

后续可单独评估的 change：

1. `llm-cache-tool-replay-contract`：在有明确 Harness authorization、idempotency 和 side-effect ledger 后才考虑 tool-call cache。
2. `llm-cache-tiered-local-cache`：Redis 正确性和容量指标稳定后再评估 bounded L1；必须保留 L2/失效一致性契约。
3. `llm-cache-analytics-projection`：若运营需要长期成本报表，将摘要投影到 durable analytics store，而不是延长 cache TTL。

阶段 23 的完成标志不是“Redis 能读写”，而是：在真实 router/Harness 路径中，缓存命中、预算、cooldown、fallback、stream completion、durable evidence 和安全边界都能被 deterministic tests 与 replay evidence 证明。
