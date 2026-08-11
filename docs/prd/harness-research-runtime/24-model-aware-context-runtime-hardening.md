# 阶段 24：模型感知的 Context Runtime Hardening PRD

> Document status: READY_FOR_OPENSPEC
>
> Implementation status: NOT_STARTED
>
> Version: v1.0
>
> Priority: P0（模型调用正确性、证据完整性与 Harness 可回放性）
>
> Scope: `framework/llm/context`、`framework/llm/routing`、`framework/harness/context`，以及所有 production LLM callsite
>
> Baseline PRD: 阶段 3D `03d-context-engineering.md`
>
> Baseline OpenSpec: `llm-context-guard`（`8/8` complete；仅提供 estimate-and-signal MVP）
>
> Proposed umbrella change: `model-aware-context-runtime-hardening`
>
> Last updated: 2026-08-11

## 0. 一句话结论

当前 Context 能力不是“完全没有”，而是停留在 **粗略估算 + 超限报错 + 演示性压缩**：它尚未按最终 deployment 的真实能力计算请求，没有为输出建立一致预留，没有保证 tool-call transaction 原子性，也没有在压缩后重新执行 deterministic VERIFY。

本阶段要把 Context 收敛为两层、一个强制入口：

```text
Harness semantic context owner
  选择什么信息、保护哪些证据、允许怎样降级、压缩后是否仍可接受
                  |
                  v
LLM model-aware request preflight owner
  基于 resolved deployment 构造实际请求、精确计数、预留输出、决定 admit/reject
                  |
                  v
Provider adapter
  只发送已经 prepare + admit 的请求；provider overflow 作为估算漂移处理
```

任何 LLM 调用必须遵循：

```text
resolve deployment
-> normalize actual provider payload
-> count prompt tokens
-> reserve output tokens
-> deterministic admission
-> bounded semantic compaction（必要时）
-> re-count
-> deterministic VERIFY
-> complete / stream
```

LLM 可以生成摘要候选，但不得决定删什么、是否压缩成功、是否允许继续调用，也不得把未经验证的摘要写成 durable verified snapshot。

## 1. 背景与问题定义

### 1.1 已有正确方向

阶段 3D 已经定义了值得保留的设计：

1. Context 由 stable prefix 与 dynamic tail 组成，而不是无界拼接全部历史。
2. Context 有 `ContextEnvelope`、`ContextSnapshot`、`ContextBudget` 和 `CompressionRecord` 等显式模型。
3. instruction、任务约束、关键 evidence refs、未决 tool transaction 等内容应受保护。
4. 压缩应分级执行，并留下 durable event / snapshot，支持 review 与 replay。
5. LLM summary 只能是 candidate，必须通过 deterministic gate 才能成为 verified context。

这些语义继续由 `framework/harness/context` 持有。本 PRD 不把业务语义下沉到通用 LLM adapter。

### 1.2 旧 OpenSpec 的边界

`llm-context-guard` 完成的是一个有意收窄的 MVP：

- 在 provider 调用前估算逻辑请求大小；
- 把估算结果写入观测数据；
- 超过静态窗口时抛出统一异常；
- 明确不实现 provider-specific tokenizer、自动截断、摘要和 conversation compaction。

因此 `8/8 complete` 只表示旧 change 的范围完成，不表示 production Context Engineering 已完成。本阶段必须显式替换旧 requirement，不能把新增行为伪装成 bugfix。

### 1.3 当前实现缺口

| ID | 当前行为 | 风险 |
| --- | --- | --- |
| CTX-BASE-01 | `framework/llm/context/estimator.py` 对 JSON 序列化结果使用 `ceil(len / 4)` | 中文、代码、结构化 schema、图片和不同 tokenizer 下误差不可控 |
| CTX-BASE-02 | `ContextPolicy.max_context_tokens` 是调用方静态配置 | 没有绑定最终 routing deployment 的真实 context window |
| CTX-BASE-03 | guard 只使用 policy reserve | `LLMRequest.max_tokens` 与 model max output 没有进入统一预算 |
| CTX-BASE-04 | `ContextStrategy` 有 `ERROR/TRUNCATE/SUMMARIZE/HYBRID` | 四种值没有不同 runtime 行为，容易形成配置幻觉 |
| CTX-BASE-05 | `compression.py` 通过 `remaining.pop(0)` 删除旧消息 | 会破坏 system/instruction、assistant tool call 与 tool result 的成组关系 |
| CTX-BASE-06 | 单条超长消息无法继续压缩 | 可能返回仍然超过 target 的结果 |
| CTX-BASE-07 | tools / response schema 参与估算但不参与压缩 | 即使消息很短，超大 tool schema 仍使请求超窗 |
| CTX-BASE-08 | router 中 token estimate 主要用于 event metadata | 并未形成 provider 调用前不可绕过的 admission gate |
| CTX-BASE-09 | `ModelCapabilities.context_window_tokens`、`max_output_tokens` 已存在 | routing 没有用它们计算 effective budget 或 capacity fallback |
| CTX-BASE-10 | Harness compression 生成字符串截断式 summary 与伪 artifact URI | 没有真实 summary artifact、evidence provenance 和 loss report |
| CTX-BASE-11 | Harness 在压缩后直接记录 `context_compression_verified` | 没有以压缩后的 envelope 重新执行 `ContextBudgetGate` |
| CTX-BASE-12 | session、memory、Harness、LLM 各自有截断实现 | 同一请求可能多次有损处理，责任、优先级和 replay 均不清晰 |
| CTX-BASE-13 | production 中存在绕过 router/preflight 的 `.complete()` 调用 | 即使 router 修复，调用路径仍可绕过窗口保护 |
| CTX-BASE-14 | `complete`、`stream`、cache hit/miss 缺少统一 preparation contract | 相同逻辑请求可能得到不同计数、路由和 replay 语义 |

### 1.4 已复现的失败场景

| 场景 | 当前结果 | 目标结果 |
| --- | --- | --- |
| context window `100`、input estimate `75`、policy reserve `0`、request output `500` | guard 放行 | 在调用前 deterministic reject，或切换到能力满足的 deployment |
| strategy 分别配置 `ERROR/TRUNCATE/SUMMARIZE/HYBRID` | 全部抛同一种异常 | unsupported strategy 在配置加载时失败；supported strategy 执行明确状态机 |
| assistant tool call 之前有旧消息 | FIFO 可留下孤立 `tool` message | tool-call transaction 原子保留或原子移除 |
| 单条消息约 `250` tokens、target `10` | 返回仍约 `250` tokens | bounded compaction 后重新计数；仍超限则 fail closed |
| 短消息 + 大 tool schema | 删除消息后请求仍超限 | schema 进入独立 budget；不可删 schema 时返回结构化容量失败 |
| Harness 压缩后 token estimate `1300`、budget `100` | 写入 verified event | 第二次 gate 失败，不得写 verified snapshot，不得调用 provider |

这些场景必须转成自动化测试，不能只验证 happy path 或“异常是否被抛出”。

## 2. 外部实现与论文结论

### 2.1 可借鉴的工程模式

| 项目 | 可借鉴点 | 本项目采用方式 |
| --- | --- | --- |
| [LangGraph memory](https://docs.langchain.com/oss/python/langgraph/add-memory) | 可按 token budget trim；通过 `start_on` / `end_on` 保持有效消息历史；tool call 与 tool result 需要成组处理 | 引入 typed message group 和 transaction-atomic trim；不直接复制其通用 message API |
| [LangChain middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in) | 可按 token、message count 或 window fraction 触发摘要；保留最近消息并清理旧 tool use | 采用多触发器和 recent tail；摘要仍由 Harness gate 验证 |
| [OpenAI Codex model metadata](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/openai_models.rs) | model metadata 持有 context window；auto-compaction threshold 与 effective context percentage 分离 | 把 physical limit、operational limit、output reserve 和 safety margin 分开建模 |
| [Letta context hierarchy](https://docs.letta.com/v1-sdk/memory/context-hierarchy) | block、file、archival memory / RAG 分层，而不是把全部内容常驻 prompt | stable core、active evidence、retrievable refs、archival store 分层 |
| [MemGPT](https://arxiv.org/abs/2310.08560) | 把有限上下文视为需要显式管理的分层 memory，而不是单次字符串截断 | 保留 durable external state，由 Harness 选择性 materialize |

### 2.2 论文带来的约束

| 论文 | 结论 | 对 PRD 的要求 |
| --- | --- | --- |
| [Lost in the Middle](https://aclanthology.org/anthology-files/pdf/tacl/2024.tacl-1.9.pdf) | 长上下文并不等于模型能稳定使用全部信息，关键信息位置会影响表现 | 不能把“仍在 window 内”当作质量充分条件；关键 evidence 与任务目标要有稳定位置策略 |
| [LLMLingua](https://aclanthology.org/2023.emnlp-main.825/) | prompt compression 可显著降低 token，但依赖任务与压缩器 | 不作为默认路径；只能作为可替换 candidate compressor |
| [LongLLMLingua](https://aclanthology.org/2024.acl-long.91/) | 长上下文压缩需要 query-aware 信息保留与位置处理 | evidence compression 必须绑定当前 task/query，并输出 provenance |
| [RECOMP](https://arxiv.org/abs/2310.04408) | retrieval context 可通过抽取式或生成式 compressor 处理 | 优先抽取 evidence-bearing spans；生成式摘要必须经过引用和 loss gate |
| [Evidence Grounding for Long-Context LLMs](https://aclanthology.org/2026.customnlp4u-1.19/) | 更长上下文可能保留答案准确率但显著削弱 evidence grounding | 验收不能只看答案；必须单独测 citation/evidence grounding 与 omission |

### 2.3 采用与不采用

采用：

- deployment-aware tokenizer / counting；
- stable prefix + recent tail + retrievable refs；
- message/tool transaction atomicity；
- query-aware、evidence-first compaction；
- 压缩前后 token、provenance、loss 和 gate 记录；
- model context window 与 operational threshold 分离。

不直接采用：

- 无条件 FIFO 删除最旧消息；
- 用单次 LLM 摘要替代原始 evidence；
- 把大 context window 当作无需压缩或无需检索；
- 把 LLMLingua 类模型直接设为默认 compressor；
- 让 provider overflow exception 充当日常 admission control。

## 3. 用户与核心场景

| 角色 | 需要的结果 |
| --- | --- |
| Workflow / Harness author | 能声明保护段、优先级、压缩级别和失败策略，不处理 tokenizer 细节 |
| LLM routing owner | 能依据 resolved deployment 计算有效输入预算，并在发送前做一致 admission |
| Research worker | 能保留当前任务、引用、关键 evidence span、未决 tool transaction 和最近推理状态 |
| Operator / reviewer | 能看出为何压缩、删了什么、保留了什么、复核为何通过或失败 |
| Model adapter owner | 只负责真实 payload 和 provider error normalization，不持有业务压缩策略 |
| Evaluation owner | 能测答案质量、evidence grounding、引用完整性和压缩损失，而非只测 token 数 |

核心场景：

1. 正常请求在 resolved deployment 上一次 preflight 即通过。
2. 首选 deployment 容量不足，但兼容且允许的 fallback deployment 容量足够；router 在 provider 调用前完成切换。
3. 只有 dynamic conversation 超限；Harness 先移除可重建低价值段，再压缩旧历史并保留 recent tail。
4. evidence pack 超限；系统优先选择相关 evidence-bearing spans，保留 source/citation provenance。
5. tool schema 本身导致超限；系统不得通过删除用户任务掩盖问题，而应减少当次授权 tool 集或结构化失败。
6. 单个不可分割 protected segment 已超过有效预算；系统 fail closed，并提供 actionable reason code。
7. provider 返回 overflow；系统记录 estimator drift，最多执行一次受控 re-prepare，不做盲目无限重试。
8. replay 使用原始 snapshot、compaction plan 和 model profile 重建同一 prepared request。

## 4. 产品目标与成功指标

### 4.1 产品目标

- **G1 模型感知**：窗口判断基于 resolved deployment 的 profile，而非调用方猜测。
- **G2 请求一致**：计数对象与 provider adapter 最终发送对象在语义上相同。
- **G3 输出有界**：输出预留同时受 request、policy 和 model max output 约束。
- **G4 结构有效**：压缩后 message order、role 和 tool transaction 仍合法。
- **G5 证据安全**：关键 evidence 不被无记录删除；摘要带 provenance 和 loss report。
- **G6 Harness 决策**：routing、压缩许可、VERIFY、retry/replan/halt 均为确定性控制面决策。
- **G7 不可绕过**：所有 production `complete` / `stream` 路径经过统一 preflight。
- **G8 可回放**：每次 materialization、compaction、admission 和 fallback 都有 durable record。

### 4.2 量化指标

| 指标 | 目标 |
| --- | --- |
| 已知窗口超限请求到达 provider 的次数 | `0` |
| output reserve 未计入 admission 的 production 请求 | `0` |
| 压缩后孤立 tool call/result transaction | `0` |
| 写入 `context_compression_verified` 但二次 budget gate 失败 | `0` |
| production LLM callsite 绕过统一 preflight | `0` |
| provider overflow 后无界 retry | `0` |
| verified summary 缺少 source refs / loss report | `0` |
| protected evidence 被静默删除 | `0` |
| 同一 prepared request 在 complete/stream 的 token count 差异 | `0` |
| replay 缺少 model profile、budget 或 compaction record | `0` |

Estimator drift 作为观测指标，不承诺跨 provider 的绝对零误差：

```text
drift = provider_reported_prompt_tokens - local_counted_prompt_tokens
```

应按 provider、model、tokenizer revision 统计 P50/P95/P99，并由配置化 safety margin 吸收已知误差。

## 5. 范围与非目标

### 5.1 本阶段范围

- 建立 `ModelContextProfile` 和 `EffectiveContextBudget`。
- 在 routing 解析最终 deployment 后构造 `PreparedLLMRequest`。
- 为 messages、tools、response format、output schema、media metadata 建立 token accounting。
- 支持 provider/model-specific token counter，并保留明确的 conservative fallback。
- 将 system/instruction、conversation turn、tool transaction、evidence span 建模为可验证 group。
- 实现 deterministic compaction planner 与 bounded execution state machine。
- 在任何压缩后重新 count + VERIFY，不通过则 replan/fallback/halt。
- 收敛 direct client callsite、stream、cache 与 router 的 preparation contract。
- 补齐 durable event、metrics、adversarial tests 和 held-out evaluation。
- 删除或 deprecate 没有实现语义的 `ContextStrategy` 配置值。

### 5.2 非目标

- 不替换阶段 3D 的 Harness semantic context ownership。
- 不把 memory、RAG、artifact store 或 durable transcript 合并进 `framework/llm/context`。
- 不让 LLM 决定 workflow routing、quality pass/fail、tool authorization、memory write 或 publication。
- 不承诺任何内容都能压进任意小窗口；不可满足时必须 fail closed。
- 不实现无界自动 replan 或 provider retry。
- 不把所有 provider tokenizer 逻辑硬编码进 core；通过 port/adapter 扩展。
- 不默认启用 learned prompt compressor；其上线必须经过 held-out grounding eval。
- 不以增大模型 context window 取代信息选择、检索和证据排序。

## 6. 所有权与架构不变量

### 6.1 所有权矩阵

| 责任 | 唯一 owner | 禁止行为 |
| --- | --- | --- |
| 任务目标、保护段、证据优先级、压缩策略 | `framework/harness/context` | provider adapter 自行删除业务内容 |
| model profile、payload token count、physical admission | `framework/llm/context` + routing | Harness 复制 provider tokenizer 逻辑 |
| deployment 选择与能力 fallback | `framework/llm/routing` | LLM worker 自选 deployment 绕过 policy |
| provider payload 与 error normalization | provider client adapter | adapter 写 verified context event |
| summary candidate 生成 | LLM worker | candidate 自行晋升为 verified snapshot |
| summary/evidence/loss 验证 | deterministic Harness gate | 用“LLM 说保留了”代替结构和引用校验 |
| durable event schema 与 append | canonical event owner | Context 创建第二套永久 event model |
| memory/RAG 原始内容 | 对应 domain/application owner | LLM context 层修改原始 memory/evidence |

### 6.2 强制不变量

1. `input_tokens + reserved_output_tokens + safety_margin_tokens <= operational_context_limit` 才能 admit。
2. `operational_context_limit <= physical_context_window_tokens`。
3. child/retry 不得扩大父级已经批准的 token/cost/turn budget。
4. message group 要么整体保留，要么通过显式 action 整体替换/移除。
5. pending tool transaction、system instruction、current task 和 required output contract 默认不可删除。
6. `verified=true` 只能由压缩后的真实 envelope 通过 deterministic gates 后产生。
7. provider 调用只接受 `PreparedLLMRequest` 或等价的不可绕过 preflight proof。
8. fallback deployment 必须通过 capability、policy、cost、tenant 和 data-boundary 检查。
9. provider overflow 不得改写为普通 transient retry；它是 capacity/profile drift 类错误。
10. replay 必须使用 versioned tokenizer/profile/config，不能只记录最终字符串。

## 7. 目标运行流程

```text
Harness builds ContextEnvelope
  |
  +-- protected groups
  +-- dynamic groups
  +-- retrievable references
  +-- requested output contract
  |
  v
Router resolves candidate deployment
  |
  v
RequestPreparer normalizes provider-semantic payload
  |
  v
TokenCounter counts messages/tools/schema/media
  |
  v
BudgetResolver computes effective input budget
  |
  +-- fits ----------------------------> ADMIT
  |
  +-- does not fit
          |
          v
Harness ContextPlanner creates bounded compaction plan
          |
          v
Deterministic actions + optional summary candidate
          |
          v
StructureGate + EvidenceGate + LossGate + BudgetGate
          |
          +-- pass -> durable verified snapshot -> re-prepare -> ADMIT
          |
          +-- fail -> fallback deployment / controlled replan / HALT
```

Provider adapter 不得在最后一刻静默 truncate。任何 provider-side automatic truncation 若无法关闭，必须在 model profile 中显式声明并视为不满足 strict evidence mode。

## 8. 核心领域模型

### 8.1 `ModelContextProfile`

```python
@dataclass(frozen=True)
class ModelContextProfile:
    provider: str
    model: str
    deployment: str
    physical_context_window_tokens: int
    max_output_tokens: int
    tokenizer_family: str
    tokenizer_revision: str
    operational_input_fraction: float
    safety_margin_tokens: int
    supports_tool_calls: bool
    supports_structured_output: bool
    provider_auto_truncation: bool
```

约束：

- profile 来自 routing registry / deployment configuration，不由 request 任意传入。
- revision 变化必须可观测并进入 replay metadata。
- `operational_input_fraction` 默认小于 `1.0`，给输出、特殊 token 和估算漂移留出空间。

### 8.2 `EffectiveContextBudget`

```python
@dataclass(frozen=True)
class EffectiveContextBudget:
    physical_limit_tokens: int
    operational_limit_tokens: int
    requested_output_tokens: int
    reserved_output_tokens: int
    safety_margin_tokens: int
    max_input_tokens: int
```

计算规则：

```text
operational_limit = floor(physical_limit * operational_input_fraction)
requested_output = request.max_tokens ?? policy.default_output_tokens
reserved_output = min(requested_output, model.max_output_tokens)
max_input = operational_limit - reserved_output - safety_margin
```

如果 request 要求的 output 大于 model max output，应返回 typed configuration/capability failure；不得简单 clamp 后假装满足原始请求。

### 8.3 `ContextMessageGroup`

```python
@dataclass(frozen=True)
class ContextMessageGroup:
    group_id: str
    kind: Literal[
        "system_instruction",
        "task_contract",
        "conversation_turn",
        "tool_transaction",
        "evidence_span",
        "memory_excerpt",
        "summary",
    ]
    messages: tuple[LLMMessage, ...]
    priority: int
    protected: bool
    source_refs: tuple[str, ...]
    reconstructable: bool
```

一个 `tool_transaction` 至少覆盖 assistant tool call 及匹配的全部 tool result。planner 不允许把它拆成孤立消息。

### 8.4 `PreparedLLMRequest`

```python
@dataclass(frozen=True)
class PreparedLLMRequest:
    request_id: str
    deployment: str
    normalized_request: LLMRequest
    payload_fingerprint: str
    model_profile_revision: str
    token_count: LLMTokenCount
    effective_budget: EffectiveContextBudget
    admission: LLMContextAdmission
```

它是 logical request 与 provider adapter 之间的唯一合法交接物。`payload_fingerprint` 必须覆盖影响 token 与响应语义的 messages、tools、tool choice、response format、schema 和 media descriptors。

### 8.5 `LLMTokenCount`

```python
@dataclass(frozen=True)
class LLMTokenCount:
    message_tokens: int
    tool_tokens: int
    response_schema_tokens: int
    media_tokens: int
    protocol_overhead_tokens: int
    total_input_tokens: int
    method: Literal["exact", "provider_counter", "conservative_fallback"]
    tokenizer_revision: str
```

若只能使用 fallback，必须给出保守上界和 reason；不能继续把 `len / 4` 伪装成精确 token 数。

### 8.6 `ContextCompactionPlan`

```python
@dataclass(frozen=True)
class ContextCompactionPlan:
    plan_id: str
    source_snapshot_id: str
    target_input_tokens: int
    max_actions: int
    max_summary_calls: int
    actions: tuple[ContextCompactionAction, ...]
    protected_group_ids: tuple[str, ...]
    policy_revision: str
```

每个 action 必须是 typed action，例如：

- `DROP_RECONSTRUCTABLE_GROUP`
- `REPLACE_WITH_REFERENCE`
- `SELECT_EVIDENCE_SPANS`
- `COMPACT_OLD_CONVERSATION`
- `SUMMARIZE_GROUPS`
- `REDUCE_AUTHORIZED_TOOL_SET`

禁止使用无法审计的 `truncate(text, n)` 作为 production action。

### 8.7 `ContextCompressionRecord`

至少记录：

```text
source_snapshot_id
result_snapshot_id
plan_id
before/after token count
removed/replaced/retained group ids
source refs and summary refs
loss report
gate results
model/profile/tokenizer revision
reason code
```

## 9. 压力处理状态机

### 9.1 处理级别

按可逆性和信息损失从低到高执行：

| Level | 行为 | 是否需要 LLM |
| --- | --- | --- |
| R0 | 去除重复 materialization、空内容和纯传输冗余 | 否 |
| R1 | 将可重建内容替换为 durable refs | 否 |
| R2 | 只保留授权 tool/schema 集，移除本次不可能调用的 tool | 否 |
| R3 | 尝试兼容且被 policy 允许的 larger-context deployment | 否 |
| R4 | 对 evidence 做 query-aware span selection，保留 citation/provenance | 默认否 |
| R5 | 压缩已完成的旧 conversation/tool transaction，保留 recent tail | 可选 |
| R6 | 生成结构化 summary candidate，并执行 evidence/loss gates | 是 |

R0-R6 的实际顺序允许由 typed policy 配置，但必须满足：可逆操作优先、有损操作有界、fallback 不绕过成本和数据边界。

### 9.2 默认保护内容

- system instructions 与安全约束；
- 当前 user task / Workflow step contract；
- required output schema；
- 未完成的 tool transaction；
- deterministic gate 的失败原因与当前 retry/replan state；
- 当前答案必须引用的 evidence spans 与 source refs；
- 最近 N 个完整 conversation turns；
- publication、memory write、tool authorization 等控制面决定。

如果保护内容本身超过 budget，返回 `PROTECTED_CONTEXT_EXCEEDS_WINDOW`，不得静默删减。

### 9.3 Summary candidate contract

生成式摘要必须返回结构化结果：

```text
summary_text
covered_group_ids
source_refs
claims[] -> supporting refs[]
omitted_topics[]
unresolved_questions[]
tool_outcomes[]
loss_risk
```

Deterministic gates 至少包括：

1. source refs 都存在且属于 source snapshot；
2. protected facts / required refs 均被覆盖；
3. 未完成 tool transaction 未被描述为已完成；
4. summary 不引入 source 中不存在的新 artifact/tool outcome；
5. 压缩后结构合法；
6. 压缩后重新 token count 并通过 budget gate；
7. action 数、summary call 数、replan 数均未超过上限。

## 10. Routing、Provider 与 Cache Contract

### 10.1 Routing 顺序

Router 对每个候选 deployment 执行：

```text
capability filter
-> tenant/data-boundary policy
-> model context profile lookup
-> request preparation and count
-> context admission
-> cost/cooldown/capacity policy
-> select deployment
```

capacity fallback 不是“遇到 overflow 再试另一个模型”。在可计算的情况下，应在第一个 provider 调用前排除容量不足的 deployment。

### 10.2 Provider overflow

Provider 返回 context overflow 时：

1. 归一化为 `LLMProviderContextOverflow`；
2. 记录 prepared count、provider reported limit/usage、profile revision 和 drift；
3. 禁止按普通 transient error 自动 retry 同一 payload；
4. 最多允许一次受控 re-prepare，且必须改变 profile、payload 或 compaction plan；
5. 第二次仍失败则 halt/fallback，不得循环。

### 10.3 Complete / Stream 一致性

- `complete` 与 `stream` 使用同一个 preparer、counter 和 admission。
- stream 开始后不得因中途重新估算而更换 request identity。
- stream accumulator 的结果必须关联 `prepared_request_id`。
- cancellation 不得把未完成 stream 写入完整 response cache。

### 10.4 Cache 一致性

本 PRD 不实现 response cache，但对阶段 23 形成以下约束：

- cache key 基于 admitted `PreparedLLMRequest.payload_fingerprint` 与 deployment/profile revision；
- cache lookup 不得绕过 context preparation；
- cache hit 不产生 provider token usage，但仍关联原始 prepared/admission record；
- compaction policy 或 context snapshot 改变后，旧 key 不得误命中；
- incomplete stream、provider overflow、failed gate 不得写 cache。

## 11. 配置契约

建议配置形态：

```yaml
llm_context:
  profile_registry_revision: "2026-08-11"
  default_operational_input_fraction: 0.90
  default_safety_margin_tokens: 512
  fallback_counter:
    enabled: true
    conservative_multiplier: 1.35
  admission:
    max_prepare_attempts: 2
    allow_capacity_fallback: true
  compaction:
    enabled: true
    max_actions: 8
    max_summary_calls: 1
    keep_recent_complete_turns: 4
    strategy_order:
      - deduplicate
      - replace_with_refs
      - reduce_tool_set
      - select_evidence_spans
      - compact_old_conversation
      - verified_summary
  provider_overflow:
    max_reprepare_attempts: 1
```

配置规则：

- 所有数值必须在 composition/config validation 时校验。
- strategy 名称必须映射到真实实现；未知或未实现值 fail fast。
- `max_summary_calls`、`max_actions`、`max_prepare_attempts` 和 Harness `max_replans` 必须共同形成有限状态机。
- 业务 Workflow 可以进一步收窄 policy，不得扩大全局限制。

## 12. Durable Event 与可观测性

### 12.1 事件

复用 canonical durable event owner，至少投影以下事件：

```text
llm_context_profile_resolved
llm_request_prepared
llm_context_admission_decided
context_compaction_planned
context_compaction_action_applied
context_summary_candidate_created
context_compaction_verified
context_compaction_rejected
llm_context_capacity_fallback_selected
llm_provider_context_overflow_observed
```

`context_compaction_verified` 必须引用：

- source/result snapshot refs；
- compaction record ref；
- budget、structure、evidence、loss gate results；
- token count before/after；
- policy、model profile 和 tokenizer revisions。

### 12.2 Metrics

```text
llm_context_input_tokens
llm_context_reserved_output_tokens
llm_context_utilization_ratio
llm_context_estimator_drift_tokens
llm_context_admission_rejected_total{reason}
llm_context_compaction_total{action,outcome}
llm_context_compaction_ratio
llm_context_capacity_fallback_total{from,to}
llm_context_provider_overflow_total{provider,model}
llm_context_grounding_regression_score
```

禁止把 prompt、evidence 原文或 summary 原文作为 metric label。日志与 events 必须遵循现有敏感信息处理策略。

## 13. 功能需求

### FR-CTX-001：Model profile resolution

Router 必须在 preparation 前解析 versioned `ModelContextProfile`；缺少有效 profile 时 production 调用 fail closed，除非明确启用 conservative fallback profile。

### FR-CTX-002：Provider-semantic request preparation

Token counting 必须覆盖 adapter 实际发送的 messages、tools、response format/schema、media descriptors 与协议 overhead。preparer 与 provider payload builder 必须共享 typed normalization，而不是各自拼装一份近似结构。

### FR-CTX-003：Output reserve

Admission 必须显式考虑 request desired output、policy default/minimum 与 model max output；冲突时返回结构化 reason，不得忽略或静默 clamp。

### FR-CTX-004：Deterministic admission

每个 provider call 前必须产生 `LLMContextAdmission`：`ADMITTED`、`COMPACTION_REQUIRED`、`CAPACITY_FALLBACK_REQUIRED` 或 `REJECTED`，并记录计算输入。

### FR-CTX-005：Message group validity

Context assembler 必须把 message history 解析为 typed groups，验证 role order、tool call/result pairing、pending transaction 和 protected group；无效历史不得进入 provider。

### FR-CTX-006：Bounded compaction

Compaction planner 只能生成允许列表内的 typed actions，并受 action、summary call、replan 与 token/cost budget 限制。相同 snapshot + policy + query 应生成可重放的 deterministic plan，LLM summary 内容除外。

### FR-CTX-007：Evidence-safe compression

Evidence 压缩优先使用 extractive span selection；任何生成式摘要必须携带 source refs、claim support、omission/loss report，并通过 gate 后才能替换原上下文。

### FR-CTX-008：Post-compaction VERIFY

每次有损或结构变化后必须重新运行 structure、evidence/loss 和 budget gates。任一失败均不得写 verified event、不得调用 provider。

### FR-CTX-009：Callsite convergence

所有 production `LLMClient.complete()` / `stream()` 调用必须经由 managed router/preflight service，或显式接收不可伪造的 `PreparedLLMRequest`。测试 fake 可以保留轻量入口，但不得成为 production composition。

### FR-CTX-010：Provider overflow recovery

Provider overflow 必须使用独立异常和有限恢复路径；同一 payload 不得作为 transient error 重试。

### FR-CTX-011：Replay and audit

Durable transcript 必须足以说明：使用了哪个 model profile、如何计数、为何压缩、哪些 group 被处理、哪些 gate 通过、最终发送了什么 fingerprint。

### FR-CTX-012：Evaluation gate

上线有损 compressor 前必须在 held-out Research 场景上同时满足 answer quality、evidence grounding、citation completeness 和 latency/cost gate。只降低 token 不构成晋升依据。

## 14. 代码影响面

| 路径 | 目标变更 |
| --- | --- |
| `framework/llm/context/window.py` | 用 typed admission/profile/budget 替换仅含字符串 strategy 的 policy |
| `framework/llm/context/estimator.py` | 改为 token counter port 与 conservative fallback；保留旧 estimator 仅作迁移诊断 |
| `framework/llm/context/guard.py` | 收敛为 deterministic admission，不直接执行语义压缩 |
| `framework/llm/context/compression.py` | 删除 FIFO message pop；若保留，只实现 group-safe deterministic primitives |
| `framework/llm/routing/router.py` | 在 resolved deployment 后强制 prepare/count/admit，支持 capacity-aware fallback |
| `framework/llm/models/capabilities.py`、`framework/llm/routing/deployment.py` | 让 `ModelCapabilities` 的 context/output 字段进入真实决策，或替换为 profile ref |
| `framework/llm/clients/openai_compatible.py` | 复用 request normalization，报告 provider overflow/usage；不持有 Harness policy |
| `framework/harness/context/assembler.py` | 压缩后重新运行所有 deterministic gates，再写 verified event |
| `framework/harness/context/compression.py` | 用 typed plan/action/record 替换字符串截断和伪 artifact URI |
| `framework/agent/session/*` | 删除独立字符截断 ownership，改为提供 typed source groups / refs |
| `framework/memory/context/*` | memory 只提供候选 excerpt/ref，不独立决定最终 prompt truncation |
| direct production callsites | 迁移到 managed LLM execution service |
| canonical event schema | 增加上述 event projection，禁止另建 Context event store |

迁移前必须再次执行 live callsite inventory；本表是 owner map，不是静态文件清单承诺。

## 15. OpenSpec 拆分与实施顺序

本 PRD 是 umbrella 文档，禁止用一个超大 change 同时修改全部层。建议拆成四个顺序 change：

### Change 1：`model-aware-llm-context-preflight`

交付：

- `ModelContextProfile`、`EffectiveContextBudget`；
- provider/model token counter port；
- request preparation 与 fingerprint；
- router 强制 admission；
- output reserve 与 provider overflow normalization；
- complete/stream 基础一致性。

验收后，逻辑请求即使还不能自动压缩，也必须能够准确 admit/reject。

### Change 2：`harness-context-compaction-verification`

交付：

- typed group / compaction plan / actions / record；
- protected content 与 tool transaction atomicity；
- evidence-first compaction；
- summary candidate contract；
- post-compaction deterministic VERIFY；
- durable snapshot/event。

### Change 3：`managed-llm-callsite-convergence`

交付：

- inventory 所有 production `.complete()` / `.stream()`；
- 迁移 worker、agent loop、visual describer、benchmark production mode 等路径；
- cache 与 prepared request contract 对齐；
- 删除 production bypass composition。

### Change 4：`evidence-safe-context-evaluation`

交付：

- adversarial corpus；
- held-out Research grounding suite；
- provider tokenizer drift dashboard；
- learned compressor candidate/eval/promotion/rollback contract；
- release gate 与 baseline ledger。

依赖顺序：

```text
Change 1
  -> Change 2
  -> Change 3
  -> Change 4
```

Change 3 的 callsite inventory 可与 Change 2 调查并行，但 production 切换必须基于已经稳定的 Change 1 contract。

每个 change 均须：

```powershell
openspec validate <change> --strict
```

## 16. 测试计划

### 16.1 Unit tests

- model/profile budget calculation 边界：0、exact fit、1 token overflow、max output conflict；
- exact/provider/fallback counter 的 breakdown 与 revision；
- system、turn、tool transaction、evidence group parser；
- protected group 不可删除；
- tool transaction 原子保留/移除；
- single oversized group fail closed；
- tool/schema-only overflow；
- deterministic plan action 与上限；
- summary refs、claim support、omission/loss gate；
- post-compaction re-count/re-gate；
- provider overflow typed normalization。

### 16.2 Integration tests

- primary model 容量不足、fallback model 容量足够；
- capability 满足但 context profile 不满足时不调用 primary provider；
- complete 与 stream 产生同一 preparation fingerprint/count；
- cache hit/miss 与 prepared request identity 一致；
- Harness compression fail 后 provider call count 为 `0`；
- durable replay 重建相同 plan、group ids、budget 和 fingerprint；
- direct production client composition 被架构测试拒绝。

### 16.3 Adversarial tests

- 中文、代码、JSON schema、长 URL、Unicode 与多语言 token drift；
- 恶意超大 tool description/schema；
- assistant multiple tool calls + 部分/乱序/重复 tool results；
- instruction injection 被伪装成 memory/evidence；
- summary candidate 丢失否定词、数字、时间、source ref；
- evidence 引用存在但 claim 与 span 不支持；
- recent tail 很小但 protected prefix 已超限；
- provider profile 热更新与 tokenizer revision 变化；
- provider 报告 overflow 后同 payload 不被盲重试；
- max actions / summary calls / replans 全部耗尽后确定性 halt。

### 16.4 Evaluation

至少包含：

- 单篇论文分析；
- 多来源冲突证据；
- Reader repair；
- bounded Agentic RAG 多轮补查；
- 带 tool transaction 的长 session；
- structured output + 大 schema；
- 中英文混合长上下文。

每个场景同时评估：

```text
task answer quality
evidence grounding
citation completeness
protected fact retention
tool outcome correctness
token reduction
latency and monetary cost
```

## 17. 验收标准

### AC-CTX-001：模型感知 admission

给定同一 logical request 和两个不同 context window 的 deployment，系统在 provider 调用前产生不同且正确的 admission；不再只依赖静态 `ContextPolicy.max_context_tokens`。

### AC-CTX-002：输出预留

给定 input `75`、window `100`、requested output `500`，系统不得 admit；event 中能看到 input、requested/reserved output、margin 和 reason。

### AC-CTX-003：结构完整

任意 compaction 后都不存在孤立 tool result、丢失对应 call 的 tool result、非法 role order 或被拆分的 protected transaction。

### AC-CTX-004：压缩后复核

若 compaction result 仍超过 budget，`context_compression_verified` event 数为 `0`，provider call 数为 `0`，run 进入受控 fallback/replan/halt。

### AC-CTX-005：证据完整

verified summary 的每个外部事实 claim 都可追溯到 source refs；required evidence 与否定/数字/时间约束通过 held-out gate。

### AC-CTX-006：不可绕过

架构测试证明 production composition 中不存在未经 preparation/admission 的 direct provider call；complete、stream 和 cache 都遵循同一 contract。

### AC-CTX-007：有限恢复

provider overflow 后，同一 payload 自动 provider retry 次数为 `0`；受控 re-prepare 最多 `1` 次，整体仍受 Harness retry/replan budget 约束。

### AC-CTX-008：可回放

从 durable transcript 可重建 model profile revision、budget、source/result snapshots、compaction actions、gate results 和 final payload fingerprint。

### AC-CTX-009：真实质量门

learned/generative compressor 只有在 held-out answer quality 与 evidence grounding 均不低于批准阈值时才能 promotion；不满足时 rollback 到 deterministic/extractive strategy。

## 18. 需求、任务与测试映射

| Requirement | 主要任务 | 必测证据 |
| --- | --- | --- |
| FR-CTX-001..004 | Change 1 profile/preparer/counter/admission | exact fit、output reserve、multi-deployment fallback |
| FR-CTX-005..008 | Change 2 groups/plan/actions/gates | orphan tool、single oversized group、false verified regression |
| FR-CTX-009 | Change 3 callsite migration | architecture inventory、complete/stream/cache integration |
| FR-CTX-010 | Change 1 provider error contract | no blind retry、one bounded re-prepare |
| FR-CTX-011 | Change 2 durable projections | replay reconstruction、schema revision |
| FR-CTX-012 | Change 4 evaluation gate | answer + grounding + citation + cost report |

## 19. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| tokenizer SDK 不可用或模型未注册 | conservative fallback + fail-closed policy；记录 method/revision |
| provider payload builder 与 counter 漂移 | 共享 typed normalization；golden payload tests；usage drift metrics |
| compaction 降低证据 grounding | evidence-first、held-out grounding gate、可回滚 strategy |
| Context owner 再次重复 | 严格执行 ownership matrix；session/memory 只产出 groups/refs |
| fallback model 成本或数据边界不允许 | fallback 必须重新走 policy/cost/tenant checks |
| summary LLM 本身占用 token/cost | `max_summary_calls`、独立 budget、优先 deterministic actions |
| profile 热更新破坏 replay | versioned immutable revision；event 记录 revision |
| 一次迁移所有 callsite 风险过大 | Change 1 contract 先稳定，Change 3 分批迁移并设架构 gate |
| 为追求 token reduction 过度压缩 | release gate 同时衡量 answer/grounding/citation，不以压缩率单独晋升 |

## 20. 发布、回滚与完成定义

### 20.1 发布策略

1. **Observe-only**：新 counter/profile 与旧 guard 并行记录，不改变调用结果。
2. **Admission shadow**：记录新旧决策差异，验证 provider usage drift。
3. **Enforce preflight**：先对少量无 tool、无有损压缩路径启用。
4. **Deterministic compaction**：启用 R0-R5 中不依赖生成式摘要的 action。
5. **Verified summary candidate**：仅对通过 held-out eval 的场景启用 R6。
6. **Callsite closure**：架构 gate 拒绝新 direct provider bypass。

每一步都必须有 feature flag、tenant/workflow scope、metrics 和 rollback owner。

### 20.2 回滚策略

- learned/generative compressor 可回滚到 deterministic/extractive path；
- compaction 可关闭，但 deterministic preflight/admission 不得回滚为 provider-side overflow；
- 新 profile revision 可回滚到上一 immutable revision；
- callsite migration 可按 composition binding 回滚，但不得恢复无 admission 的 production 路径；
- durable events 采用兼容 schema migration，不删除已写历史。

### 20.3 Definition of Done

- 四个 OpenSpec change 均通过 strict validation，并按顺序归档；
- 所有 FR 与 AC 有实现、测试和 evidence ledger 映射；
- 旧 `len / 4` 只作为显式 fallback/迁移诊断，不再被称为精确 token estimate；
- 无行为差异的 ContextStrategy 被删除或实现；
- FIFO `pop(0)` production compression 路径删除；
- 压缩后 deterministic re-count + VERIFY 成为强制路径；
- production direct LLM callsite 收敛；
- complete/stream/cache contract 一致；
- provider overflow 无盲重试；
- held-out Research evaluation 同时通过 answer、grounding、citation、latency/cost gates；
- compile、targeted tests、broad tests、smoke 与 OpenSpec strict validation 全部通过；
- durable replay 和 operator diagnostics 经人工演练验证。

完成这些条件后，NewsRoom 才能把 Context 描述为：

> 在 Harness 控制下，按最终模型能力装配、计数、压缩、验证并守住上下文窗口；LLM 只生成候选内容，所有 admission、质量判断和状态推进均可审计、可回放、可失败关闭。
