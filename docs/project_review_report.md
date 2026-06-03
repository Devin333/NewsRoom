# 项目审查报告

## 0. 当前闭环状态

> 更新日期：2026-06-03。以下状态优先于后续原始审查描述；后续章节保留为历史问题分析和重构背景。

| 编号 | 当前状态 | 当前落点 / 证据 |
|---|---|---|
| I-01 | 已闭环 | `quality_gate_step.py` 只注入/读取 memory repository，memory 检查下沉到 `memory_quality.py`、`quality_context_projection.py`。 |
| I-02 | 已闭环 | `agent_tools.py` 注册 `daily.evidence_search`、`daily.source_metadata`、`daily.citation_validate`、`daily.section_draft`，业务逻辑由 `agent_tool_service.py` 承载。 |
| I-03 | 已闭环 | 普通 runner 和 agentic runner 都通过 `source_runtime_assembly_from_runtime()` 投影 source runtime。 |
| I-04 | 已闭环 | `quality_gate_step.py` 已变为 workflow adapter，质量评估、路由和输出构建拆到 `quality_gate_usecase.py`、`quality_gate_outputs.py` 等模块。 |
| I-05 | 已闭环并加防回归 | fake LLM 迁入 `agent_fixtures.py`，`agent_registry.py` 只保留生产 agent/runner 构造；架构测试禁止 registry 重新导入 fixture。 |
| I-06 | 已闭环 | `spec.py` 和 `spec_agentic.py` 复用 `source_evidence_steps.build_source_and_evidence_steps()`。 |
| I-07 | 已闭环 | `finalize_report_step.py` 已变为 adapter；最终报告路由在 `report_finalization.py`，输入归一化在 `report_draft_normalization.py`，通用值归一化在 `business.foundation.value_normalization`。 |
| I-08 | 已闭环 | `DailyIntelligenceRunner.__init__` 不再使用动态 `setattr` 绑定 connector。 |
| I-09 | 已闭环 | `_NoopMemoryQualityRepository` 已移除，质量门控消费注入 repository 或 context repository。 |
| I-10 | 已闭环 | `_collect_evidence_ids()` 已加入 `max_depth`，agent 输出还通过 `AgentOutputBudgetValidator` 做大小预算校验。 |
| I-11 | 已闭环 | `framework.llm.clients.config` 对 `configs/models.yaml` 做加载期 schema / secret / 路由校验，错误归一为 `LLMConfigurationError`。 |
| I-12 | 已闭环 | `report_writer.py` 在 `recall_service` 缺失时记录 warning，不再静默跳过 memory context。 |
| I-13 | 已闭环 | non-social-media bypass 统一由 `quality_gate_policy.assess_non_social_media_bypass()` 判断。 |
| I-14 | 已闭环 | stage 执行和失败记录拆到 `_workflow_execution.py`；失败 stage 会记录并 finish execution 后重新抛出。 |
| I-15 | 已闭环并加防回归 | fake scenario 改为显式 `fixture_scenario`，不再从 topic 字符串推断；架构测试固定生产 registry 的 fixture-free 边界。 |

仍建议继续推进的长期方向：

- Agent 间反馈闭环目前已有 `DailyAgentFeedbackRoutingService` 承载 bounded writer rewrite / source recollect 路由，以及 analyst evidence gap -> `daily.source_recollect` recommendation -> `DailySourceRecollectionProfile` -> `DailySourceRecollectionExecutionPlan` -> `DailySourceRecollectionExecutor` -> `DailySourceRecollectionExecutionReport` -> `DailySourceRecollectionQualityAssessment` -> finalization human review policy -> source/evidence pipeline -> planner 的正式补源闭环；补源 profile/plan/report/quality assessment 已进入 artifact 观测，且 assessment 已接入 strict quality gate 下的发布/人工审核策略。人工审核后的 approval resume 现在会投影为 `human_review_resume_route` / `quality.human_review_resume_route`，approve / reject route 回到 finalization，modify / rewrite route 可通过通用 `ResumeMode.FROM_STEP` 恢复到 `writer_agent` 重新执行后续链路；下一轮应继续推进 dotted key 从兼容双写到正式消费，并下线旧 key 依赖面。
- source/model 配置、workflow buffer、business layer boundary 已有基础 guard；`finalize_report`、source/evidence 主链路、函数型 feedback/recollect step、agent loop step、artifact publisher、daily run service 的 persistence / memory / board consumer、run inspection 的 quality preview / lineage，以及 report quality API 的 report/repository 质量结果读取已改为通过业务 projection 消费。`DailyAgentInputCanonicalizingRunner` 在 business 层把 dotted key 投影回 agent spec 期待的 canonical 输入，避免 framework runner 承载 daily alias 规则；planner/analyst 业务 payload 通过 `agent.planner.research_plan` 和 `agent.analyst.analysis_result` 作为正式中间结果 key，agent loop telemetry 通过 business spec 声明 `agent.<label>.loop.*` output aliases，framework 只做通用 key 复制；artifact publisher 现在只消费 `daily_intelligence.output_projection` 的专用 artifact 投影视图，泛用 `daily_output_value()` / `daily_output_contains()` 只保留在 projection 内部兼容边界；发布侧不再直接导入 `DAILY_BUFFER_ALIASES` 或维护 dotted/legacy 分支，并由架构测试防回归；服务层 consumer 同样通过 business output projection 消费，但继续保持 artifact key/path、legacy output key 和旧 consumer 行为稳定。持久化构造侧已拆出 `infrastructure.storage.persistence.records`、`record_inputs`、`record_builders` 和 `local_json_adapter`，由 `RunPersistenceInput` 显式承载 builder 输入，由 record model / builder 承载 report、quality、source、evidence、claim record 生成，由 adapter 模块承载本地 JSON 读写；repository 只保留协议、环境选择和 `persist_run_result()` / `persist_run_input()` 编排。daily/output persistence projection 已收敛为 `project_daily_output_for_persistence()` -> `daily_persistence_projection` -> `RunPersistenceInput`，落库不再要求先对 `result.output` 原地补 legacy key；memory ingestion 改为消费 `project_daily_output_for_memory_ingestion()` 的专用视图，只接收 report、evidence、quality decision 和 request/topic 输入；run inspection 改为消费 `project_daily_output_for_run_inspection()` 的专用视图，只接收 quality preview / lineage 所需 report、quality、citation、support 和 claim 字段；board attachment 也改为消费 `project_daily_output_for_board_attachment()` 的投影输入，只将 `board_outputs` / `cross_board_output` 正式结果合并回 run output。后续应继续减少 legacy key 双写面，并推进旧 key 消费面下线。
- `docs/prd1.md` 已标记为历史审查快照，并指向本文作为当前权威闭环状态；后续不要把它作为当前任务入口或完成状态依据。

## 1. 主要问题总览

| 编号 | 级别 | 问题位置 | 问题类型 | 问题摘要 | 建议优先级 |
|---|---|---|---|---|---|
| I-01 | P0 | `quality_gate_step.py` / `_NoopMemoryQualityRepository` | 伪实现 / 功能空洞 | 内存质量检查使用的是 Noop Repository，所有 search 均返回空，导致 memory 质量检查始终通过 | 立即 |
| I-02 | P0 | `agent_tools.py` / `build_daily_agent_tool_registry()` | 缺失实现 | Agent 的 `ToolRegistry` 为空，5 个 Agent 实际上没有任何工具可调用 | 立即 |
| I-03 | P1 | `runner.py` vs `runner_agentic.py` | 初始化模式不一致 | `DailyIntelligenceRunner` 使用 `setattr` 动态绑定连接器，而 `AgenticDailyIntelligenceRunner` 使用 `apply_daily_source_runtime_assembly`，两套初始化模式并存 | 高 |
| I-04 | P1 | `quality_gate_step.py` / `quality_gate()` | 函数过长 / 职责混杂 | 单函数约 200 行，混合 memory 上下文、historian 元数据、质量评估、rewrite、human review 和输出构建等职责 | 高 |
| I-05 | P1 | `agent_registry.py` / `build_daily_agent_fake_llm_client()` | 测试代码混入生产路径 | fake LLM client 构建逻辑、fixture 数据和 scenario 判断逻辑直接放在生产注册文件中 | 高 |
| I-06 | P1 | `spec.py` / `spec_agentic.py` | 大量重复代码 | `source_and_evidence_steps` 在两个 spec 中重复定义，维护成本高 | 高 |
| I-07 | P1 | `finalize_report_step.py` | 函数过长 / helper 粒度混乱 | 文件约 400 行，内部包含大量与业务无关的通用工具函数，应下沉到 shared 层 | 中 |
| I-08 | P1 | `DailyIntelligenceRunner.__init__` | 初始化副作用 / 隐式依赖 | 通过 `setattr` 动态绑定 connector，IDE 和类型检查无法感知，重构风险高 | 高 |
| I-09 | P2 | `quality_gate_step.py` / `_NoopMemoryQualityRepository` | 临时代码未清理 | Noop Repository 实现完整协议但全部返回空，说明真实 repository 注入机制尚未完成 | 中 |
| I-10 | P2 | `agent_loop_integration.py` / `_collect_evidence_ids()` | 递归遍历无深度限制 | 递归遍历 agent 输出中的 `evidence_id`，缺少最大深度限制，极端情况下可能触发递归过深 | 中 |
| I-11 | P2 | `configs/models.yaml` | 配置校验不足 | model 配置缺少 schema 验证，无法在启动阶段 fail-fast | 中 |
| I-12 | P2 | `runner.py` / `_function_registry` | 降级路径不可见 | `recall_service` 为 None 时 memory 上下文会被静默跳过，没有日志或告警 | 中 |
| I-13 | P2 | `quality_gate_step.py` / `finalize_report_step.py` | 逻辑重复 | 两处都存在 non-social-media bypass 逻辑，语义相同但实现分散 | 中 |
| I-14 | P3 | `business/boards/_workflow.py` | 异常处理流程不清晰 | `run()` 捕获 stage 异常后仍继续执行 finish 和 trace 构建，re-raise 前逻辑较重，阅读成本高 | 低 |
| I-15 | P3 | `agent_registry.py` | 测试分支脆弱 | fake client 的 scenario 解析依赖 topic 字符串中的特殊关键词，易碎且不可读 | 低 |

---

## 2. 详细问题分析

### I-01：`_NoopMemoryQualityRepository` 导致内存质量检查失效（P0）

**位置：**
`business/boards/cross_board/workflows/daily_intelligence/quality_gate_step.py`

**当前实现：**

```python
result = QualityMemoryChecker(_NoopMemoryQualityRepository()).check_report_context(context)
```

`_NoopMemoryQualityRepository` 的所有方法都返回空列表或 `None`。这意味着 `QualityMemoryChecker` 无法获取任何历史 claim、event 或 evidence。最终结果是：memory 质量检查在逻辑上永远无法发现问题。

**问题影响：**

所有依赖内存质量检查来阻断报告发布的逻辑都会失效，尤其是：

- 重复报道无法被捕获；
- 历史矛盾声明无法被发现；
- memory-aware quality gate 实际上变成空操作；
- `_has_critical_memory_issue` 在 live 环境中几乎不会被触发。

**推荐修改：**

不应在 `quality_gate` 内部直接构造 Noop Repository，而应通过依赖注入传入真实的 `IntelligenceMemoryRecallService` 或其底层 repository。

建议方向：

```python
def _memory_quality_result(context, memory_repository):
    return QualityMemoryChecker(memory_repository).check_report_context(context)
```

或者从 workflow buffer / dependency bundle 中读取真实 repository。

**是否建议立即修改：** 是。
**优先级：** P0，必须优先处理。

---

### I-02：Agent ToolRegistry 为空实现（P0）

**位置：**
`business/boards/cross_board/workflows/daily_intelligence/agent_tools.py`

**当前实现：**

```python
def build_daily_agent_tool_registry() -> ToolRegistry:
    return ToolRegistry()
```

**问题描述：**

当前 5 个 Agent，包括 planner、analyst、writer、verifier、editor，虽然在架构上被设计成 agentic workflow，但它们没有任何工具可调用。也就是说，Agent 实际运行时只能依赖 prompt 输入和 LLM 输出，无法进行真实的 evidence 查询、验证、过滤或补充分析。

**问题影响：**

这会导致整个 agentic workflow 退化为：

```text
prompt → LLM output → buffer write
```

而不是完整的：

```text
planning → tool use → evidence retrieval → reasoning → validation → rewrite
```

对于 live 环境来说，这是严重的功能缺失。

**推荐修改：**

至少应为以下 Agent 注册必要工具：

- `planner`：source metadata 查询、任务拆解辅助工具；
- `analyst`：evidence search、entity lookup、source filtering；
- `writer`：section draft helper、citation helper；
- `verifier`：evidence boundary check、citation validation；
- `editor`：quality review、rewrite suggestion。

示例方向：

```python
def build_daily_agent_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register("search_evidence", search_evidence_tool)
    registry.register("lookup_source_metadata", lookup_source_metadata_tool)
    registry.register("validate_citations", validate_citations_tool)
    return registry
```

**是否建议立即修改：** 是。
**优先级：** P0，必须优先处理。

---

### I-03：两套 Runner 初始化模式并存（P1）

**位置：**

- `runner.py`
- `runner_agentic.py`

**当前实现：**

`DailyIntelligenceRunner` 使用：

```text
DailyIntelligenceRuntime + setattr 动态绑定连接器
```

而 `AgenticDailyIntelligenceRunner` 使用：

```text
DailySourceRuntimeAssembly + apply_daily_source_runtime_assembly
```

**问题描述：**

同一批 connector 参数在两个 runner 中重复声明和处理，且初始化方式不同。新增 connector 时，需要同时修改两个地方，容易出现遗漏。

**问题影响：**

- 初始化逻辑分叉；
- connector 生命周期难以统一管理；
- 类型推断困难；
- 后续重构成本上升；
- agentic runner 和非 agentic runner 的行为可能逐渐漂移。

**推荐修改：**

统一使用 `DailySourceRuntimeAssembly` 作为 source 依赖的标准装配方式。

建议结构：

```python
class DailyIntelligenceRuntime:
    source_runtime: DailySourceRuntimeAssembly
    recall_service: IntelligenceMemoryRecallService | None
    ...
```

两个 runner 都通过同一个 builder 构建 source runtime，避免重复逻辑。

---

### I-04：`quality_gate()` 函数职责过重（P1）

**位置：**
`quality_gate_step.py`

**问题描述：**

当前 `quality_gate()` 单函数约 200 行，混合了多个独立职责：

- 读取 memory context；
- 读取 historian context；
- 执行 memory quality check；
- 执行报告质量评估；
- 判断是否需要 rewrite；
- 构建 human review；
- 构建输出对象；
- 写入 quality events。

这违反了单一职责原则，也让测试变得困难。

**推荐重构方向：**

```python
def quality_gate(buffer):
    ctx = _load_quality_context(buffer)
    memory_result = _check_memory_quality(ctx)
    evaluation = _evaluate_and_maybe_rewrite(ctx, memory_result)
    outputs = _build_quality_outputs(ctx, evaluation, memory_result)
    return outputs
```

建议拆分为：

- `_load_quality_context()`
- `_check_memory_quality()`
- `_evaluate_and_maybe_rewrite()`
- `_build_human_review_payload()`
- `_build_quality_outputs()`

这样每个子函数都可以单独测试。

---

### I-05：fake LLM client 混入生产注册逻辑（P1）

**位置：**
`agent_registry.py`

**问题描述：**

`build_daily_agent_fake_llm_client()` 及相关 `_fake_*` 函数与生产用的 `build_daily_agent_registry()`、`build_daily_agent_runner()` 放在同一个文件中。

这导致：

- 生产代码和测试 fixture 耦合；
- 文件职责不清；
- fake scenario 逻辑污染生产路径；
- fixture 数据难以复用；
- 后续新增测试场景会进一步膨胀该文件。

**推荐修改：**

将 fake client 相关逻辑迁移到独立文件，例如：

```text
agent_fixtures.py
fake_llm_clients.py
test_scenarios.py
```

`agent_registry.py` 应只保留生产构造逻辑。

---

### I-06：`spec.py` 与 `spec_agentic.py` 存在重复步骤定义（P1）

**位置：**

- `spec.py`
- `spec_agentic.py`

**问题描述：**

`collect → require → normalize → deduplicate → rank → build_evidence` 这一组 source/evidence steps 在两个 spec 文件中重复定义。

虽然 `spec_agentic.py` 已提取 `_source_and_evidence_steps()`，但 `spec.py` 中仍是内联写法。

**问题影响：**

- 修改 source 流程时需要同步两个文件；
- 容易出现两个 workflow 行为不一致；
- 测试覆盖容易遗漏；
- spec 文件会越来越臃肿。

**推荐修改：**

将共同步骤提取为公共 builder：

```python
def build_source_and_evidence_steps() -> list[StepSpec]:
    return [
        collect_sources_step(),
        require_sources_step(),
        normalize_sources_step(),
        deduplicate_sources_step(),
        rank_sources_step(),
        build_evidence_step(),
    ]
```

然后 `spec.py` 和 `spec_agentic.py` 共同复用。

---

### I-07：`finalize_report_step.py` 中通用工具函数过多（P1）

**位置：**
`finalize_report_step.py`

**问题描述：**

该文件约 400 行，`finalize_report()` 主函数约 100 行，同时包含大量通用 helper，例如：

- `_field_value`
- `_list_value`
- `_string_list`
- `_float_value`
- `_to_plain_dict`

这些函数并不属于 finalize report 的核心业务逻辑，应该下沉到 shared 层。

**推荐修改：**

可以拆分为：

```text
framework/shared/normalization.py
framework/shared/typing_utils.py
business/boards/cross_board/workflows/daily_intelligence/report_normalizer.py
```

`finalize_report_step.py` 应聚焦于最终报告组装，而不是承担通用数据清洗职责。

---

### I-08：`DailyIntelligenceRunner.__init__` 使用动态 `setattr` 绑定 connector（P1）

**位置：**
`runner.py`

**当前实现：**

```python
for field_name in CONNECTOR_FIELD_NAMES:
    setattr(self, field_name, getattr(self.source_dispatcher, field_name))
```

**问题描述：**

这种动态绑定会让 runner 对象在初始化后获得一批 IDE 和类型系统无法感知的属性。

**问题影响：**

- 静态类型检查失效；
- IDE 无法自动补全；
- 重构时难以发现字段引用；
- `CONNECTOR_FIELD_NAMES` 与 `source_dispatcher` 字段名之间形成隐式耦合；
- 新增或删除 connector 时风险较高。

**推荐修改：**

去掉该 `setattr` 循环，统一通过：

```python
self.source_runtime_assembly
```

或：

```python
self.runtime.source_dispatcher
```

访问 connector。

---

### I-10：`_collect_evidence_ids()` 递归遍历缺少深度限制（P2）

**位置：**
`agent_loop_integration.py`

**问题描述：**

该函数递归遍历 Agent 输出中的 `evidence_id` 字段，但没有最大递归深度限制。如果 LLM 输出了异常深的嵌套 JSON，可能触发 Python recursion limit。

**推荐修改：**

加入 `max_depth` 参数：

```python
def _collect_evidence_ids(value, *, depth=0, max_depth=50):
    if depth > max_depth:
        return set()
    ...
```

这属于防御性编程，成本低，收益明确。

---

### I-13：non-social-media bypass 逻辑重复实现（P2）

**位置：**

- `quality_gate_step.py`
- `finalize_report_step.py`

**问题描述：**

两个文件分别存在：

```python
_non_social_media_pass_review()
_non_social_media_editor_pass()
```

它们的语义基本一致：当 evidence 不是 social media 来源时，将部分非 PASS 决策强制放行。

**问题影响：**

- 相同业务规则分散在多个文件；
- 后续修改容易漏改；
- editor agent 的真实判断可能被下游静默覆盖；
- 质量门控策略不透明。

**推荐修改：**

将该逻辑统一提取到：

```text
source_gate_policy.py
```

或：

```text
quality_gate_policy.py
```

例如：

```python
def should_bypass_for_non_social_media(evidence_bundle, decision) -> bool:
    ...
```

---

## 3. Agent 架构专项审查

整体来看，当前 Agent 架构已经具备比较完整的骨架，但实际能力仍处于“框架搭好、关键能力未填充”的阶段。

### 已有优点

1. **角色划分清晰**

当前包含 planner、analyst、writer、verifier、editor 五类 Agent。每个 Agent 的输入输出 key 在 `spec_agentic.py` 中有明确声明，职责边界相对清楚。

2. **上下文隔离设计较合理**

每个 agent step 通过 `read_keys` 从 workflow buffer 中读取所需数据，避免了所有 Agent 共享完整上下文导致的污染问题。

3. **Evidence boundary 检查是一个好设计**

`DailyEvidenceOutputValidator` 会对 writer / verifier 的输出做 evidence boundary check，防止 Agent 引用 bundle 之外的 URL。这对降低幻觉和越权引用非常重要。

4. **有基本的循环保护机制**

Agent loop 中已经存在 `AgentLoopStallDetector` 和 max iterations detection，说明系统考虑了无限循环风险。

### 主要不足

1. **Agent 工具调用能力缺失**

`build_daily_agent_tool_registry()` 返回空 registry，这是当前 agentic 架构最大的短板。没有工具后，Agent 无法完成真正的 evidence 查询、验证和补充分析。

2. **Agent 之间缺少反馈闭环**

例如：

- analyst 发现 evidence 不足时，无法回溯触发 source recollect；
- verifier 发现 citation 问题时，无法触发 writer 局部重写；
- editor 发现质量问题时，无法清晰反馈给 writer 或 planner。

3. **Editor 决策可能被下游静默覆盖**

`REWRITE_REQUIRED` 在 non-social-media 情况下可能被 finalize 阶段覆盖为 PASS。这个策略如果是业务规则，应显式定义；如果只是临时 bypass，则需要尽快收敛。

4. **fake scenario 机制较脆弱**

`_fake_scenario()` 依赖 topic 字符串中的特殊关键词，例如 `"rewrite-valid"`，这会让测试逻辑变得隐式且不可读。

---

## 4. 代码逻辑专项审查

### 4.1 `require_sources()` 中存在 duck typing

当前错误处理逻辑同时兼容对象和 dict：

```python
error.error_type if hasattr(error, "error_type") else error.get("error_type", "unknown")
```

这说明 `source_errors` 中可能混入了不同类型的数据结构。

**建议：**

统一将所有错误转换为 `SourceError` 对象，不要在下游做类型猜测。

---

### 4.2 `deduplicate_sources()` 失败时直接返回空列表

当前逻辑中，如果去重失败，会 fallback 到：

```python
deduplicated_items = []
source_duplicate_groups = []
```

这会导致前面已经成功 normalize 的 sources 被全部丢弃。

**建议：**

去重失败时应降级为直接使用 `normalized_items`：

```python
deduplicated_items = normalized_items
source_duplicate_groups = []
```

---

### 4.3 `rank_sources()` 失败时也不应清空结果

ranking 失败时更合理的行为是保留上一步结果，而不是返回空列表。

**建议：**

```python
ranked_items = deduplicated_items
```

这样 workflow 可以继续产出结果，同时记录 quality event 或 warning。

---

### 4.4 `_normalize_report_draft()` 的异常处理需要纳入质量门控

当前 `_normalize_report_draft()` 如果遇到格式异常，会直接 `raise ValueError`。这会让 workflow 以 system error 的形式失败，而不是进入 blocked / human review 路径。

**建议：**

将此类异常纳入质量门控结果，例如：

```python
return FinalizeResult(
    status="blocked",
    reason="invalid_report_draft_format",
    ...
)
```

---

## 5. 数据流与状态管理审查

### 5.1 Buffer key 命名空间过于扁平

当前 workflow buffer 中存在大量平铺 key，例如：

- `source_errors`
- `source_events`
- `quality_events`
- `memory_context`
- `historian_context`
- `evidence_bundle`
- `citation_check_result`

随着 workflow 扩展，key 冲突风险会增加。

**建议：**

逐步引入命名空间约定：

```text
sources.errors
sources.events
quality.events
memory.context
agent.writer.output
agent.verifier.output
```

---

### 5.2 read-append-write 模式需要文档化

例如：

```python
events = list(buffer.read("quality_events"))
events.append(new_event)
buffer.write("quality_events", events)
```

这种 immutable read + new write 模式是合理的，但目前缺少文档说明。后续维护者可能误写为：

```python
buffer.read("quality_events").append(new_event)
```

从而破坏 buffer 的一致性假设。

**建议：**

在 workflow buffer 设计文档中明确：

- `buffer.read()` 返回值不应被原地修改；
- append 类操作必须采用 read-copy-write；
- 复杂数据结构建议使用 typed object 或 event collector。

---

### 5.3 memory context 缺失时的可见提示已闭环

当 `recall_service` 为 None 时，`draft_report` 不会写入 `memory_context`，`quality_gate` 会走 optional path。

这个降级行为本身可以接受，但 live 环境中必须有 warning 日志。当前已由 `report_writer.py` 记录：

```python
logger.warning("Memory recall service is not configured; memory context will be skipped.")
```

对应回归测试为 `test_daily_memory_recall_consumption.py` 中的 memory recall consumption 用例。

---

## 6. 安全性与稳定性审查

### 6.1 已有安全设计

`DailyEvidenceOutputValidator` 对 Agent 输出进行 evidence boundary 检查，这是非常重要的防护点。它可以防止 Agent 引用 evidence bundle 之外的 URL，降低引用幻觉和越界引用风险。

### 6.2 已收敛的风险点

1. **source URL/domain 白名单校验已接入**

`business.layers.signal.source_config` 加载 source registry 时会校验 `fetch.allowed_domains`，`SourceDispatcher` 运行期也会拒绝不在 fetch policy allowlist 内的 URL。证据包括 `test_source_config.py::test_load_source_registry_rejects_source_url_outside_allowed_domains` 和 `test_daily_intelligence_runner.py::test_daily_intelligence_runner_blocks_source_outside_runtime_allowed_domains`。

2. **Agent 输出大小与深度限制已接入**

Daily agent spec 已声明 `DAILY_AGENT_OUTPUT_BUDGET`，agent loop 由 `AgentOutputBudgetValidator` 执行输出预算校验；`_collect_evidence_ids()` 也已有 `max_depth` 参数和回归测试，避免深层 payload 递归遍历失控。

3. **memory quality gate 已恢复为真实业务路径**

`_NoopMemoryQualityRepository` 已移除，quality gate 消费注入 repository 或 `memory_context`。`test_quality_memory_integration.py` 覆盖了 social-media critical memory issue 被阻断、non-social media 通过策略绕行的路径。

4. **workflow / connector timeout 已有统一边界**

Daily agentic workflow 通过 `daily_workflow_runtime_policy()` 声明全局 timeout，framework runtime 会根据 workflow policy 生成 `WorkflowTimeoutBudget`；source fetch policy 继续承载 connector 级 timeout。

5. **失败降级路径不再清空有效输入**

`deduplicate_sources()` 失败时保留 normalized items，`rank_sources()` 失败时把 deduplicated items 包装为 fallback ranked items，并写入正式 `SourceError` 和 source event。对应测试在 `test_daily_intelligence_steps.py`。

---

## 7. 重构建议

### 已闭环事项

1. `_NoopMemoryQualityRepository` 已移除，quality gate 使用真实 memory context / repository 输入。
2. `build_daily_agent_tool_registry()` 已注册 daily evidence/source/citation/report draft 工具。
3. `DailyIntelligenceRunner` 的动态 connector `setattr` 路径已移除。
4. non-social-media bypass 已统一到 `quality_gate_policy.assess_non_social_media_bypass()`。
5. `source_errors` 已统一通过 `normalize_source_errors()` 和 `SourceErrorArtifactInput` 边界归一化。
6. deduplicate / rank 失败降级已改为保留有效 item 并写正式 error/event。
7. `DailyIntelligenceRunner` 与 `AgenticDailyIntelligenceRunner` 已通过 source runtime assembly 投影统一关键装配边界。
8. `spec.py` 与 `spec_agentic.py` 已复用 `build_source_and_evidence_steps()`。
9. fake LLM / fixture 代码已迁出 `agent_registry.py`，生产 registry 有架构测试防回归。
10. `quality_gate()` 已拆为 workflow adapter、usecase、evaluation、outputs、policy 等模块。
11. `finalize_report_step.py` 已变为 adapter，报告归一化、路由和输出构建下沉到业务服务。
12. workflow buffer 已引入命名空间 key 约定和 `buffer_key_aliases` / `workflow_buffer_access` 边界。

### 下一轮剩余方向

1. 继续把 dotted key 从兼容双写推进到正式消费，逐步缩小 legacy key fallback 面。
2. 继续收敛 artifact-facing projection 中的 legacy fallback，但保持 artifact key、manifest key 和历史 consumer 行为稳定。
3. quality gate 的 block / rewrite / memory conflict / human review route 已有跨 run 聚合入口，后续可接入持久化 run inspection 或 dashboard。
4. 继续减少 metadata 作为隐式数据通道的历史兼容面，优先新增正式 input view 或 domain model。
5. 对 source connector metadata fallback 做分批下线计划，保留 `SourceConnectorRuntimeOptions` 作为唯一业务读取口。

---

## 8. 推荐的下一步行动

### 当前闭环清单

- [x] 修复 `_NoopMemoryQualityRepository`，让 `quality_gate` 使用真实 memory repository / memory context。
- [x] 实现 `build_daily_agent_tool_registry()`，为 agent 注册 evidence 查询、source metadata、citation validate 和 section draft 工具。
- [x] 统一两套 Runner 初始化模式的 source runtime 边界。
- [x] 移除 `DailyIntelligenceRunner.__init__` 中的动态 connector `setattr`。
- [x] 提取 `spec.py` 和 `spec_agentic.py` 的公共 source/evidence steps。
- [x] 将 fake LLM / fixture 代码迁移出 `agent_registry.py`。
- [x] 重构 `quality_gate()`，拆分为可测试业务模块。
- [x] 统一 non-social-media bypass 逻辑。
- [x] 修复 deduplicate / rank 失败时返回空列表的问题。
- [x] 统一 `source_errors` 的数据类型。
- [x] 迁移 `finalize_report_step.py` 中的通用工具函数。
- [x] 当 `recall_service` 为 None 时增加 warning 日志。
- [x] 引入 buffer key 命名空间约定。
- [x] 为 `_collect_evidence_ids()` 增加最大递归深度。
- [x] 将 report draft 格式异常路由到 blocked report，而不是直接作为 system error 抛出。
- [x] 设计 Agent 间反馈闭环。
- [x] 增加配置 schema 启动校验。
- [x] 增加 workflow 级别全局 timeout。
- [x] 增加 source URL/domain 白名单校验。

### 建议下一轮小步

- [ ] 对 daily output 的 artifact-facing projection 继续做 legacy fallback 消费面审计。
- [x] 为 quality observability 增加跨 run 聚合入口，沉淀 block / rewrite / human review / memory conflict 指标。
- [ ] 为 source connector metadata fallback 制定下线顺序，并用架构测试禁止新增直接 metadata 读取。

---

## 9. 总体结论

当前项目的 daily intelligence / agentic workflow 已经从“骨架可运行”推进到“核心生产边界基本闭环”的状态。原报告中两个 P0 风险，即 memory quality check 空实现和 Agent tool registry 缺失，已经闭环；fixture 混入生产 registry、runner 动态装配、quality gate 过重、source error duck typing、dedup/rank 失败清空输入、缺少全局 timeout / allowlist 等问题也已有代码和测试证据。

接下来不建议继续做大爆炸式重构。更合适的方向是沿着已建立的 business boundary 小步收敛：减少 legacy key fallback，减少 metadata 兼容读取，把 artifact / quality / source connector 的历史兼容面继续压缩到明确 projection 或 input view 内。
