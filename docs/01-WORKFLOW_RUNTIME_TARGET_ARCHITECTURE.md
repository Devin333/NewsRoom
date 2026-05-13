# 01-WORKFLOW_RUNTIME.md

版本：v1.0-target-architecture  
适用项目：News Intelligence System  
模块：Workflow Runtime  
定位：目标态架构设计，不是 MVP 简化版  

---

### 0.2 v1.3 运行装配命名约定

本模块吸收“运行装配 / 执行外壳 / 测试台”的设计思想，但正式命名统一使用 `WorkflowRunner`，不使用不直观的外来命名。

`WorkflowRunner` 的定位是 Workflow Runtime 的可编程入口：

```text
Interface / Worker / Test / Workflow-specific Runner
  -> WorkflowRunner
      -> WorkflowExecutor
          -> StepRunnerRegistry
              -> StepRunner
```

`WorkflowRunner` 只负责装配和调用，不负责 graph 执行细节。真正执行 workflow graph 的仍然是 `WorkflowExecutor`。


## 0. 文档定位

本文档定义 News Intelligence System 的 **最终目标态 Workflow Runtime**。

注意：

- 本文档不是第一版实现说明。
- 本文档不是 MVP 裁剪方案。
- 本文档先定义最终系统应该长什么样。
- 后续 MVP、P1、P2、生产化阶段，都应该从这个目标架构中裁剪实现范围。
- 第一版实现只是目标态架构的一个子集，而不是反过来用第一版限制最终设计。

Workflow Runtime 是整个 News Intelligence System 的流程执行内核。它负责把情报生产过程建模成可验证、可执行、可回放、可审计、可扩展的 workflow graph。

---

## 0.1 v1.1 设计审查结论：Workflow Runtime 的修订边界

本次审查不压缩 Workflow Runtime 的目标态能力，而是明确它在九份 PRD 中的系统边界。

需要保留：Workflow Runtime 仍然是流程执行内核，负责 graph、step、edge、routing、checkpoint、pause/resume、artifact manifest 与 run event。

需要修正：Workflow Runtime 不应成为 ArtifactRef、RunStore、ArtifactStore、CheckpointStore 的 canonical 定义处。这些模型和 repository 协议的归属应放在 `07-STORAGE_AND_MEMORY_TARGET_ARCHITECTURE.md`；本文件只描述 Workflow Runtime 如何依赖这些接口。

需要做设计减法：

```text
保留最终态 step_type 列表，但实现路线必须分层：
  core: function / agent_loop / router / quality_gate / persist / artifact
  advanced: parallel_group / join / subworkflow / human_review / notification
  extension: llm_decide edge / event trigger / scheduled trigger

LLM_DECIDE edge 只能作为可解释的辅助路由，不能用于安全、审批、质量通过、发布等强治理决策。
```

跨文档一致性要求：

```text
WorkflowRunStatus 由 Workflow Runtime 定义语义，由 Storage 持久化。
TaskStatus 由 Worker/Scheduler 定义。
ReportStatus 由 Evidence/Quality + Storage 定义。
Interface 层只能组合展示这些状态，不能重新发明一套状态语义。
```

---

## 0.2 v1.2 复查修订：避免 canonical 定义重复

本次复查发现，v1.1 虽然已经声明 `ArtifactRef`、`RunStore`、`ArtifactStore`、`CheckpointStore` 归 Storage/Memory 文档所有，但本文后续仍保留同名 `class` 示例。

这在设计文档阅读上可以理解为“依赖视图”，但在 OpenSpec / vibe coding / 代码生成时容易被误读为第二套定义。

因此 v1.2 进一步收敛：

```text
01 Workflow Runtime:
  只定义 WorkflowSpec / StepSpec / EdgeSpec / DataBuffer / StepOutcome / WorkflowResult / Workflow event type

07 Storage / Memory:
  统一定义 ArtifactRef / RunStore / ArtifactStore / CheckpointStore / EventStore / EventRecord / persistent record
```

本文不再用 `class ArtifactRef` 或 `class RunStore` 形式重复定义 Storage 模型，只说明 Workflow Runtime 对这些接口的依赖关系。


## 1. 为什么需要 Workflow Runtime

News Intelligence System 最终不是一个简单脚本，也不是单次 LLM 调用。

它会包含：

```text
source collection
source health
normalization
deduplication
ranking
evidence construction
analysis
verification
writing
citation checking
editor review
human review
memory indexing
persistence
publishing
subscription notification
scheduled rerun
failure recovery
```

这些过程具有以下特点：

1. 有固定顺序。
2. 有条件分支。
3. 有失败恢复。
4. 有质量门控。
5. 有人工介入点。
6. 有并行抓取和并行分析。
7. 有长期状态和历史记忆。
8. 有运行日志和 artifact。
9. 有成本、token、时间、质量指标。
10. 有不同工作流形态：daily、weekly、topic、company、paper、github project。

因此，系统需要一个自研 Workflow Runtime 来统一描述、执行和审计这些流程。

---

## 2. 参考项目的通俗解释

### 2.1 Hive：像“会思考的流程图”

Hive 把 Agent 运行建模成 graph。

通俗理解：

```text
Graph = 一张流程图
Node = 每一个会做事的步骤
Edge = 步骤之间的箭头
Shared Memory = 所有节点共享的数据仓库
GraphExecutor = 按流程图执行的人
EventLoopNode = 会调用 LLM、会用工具、会自我检查的特殊节点
```

Hive 的特点是：每个 Agent 都可以是一张节点图。节点读共享内存，做事情，再把结果写回共享内存。边负责决定下一步走哪里。Hive 的文档也明确说，节点读取 shared buffer、写回输出；edge 可以 on success、on failure、conditional、LLM-decided；shared buffer 会强制节点只能访问声明的 key。

值得借鉴：

- Graph / Node / Edge 思想。
- Shared Memory 的读写权限。
- GraphExecutor 和 EventLoopNode 分离。
- 节点 success / failure 路由。
- 条件边。
- LLM 决策边。
- 节点内自我修正。
- Human-in-the-loop。
- 运行指标、路径、成本统计。

不应照搬：

- Hive 当前更偏 Agent Graph，`event_loop` 是核心节点类型。
- News 需要大量确定性数据处理节点，不能所有步骤都做成 LLM 节点。
- News 需要更强的 evidence、citation、report、source、artifact 业务约束。

---

### 2.2 Burr：像“带权限的接力棒”

Burr 最值得借鉴的是：

```text
每个 action 声明 reads / writes
```

通俗理解：

```text
每个工人只能拿自己被允许拿的材料，
只能把结果放到被允许的位置，
不能随便翻整个仓库。
```

对应 News：

```text
StepSpec.read_keys
StepSpec.write_keys
ScopedDataBuffer
```

这对最终态非常重要。因为 News 后面会有很多 agent，如果不限制读写边界，系统会变成一团共享上下文。

---

### 2.3 Dagu：像“每次运行都有施工日志”

Dagu 的价值在于：

```text
每次 workflow run 都有日志、状态、历史记录和 artifacts
```

通俗理解：

```text
一次 workflow 就像一次施工：
施工前有图纸，
施工中有日志，
施工后有验收记录，
出错了可以回放。
```

News 应该把 artifact replay 放到一等公民位置：

```text
request.json
workflow_spec.json
data_buffer.json
events.jsonl
manifest.json
report.md
report.json
error.json
```

---

### 2.4 Prefect：像“任务管家”

Prefect 的价值是：

```text
task status
retry
timeout
state tracking
failure handling
```

通俗理解：

```text
网络失败可以重试，
API key 没配直接失败，
LLM 429 可以等一会再试，
schema 错误不要无限重试。
```

News 的最终态需要完整 RetryPolicy 和 ErrorPolicy。

---

### 2.5 Hamilton：像“流水线加工厂”

Hamilton 的价值是把业务函数写得清楚：

```text
raw_items -> normalized_items -> deduplicated_items -> ranked_items -> evidence_bundle
```

News 最终态应该让确定性数据处理逻辑尽可能纯函数化：

```python
normalize_sources(raw_items) -> normalized_items
deduplicate_sources(normalized_items) -> deduplicated_items
rank_sources(deduplicated_items, request) -> ranked_items
```

Runtime 负责调度，不把业务逻辑写死在 executor 里。

---

### 2.6 Dagster：像“资产台账”

Dagster 的价值是：

```text
不仅关心任务是否执行，
还关心任务产出了什么资产，
这些资产之间有什么 lineage。
```

News 的资产包括：

```text
source_items
evidence_items
verified_claims
report_sections
final_report
artifact_index
memory_documents
```

最终态 Workflow Runtime 要能记录这些对象的 lineage。

---

## 3. Hive Workflow Runtime 结构分析

Hive 中相关模块主要在：

```text
core/framework/graph/
  node.py
  edge.py
  executor.py
  event_loop_node.py
  conversation.py
  conversation_judge.py
  validator.py
  safe_eval.py
  checkpoint_config.py
```

Hive 不叫 workflow runtime，而是 graph runtime。

### 3.1 Hive 的核心结构

```text
GraphSpec
  ├── NodeSpec[]
  └── EdgeSpec[]

NodeSpec
  定义节点做什么、读什么、写什么、用什么工具、用什么模型、如何校验

EdgeSpec
  定义节点之间如何跳转

SharedMemory
  graph run 期间的共享状态

GraphExecutor
  执行整张 graph

NodeProtocol
  节点执行接口

EventLoopNode
  多轮 LLM + tool + judge 的特殊节点

ExecutionResult
  返回 success、error、path、metrics、session_state 等
```

### 3.2 Hive 的 NodeSpec 值得参考什么

Hive 的 NodeSpec 包含很多字段，例如：

```text
id
name
description
node_type
input_keys
output_keys
nullable_output_keys
input_schema
output_schema
system_prompt
tools
model
routes
max_retries
retry_on
max_node_visits
output_model
max_validation_retries
client_facing
success_criteria
```

News 最终态可以吸收这些能力，但命名上应该更贴近情报 workflow：

```text
WorkflowSpec
StepSpec
EdgeSpec
```

News 的 StepSpec 最终应该包含：

```text
identity
type
implementation
input contract
output contract
schema contract
runtime policy
retry policy
timeout policy
resource policy
quality policy
lineage policy
artifact policy
```

### 3.3 Hive 的 SharedMemory 值得参考什么

Hive 的 SharedMemory 支持共享数据读写，并提供带权限的视图。

News 应该设计：

```text
DataBuffer
ScopedDataBuffer
PersistentDataBuffer
DataBufferSnapshot
DataBufferDiff
```

最终态不只是内存 dict，而应该支持：

```text
step-level read/write permission
snapshot
diff
redaction
serialization
resume
checkpoint
artifact export
DB persistence
lineage link
```

### 3.4 Hive 的 EdgeSpec 值得参考什么

Hive 的 EdgeCondition 包括：

```text
always
on_success
on_failure
conditional
llm_decide
```

News 最终态应该支持类似能力，但要增加情报系统自己的 edge 类型：

```text
always
on_success
on_failure
conditional
quality_pass
quality_rewrite_required
quality_blocked
human_approved
human_rejected
budget_exceeded
source_unavailable
llm_decide
```

### 3.5 Hive 的 GraphExecutor 值得参考什么

Hive 的 GraphExecutor 负责：

```text
validate graph
initialize shared memory
execute node
validate output
write memory
handle retries
follow edges
handle pause/resume
track path
track metrics
return execution result
```

News 最终态 WorkflowExecutor 也应该负责这些，但要加强：

```text
artifact replay
source failure isolation
quality gate state
lineage propagation
cost guard
secret redaction
run manifest
storage persistence
memory indexing hooks
human review resume
```

### 3.6 Hive 的 EventLoopNode 值得参考什么

Hive 把 LLM 多轮循环放在 EventLoopNode 里，而不是塞进 GraphExecutor。

这是非常重要的边界：

```text
WorkflowExecutor 只管流程调度
AgentLoop 只管 LLM 循环
ToolRuntime 只管工具执行
LLM Layer 只管模型调用
```

News 应该继承这个分层。

---

## 4. News 最终态 Workflow Runtime 目标

最终态 Workflow Runtime 应该支持以下能力。

### 4.1 图执行能力

支持：

```text
linear workflow
branching workflow
conditional routing
failure routing
retry loop
quality gate loop
parallel fan-out
fan-in join
subworkflow
human-in-the-loop pause/resume
scheduled trigger
event trigger
manual trigger
```

### 4.2 Step 类型体系

最终态不应该只有 function 和 agent_loop。

建议支持：

```text
function
agent_loop
tool_call
tool_batch
parallel_group
join
subworkflow
human_review
persist
memory_index
artifact
router
quality_gate
notification
```

解释：

| Step Type | 用途 |
|---|---|
| function | 确定性 Python 逻辑 |
| agent_loop | LLM agent 循环 |
| tool_call | 单个工具调用 |
| tool_batch | 批量工具调用 |
| parallel_group | 并行执行多个 step |
| join | 汇合并行结果 |
| subworkflow | 调用另一个 workflow |
| human_review | 人工审阅/批准 |
| persist | 写数据库 |
| memory_index | 写向量库 |
| artifact | 写出文件产物 |
| router | 根据状态决定下一步 |
| quality_gate | 质量门控 |
| notification | 通知订阅者 |

### 4.3 Workflow 类型体系

最终系统至少支持：

```text
daily_intelligence
weekly_intelligence
topic_intelligence
company_intelligence
paper_intelligence
github_project_intelligence
source_health_check
memory_reindex
report_rewrite
human_review_publish
subscription_alert
```

Workflow Runtime 不能只为 daily news 写死。

---

## 5. 最终态核心模型

### 5.1 WorkflowSpec

```python
class WorkflowSpec(BaseModel):
    workflow_id: str
    name: str
    description: str = ""
    version: str

    trigger: WorkflowTriggerSpec | None = None

    start_step_id: str
    terminal_step_ids: list[str] = Field(default_factory=list)

    steps: list[StepSpec]
    edges: list[EdgeSpec]

    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

    policies: WorkflowPolicySpec = Field(default_factory=WorkflowPolicySpec)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

最终态 WorkflowSpec 不只是步骤列表，还应该包含：

```text
trigger
input schema
output schema
policy
version
metadata
```

### 5.2 StepSpec

```python
class StepSpec(BaseModel):
    step_id: str
    name: str
    description: str = ""

    step_type: StepType
    implementation: str

    read_keys: list[str] = Field(default_factory=list)
    write_keys: list[str] = Field(default_factory=list)
    required_output_keys: list[str] = Field(default_factory=list)
    nullable_output_keys: list[str] = Field(default_factory=list)

    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

    retry_policy: RetryPolicySpec = Field(default_factory=RetryPolicySpec)
    timeout_policy: TimeoutPolicySpec = Field(default_factory=TimeoutPolicySpec)
    failure_policy: FailurePolicySpec = Field(default_factory=FailurePolicySpec)
    resource_policy: ResourcePolicySpec = Field(default_factory=ResourcePolicySpec)
    quality_policy: QualityPolicySpec | None = None
    artifact_policy: ArtifactPolicySpec | None = None
    lineage_policy: LineagePolicySpec | None = None

    idempotent: bool = True
    cacheable: bool = False
    client_facing: bool = False

    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 5.3 EdgeSpec

```python
class EdgeSpec(BaseModel):
    edge_id: str
    source_step_id: str
    target_step_id: str

    condition: EdgeCondition
    condition_expr: str | None = None

    input_mapping: dict[str, str] = Field(default_factory=dict)
    output_mapping: dict[str, str] = Field(default_factory=dict)

    priority: int = 0
    description: str = ""

    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 5.4 DataBuffer

最终态 DataBuffer 应该不是普通 dict，而是 workflow run 的状态模型。

```python
class DataBuffer:
    def read(key: str) -> Any: ...
    def write(key: str, value: Any, lineage: Lineage | None = None) -> None: ...
    def exists(key: str) -> bool: ...
    def snapshot() -> DataBufferSnapshot: ...
    def diff(previous: DataBufferSnapshot) -> DataBufferDiff: ...
    def scope(read_keys: list[str], write_keys: list[str]) -> ScopedDataBuffer: ...
    def redact(policy: RedactionPolicy) -> dict[str, Any]: ...
```

### 5.5 ScopedDataBuffer

```python
class ScopedDataBuffer:
    def read(key: str) -> Any: ...
    def write(key: str, value: Any, lineage: Lineage | None = None) -> None: ...
    def list_allowed_reads() -> list[str]: ...
    def list_allowed_writes() -> list[str]: ...
```

### 5.6 StepOutcome

```python
class StepOutcome(BaseModel):
    status: StepStatus
    outputs: dict[str, Any] = Field(default_factory=dict)

    error_type: str | None = None
    error_message: str | None = None
    error_details: dict[str, Any] = Field(default_factory=dict)

    metrics: StepMetrics = Field(default_factory=StepMetrics)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    lineage: list[LineageRecord] = Field(default_factory=list)

    next_hint: str | None = None
```

### 5.7 WorkflowResult

```python
class WorkflowResult(BaseModel):
    run_id: str
    workflow_id: str
    workflow_version: str
    status: WorkflowStatus

    output: dict[str, Any] = Field(default_factory=dict)
    error: WorkflowError | None = None

    path: list[str] = Field(default_factory=list)
    step_results: dict[str, StepOutcome] = Field(default_factory=dict)

    metrics: WorkflowMetrics = Field(default_factory=WorkflowMetrics)
    manifest: RunManifest
```

---

## 6. 最终态执行器设计

### 6.1 WorkflowExecutor 职责

WorkflowExecutor 负责：

```text
validate workflow spec
resolve workflow version
initialize run context
initialize data buffer
create run manifest
write initial artifacts
execute graph
call node runners
enforce read/write scope
validate outputs
record events
handle retries
handle failure policy
route edges
handle parallel branches
handle join
pause for human review
resume from checkpoint
write final artifacts
persist run summary
return WorkflowResult
```

### 6.2 WorkflowExecutor 不负责

WorkflowExecutor 不应该负责：

```text
LLM prompt construction
LLM response parsing
tool implementation
RSS fetching details
database SQL details
Qdrant indexing details
report writing content
citation checking rules
```

这些都属于其他模块。

### 6.3 NodeRunner / StepRunner 抽象

最终态应该支持不同 StepType 的 runner。

```text
StepRunner
  FunctionStepRunner
  AgentLoopStepRunner
  ToolCallStepRunner
  ToolBatchStepRunner
  ParallelGroupRunner
  JoinStepRunner
  SubworkflowRunner
  HumanReviewStepRunner
  PersistStepRunner
  MemoryIndexStepRunner
  ArtifactStepRunner
  QualityGateStepRunner
```

这样 WorkflowExecutor 不需要对每种 step 写大量 if/else。

执行过程：

```text
WorkflowExecutor
  -> StepRunnerRegistry.get(step.step_type)
  -> runner.run(step_context, scoped_buffer)
  -> StepOutcome
```

---

## 7. 最终态 Routing 设计

### 7.1 EdgeCondition

```python
class EdgeCondition(str, Enum):
    ALWAYS = "always"
    ON_SUCCESS = "on_success"
    ON_FAILURE = "on_failure"
    CONDITIONAL = "conditional"
    LLM_DECIDE = "llm_decide"

    QUALITY_PASS = "quality_pass"
    QUALITY_REWRITE_REQUIRED = "quality_rewrite_required"
    QUALITY_BLOCKED = "quality_blocked"

    HUMAN_APPROVED = "human_approved"
    HUMAN_REJECTED = "human_rejected"

    BUDGET_EXCEEDED = "budget_exceeded"
    SOURCE_UNAVAILABLE = "source_unavailable"
```

### 7.2 RoutingEngine

```python
class RoutingEngine:
    async def next_steps(
        self,
        workflow: WorkflowSpec,
        current_step: StepSpec,
        outcome: StepOutcome,
        buffer: DataBuffer,
        context: WorkflowRunContext,
    ) -> list[str]:
        ...
```

最终态 routing 不只能返回一个 step，也可能返回多个 step：

```text
parallel fan-out -> 多个 next steps
normal route -> 一个 next step
terminal -> 空列表
```

### 7.3 条件表达式

条件表达式必须安全执行。

可以借鉴 Hive 的 safe_eval 思路，但 News 应该限制表达式能力：

```text
允许访问 outcome.status
允许访问 outcome.metrics
允许访问 buffer 中声明可读 key
允许比较数字、字符串、布尔
禁止 import
禁止函数调用
禁止文件访问
禁止网络访问
```

---

## 8. 最终态状态与持久化

### 8.1 Run State

```text
created
running
paused
waiting_for_human
retrying
succeeded
failed
blocked
cancelled
budget_exceeded
```

### 8.2 Step State

```text
pending
running
succeeded
failed
skipped
retrying
blocked
paused
cancelled
```

### 8.3 Checkpoint

最终态支持 checkpoint/resume：

```text
checkpoint_id
run_id
workflow_id
current_step_ids
data_buffer_snapshot
path
step_results
event_offset
created_at
resume_token
```

用途：

```text
human review pause/resume
long-running workflow recovery
process crash recovery
scheduled continuation
manual rerun from step
```

### 8.4 Persistence Backend

最终态 Workflow Runtime 应该支持多后端：

```text
filesystem artifact store
local JSON repository
PostgreSQL run store
Redis runtime state cache
object storage artifact store
```

Runtime 不应该写死某个后端，而是依赖接口。

注意：Workflow Runtime 依赖以下 Storage ports，但不在本文定义它们的 Python 协议：

```text
RunStore          -> 创建/更新/读取 workflow run 状态
ArtifactStore     -> 写入和读取 workflow artifact
CheckpointStore   -> 保存和恢复 checkpoint
EventStore        -> 追加 workflow event 并支持回放
```

这些接口的 canonical 协议、字段和持久化语义统一归 `07-STORAGE_AND_MEMORY_TARGET_ARCHITECTURE.md` 管理。

---

## 9. 最终态 Artifact 设计

### 9.1 Artifact 一等公民

每次 run 必须可以审计和回放。

标准 artifact：

```text
request.json
workflow_spec.json
workflow_version.json
data_buffer.initial.json
data_buffer.final.json
data_buffer.diff.json
events.jsonl
manifest.json
step_results.json
metrics.json
report.md
report.json
error.json
redaction_report.json
```

### 9.2 Step-level Artifact

每个重要 step 可以写自己的 artifact：

```text
steps/{step_id}/input.json
steps/{step_id}/output.json
steps/{step_id}/error.json
steps/{step_id}/metrics.json
steps/{step_id}/llm_request.redacted.json
steps/{step_id}/llm_response.redacted.json
```

注意：

- 必须 redaction。
- 不能写 API key。
- 不能写 Authorization header。
- 可以写 redacted prompt 和 response，便于调试。

### 9.3 ArtifactRef 依赖视图

Workflow Runtime 需要在 `StepOutcome.artifacts`、`WorkflowResult.manifest` 和 run manifest 中引用 ArtifactRef。

但 ArtifactRef 的 canonical 模型归 `07-STORAGE_AND_MEMORY_TARGET_ARCHITECTURE.md`，本文只要求 Workflow Runtime 能读取以下语义字段：

```text
artifact_id
run_id
step_id
artifact_type
path
content_type
created_at
redacted
metadata
```

不要在 Workflow Runtime 包内再生成一份 `ArtifactRef` 数据模型，避免和 Storage 模型分叉。

---

## 10. 最终态 Event 设计

### 10.1 Event Types

```text
workflow_started
workflow_paused
workflow_resumed
workflow_succeeded
workflow_failed
workflow_blocked
workflow_cancelled

step_scheduled
step_started
step_retry_scheduled
step_succeeded
step_failed
step_blocked
step_skipped

edge_evaluated
edge_traversed
edge_rejected

data_buffer_read
data_buffer_write
data_buffer_permission_denied

artifact_written
checkpoint_created
checkpoint_restored

human_review_requested
human_review_completed

budget_warning
budget_exceeded

policy_violation
secret_redacted
```

### 10.2 Workflow Event Payload

EventRecord 的 canonical 持久化模型归 `07-STORAGE_AND_MEMORY_TARGET_ARCHITECTURE.md` 的 EventStore 管理。

Workflow Runtime 只负责产生 workflow event payload，并至少提供以下字段给 EventStore：

```text
run_id
workflow_id
step_id
event_type
timestamp
payload
severity
trace_id
```

EventStore 负责补全 `event_id`、持久化、索引、回放和向 observability 系统转发。

### 10.3 EventBus

最终态不只是写 JSONL，还应该支持 EventBus：

```text
EventRecorder -> EventStore
EventRecorder -> EventBus
EventBus -> monitoring
EventBus -> web console
EventBus -> scheduler
EventBus -> alerting
```

---

## 11. 最终态 Policy 设计

### 11.1 RetryPolicy

```python
class RetryPolicySpec(BaseModel):
    max_retries: int = 0
    retry_delay_seconds: list[int] = Field(default_factory=list)
    backoff_strategy: str = "fixed"
    retry_on_error_types: list[str] = Field(default_factory=list)
    no_retry_on_error_types: list[str] = Field(default_factory=list)
```

### 11.2 TimeoutPolicy

```python
class TimeoutPolicySpec(BaseModel):
    timeout_seconds: int = 60
    on_timeout: str = "fail"
```

### 11.3 FailurePolicy

```python
class FailurePolicySpec(BaseModel):
    on_failure: str = "fail_workflow"
    fallback_step_id: str | None = None
    mark_as_blocked: bool = False
    allow_partial_success: bool = False
```

### 11.4 ResourcePolicy

```python
class ResourcePolicySpec(BaseModel):
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_cost_usd: float | None = None
    max_items: int | None = None
    max_parallelism: int | None = None
```

### 11.5 QualityPolicy

```python
class QualityPolicySpec(BaseModel):
    min_citation_coverage: float | None = None
    min_editor_score: float | None = None
    block_on_unsupported_claims: bool = True
    allow_rewrite_count: int = 1
```

---

## 12. 最终态并行与 Join

### 12.1 Parallel Fan-out

用于：

```text
parallel source fetching
parallel topic analysis
parallel entity extraction
parallel memory search
parallel report section drafting
```

### 12.2 Join Strategy

```text
wait_all
fail_fast
continue_on_partial_failure
threshold_success
```

### 12.3 Memory Conflict Strategy

并行 step 可能写同一个 key。

支持：

```text
error
last_wins
first_wins
merge_list
merge_dict
custom_reducer
```

News 默认应该优先使用：

```text
error
merge_list
custom_reducer
```

不建议默认 `last_wins`，因为容易覆盖 evidence。

---

## 13. 最终态 Human-in-the-loop

最终系统需要人工审阅节点：

```text
human_review
human_approval
human_edit
publish_approval
```

使用场景：

```text
报告发布前审批
高风险 claim 审查
source 可信度争议
LLM 多次 rewrite 失败
质量分低于阈值
```

HumanReviewStep 需要支持：

```text
pause workflow
write checkpoint
send review request
accept human decision
resume workflow
record decision as artifact
```

---

## 14. 最终态版本管理

WorkflowSpec 必须版本化。

```text
workflow_id = daily_intelligence
version = 1.3.0
```

需要支持：

```text
workflow spec registry
version pinning
run uses exact workflow version
old run replay uses old spec
new run uses latest active spec
migration note
deprecation
```

不能让旧 run 被新 workflow spec 解释错。

---

## 15. 最终态 Graph Validation

在执行前必须验证：

```text
start_step_id exists
all target_step_ids exist
no duplicate step_id
required_output_keys are declared in write_keys
read_keys can be produced by upstream steps or request
terminal steps reachable
no invalid edge condition
no unbounded loop without max visits
parallel write conflicts detected
all step runners registered
all implementation targets resolvable
all schemas valid
secret fields not in tracked spec
```

ValidationResult：

```python
class ValidationResult(BaseModel):
    passed: bool
    errors: list[ValidationErrorItem]
    warnings: list[ValidationWarningItem]
```

---

## 16. 最终态 Observability

Workflow Runtime 必须输出：

```text
run duration
step duration
step retries
step failures
LLM calls
tool calls
input tokens
output tokens
estimated cost
source success count
source failure count
citation coverage
editor score
artifact count
checkpoint count
human wait time
```

最终这些指标服务于：

```text
CLI diagnose
Web Console
MVP acceptance
cost dashboard
quality evaluation
agent improvement
```

---

## 17. News 目标态 Workflow 示例

### 17.1 Daily Intelligence Workflow

```text
scheduled_trigger / manual_trigger
  -> load_config
  -> collect_sources_parallel
  -> join_sources
  -> update_source_health
  -> normalize_sources
  -> deduplicate_sources
  -> rank_sources
  -> build_evidence
  -> retrieve_memory
  -> analyze
  -> verify_claims
  -> write_report
  -> citation_check
  -> editor_gate
      -> pass -> human_review_optional -> finalize
      -> rewrite_required -> rewrite_report -> citation_check
      -> blocked -> write_blocked_artifact
  -> persist_report
  -> index_memory
  -> publish_or_store
  -> notify_subscribers
```

### 17.2 Topic Intelligence Workflow

```text
topic_request
  -> expand_topic_queries
  -> collect_sources_parallel
  -> retrieve_historical_memory
  -> cluster_events
  -> build_timeline
  -> analyze_trend
  -> verify_claims
  -> write_topic_report
  -> quality_gate
  -> persist
```

### 17.3 Source Health Workflow

```text
scheduled_source_check
  -> probe_sources_parallel
  -> classify_source_errors
  -> update_source_health
  -> disable_down_sources
  -> write_health_report
```

---

## 18. 和 Hive 的最终取舍

### 18.1 借鉴 Hive

```text
Graph / Node / Edge 思想
SharedMemory 权限访问
EventLoopNode 与 GraphExecutor 分离
EdgeCondition: always/on_success/on_failure/conditional/llm_decide
ExecutionResult 记录 path、metrics、session_state
Node success criteria / judge retry
Human-in-the-loop pause/resume
Parallel branches
Event bus
Checkpoint
```

### 18.2 不照搬 Hive

```text
不把所有节点都变成 event_loop
不让 LLM 主导所有路由
不把 News 变成通用 Agent 生成平台
不把 evidence/citation/report 业务规则藏进通用 node
不默认 last_wins 合并并行结果
不让 SharedMemory 无结构增长
不忽视 artifact/replay 对情报系统的重要性
```

### 18.3 News 自己的目标态

```text
WorkflowSpec 而不是 GraphSpec
StepSpec 而不是 NodeSpec
DataBuffer 而不是 SharedMemory
WorkflowExecutor 而不是 GraphExecutor
StepRunnerRegistry 而不是单一 node_type
function / agent_loop / tool_batch / human_review / persist / memory_index 等多 StepType
Evidence / Citation / EditorGate 是一等业务节点
Artifact Replay 是一等系统能力
Lineage 是最终态核心能力
```

---

## 19. 最终态目录结构建议

```text
core/framework/workflow/
  __init__.py

  specs/
    workflow_spec.py
    step_spec.py
    edge_spec.py
    trigger_spec.py
    policy_spec.py
    validation.py

  runtime/
    executor.py
    context.py
    router.py
    lifecycle.py
    scheduler_hooks.py

  buffer/
    data_buffer.py
    scoped_buffer.py
    snapshot.py
    diff.py
    redaction.py

  runners/
    base.py
    function_runner.py
    agent_loop_runner.py
    tool_call_runner.py
    tool_batch_runner.py
    parallel_runner.py
    join_runner.py
    subworkflow_runner.py
    human_review_runner.py
    persist_runner.py
    memory_index_runner.py
    artifact_runner.py
    quality_gate_runner.py

  events/
    event_record.py
    event_recorder.py
    event_bus.py
    event_store.py

  artifacts/
    artifact_ref.py
    artifact_store.py
    filesystem_store.py
    manifest.py
    redaction.py

  checkpoints/
    checkpoint.py
    checkpoint_store.py
    resume.py

  stores/
    run_store.py
    local_json_run_store.py
    postgres_run_store.py

  errors/
    error_types.py
    exceptions.py
    error_policy.py

  metrics/
    models.py
    collector.py

  lineage/
    models.py
    tracker.py
```

---

## 20. 分阶段裁剪原则

虽然本文档是最终态，但后续实现可以按阶段裁剪。

裁剪原则：

```text
目标态先定完整边界
第一阶段只取最小闭环
每一阶段都不破坏最终架构命名和接口
后续功能是补 runner、policy、store，而不是推翻 runtime
```

也就是说，第一版不是另起炉灶，而是实现目标态中的一个小子集。

例如：

```text
第一阶段可以只实现：
WorkflowSpec
StepSpec
EdgeSpec
DataBuffer
ScopedDataBuffer
FunctionStepRunner
AgentLoopStepRunner
WorkflowExecutor
EventRecorder
FilesystemArtifactStore
RunManifest

但命名、接口、目录都要和最终态兼容。
```

---

## 21. 最终态验收标准

Workflow Runtime 最终完成时，应该满足：

```text
支持多 workflow 类型
支持 function / agent_loop / tool_batch / parallel / join / human_review / persist / memory_index 等 step
支持条件路由和失败路由
支持 checkpoint/resume
支持 artifact replay
支持 event bus
支持 run store
支持 DataBuffer 权限控制
支持 lineage
支持 retry / timeout / resource / quality policies
支持 graph validation
支持并行执行和 join
支持 human-in-the-loop
支持 workflow versioning
支持 CLI/API/Web Console 读取运行状态
```

---

## 22. 总结

News Workflow Runtime 的最终目标不是一个简单 DAG executor，也不是 Hive 的复制品。

它应该是：

```text
面向情报生产的可审计 Workflow Engine
```

它吸收 Hive 的 graph、shared memory、event loop、edge、checkpoint 思想，但在 News 中要进一步强化：

```text
真实 source
evidence lineage
citation quality
report artifacts
human review
memory indexing
run replay
workflow versioning
production observability
```

后续 MVP、第一版、第二版都应该从这个最终态目标中裁剪实现，而不是用第一版的简单实现反向定义系统上限。

---
# 本版保留说明

以上内容为原目标态文档主体内容，已完整保留。下面追加的是 v2.0 设计书级补强，用于把原目标态说明转化为更可开发、可验收、可维护的工程设计书。

---
# v2.0 设计书级补强：Workflow Runtime 工程化设计

> 本节是在原 v1.x 目标态内容之后追加的设计书级补强。原文中的 Hive/Burr/Dagu/Prefect/Hamilton/Dagster 参考分析、目标态模型、最终态 workflow 示例全部保留。本节只做工程化收敛：如何开发、如何落代码、如何验收、如何避免过度抽象。

## A. 本模块最终职责

Workflow Runtime 是流程执行内核，负责“流程怎么走”。

它拥有：

```text
WorkflowSpec
StepSpec
EdgeSpec
DataBuffer
ScopedDataBuffer
StepRunner
StepRunnerRegistry
WorkflowExecutor
WorkflowRunner
WorkflowResult
WorkflowRunStatus
WorkflowEvent
```

它不拥有：

```text
ArtifactRef canonical model
RunStore canonical protocol
ArtifactStore canonical protocol
CheckpointStore canonical protocol
ReportRecord
TaskStatus
ReportStatus
LLM provider SDK
Tool execution internals
```

这些分别归 Storage、Worker、Evidence/Quality、LLM Layer、ToolRuntime。

## B. 推荐开发顺序

```text
P2.1: WorkflowSpec / StepSpec / EdgeSpec 数据模型
P2.2: DataBuffer + read_keys/write_keys 校验
P2.3: FunctionStepRunner
P2.4: WorkflowExecutor 顺序执行
P2.5: Edge condition: always/on_success/on_failure
P2.6: WorkflowRunner 装配入口
P2.7: manifest/events/artifact hooks
P2.8: validation
P6: AgentLoopStepRunner
P7+: parallel/join/human_review/subworkflow
```

不要第一版就写 parallel、subworkflow、human review。否则容易框架复杂但主链路不稳。

## C. 核心执行算法

```text
validate workflow spec
create run context
initialize DataBuffer from request
resolve start step
while current step exists:
  create ScopedDataBuffer
  run StepRunner
  write StepOutcome
  persist event
  update DataBuffer
  choose next edge
  check max step visits / budget / cancellation
return WorkflowResult
```

## D. StepSpec 必须表达的字段

```python
class StepSpec(BaseModel):
    step_id: str
    name: str
    step_type: StepType
    implementation: str | None = None

    read_keys: list[str] = Field(default_factory=list)
    write_keys: list[str] = Field(default_factory=list)

    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None

    retry_policy: RetryPolicySpec | None = None
    timeout_seconds: int | None = None
    artifact_policy: ArtifactPolicySpec | None = None
    quality_policy: QualityPolicySpec | None = None

    max_visits: int = 1
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
```

## E. DataBuffer 设计原则

DataBuffer 不应该只是裸 dict。

它必须支持：

```text
get(key)
set(key, value)
snapshot()
diff(before, after)
redacted_view()
scoped(read_keys, write_keys)
serialize()
```

ScopedDataBuffer 必须阻止 step 读取未声明的 key，也阻止写入未声明的 key。

## F. EdgeCondition 设计

第一阶段只实现：

```text
always
on_success
on_failure
```

第二阶段引入：

```text
conditional
quality_pass
quality_rewrite_required
quality_blocked
```

最终态才引入：

```text
human_approved
human_rejected
budget_exceeded
llm_decide
```

`llm_decide` 只能用于辅助路由，不能用于安全、发布、质量通过等强治理决策。

## G. WorkflowRunner 边界

WorkflowRunner 只做装配：

```text
load profile
load workflow spec
build stores
build llm router
build tool registry
build step runner registry
call WorkflowExecutor.execute()
```

WorkflowRunner 不写：

```text
source parse
report writing
citation checker
database SQL
LLM prompt
tool execution
```

## H. 代码组织建议

初期只用一个文件：

```text
runtime/workflow.py
```

内部 section：

```text
Constants
Errors
Models
Policies
DataBuffer
StepRunner Protocols
Built-in StepRunners
WorkflowExecutor
WorkflowRunner
Validation
Helpers
```

当超过 2200 行再拆：

```text
runtime/workflow_models.py
runtime/workflow_executor.py
runtime/workflow_runners.py
```

不要一开始拆成 specs/buffer/executor/registry 十几个文件。

## I. 测试矩阵

```text
test_workflow_spec_validation
test_data_buffer_read_write_scope
test_function_step_runner_success
test_function_step_runner_failure
test_edge_on_success
test_edge_on_failure
test_manifest_written
test_step_failure_has_step_id
test_daily_workflow_smoke
```

## J. 验收清单

```text
[ ] Daily workflow 能通过 WorkflowExecutor 执行。
[ ] manifest 中能看到 step path。
[ ] 每个 step 有 started/succeeded/failed event。
[ ] Step 失败能定位 step_id 和 error_code。
[ ] DataBuffer 不允许越权读写。
[ ] WorkflowRunner 不包含业务逻辑。
[ ] WorkflowRunStatus 不混入 TaskStatus/ReportStatus。
```

## K. 当前代码进度映射（2026-05-13）

本节不是替代前文目标态，而是把当前仓库实现映射到目标态，作为后续继续开发的落地基线。Workflow Runtime 已经不是空白模块，后续应在现有结构上收口、补齐、增强，不从零重写。

### K.1 已完成或基本可用

```text
core/framework/specs/workflow_spec.py
  WorkflowSpec / StepSpec / EdgeSpec
  StepType / EdgeCondition / StepStatus / WorkflowStatus
  RetryPolicySpec / FailurePolicySpec / TimeoutPolicySpec / ResourcePolicySpec
  QualityPolicySpec / ArtifactPolicySpec / LineagePolicySpec
  WorkflowSpecRegistry
  graph validation、read_keys/write_keys 可达性校验、runner 注册校验入口

core/framework/workflow/buffer.py
  DataBuffer / ScopedDataBuffer
  DataBufferSnapshot / DataBufferDiff
  read_keys/write_keys 权限控制

core/framework/workflow/manifest.py
  RUN_MANIFEST_SCHEMA_VERSION = newsroom.workflow_run_manifest.v1
  build_run_manifest()
  REQUIRED_RUN_ARTIFACTS
  manifest_schema_version()
  run manifest 已显式版本化，后续 replay/debug/audit schema 演进应优先从这里收口

core/framework/workflow/executor.py
  WorkflowExecutor
  workflow validate
  step execution
  retry / timeout / fallback / blocked / pause
  routing
  checkpoint
  manifest
  events
  artifact
  data buffer snapshot/diff
  error artifact

core/framework/workflow/routing.py
  RoutingEngine
  success/failure/conditional/quality/human/budget/source route
  llm_decide 仅作为 route hint，不参与强治理决策

core/framework/workflow/step_runner.py
  StepRunnerRegistry
  build_default_step_runner_registry()
  FunctionStepRunner
  ToolCallStepRunner / ToolBatchStepRunner
  AgentLoopStepRunner
  ParallelGroupStepRunner
  SubworkflowStepRunner
  RouterStepRunner / JoinStepRunner
  QualityGateStepRunner / HumanReviewStepRunner
  ArtifactStepRunner

core/framework/runner.py
  WorkflowRunner 作为可编程装配入口
  WorkflowRunIndexer 负责 artifact/event/lineage 索引桥接
  ArtifactManager / event store / lineage store / checkpoint store / redactor 装配

workflows/daily_intelligence/runner.py
  DailyIntelligenceRunner 已接入 WorkflowRunner
  保留 connector / source registry / llm client 装配入口
  保留依赖实例状态的 collect_sources / draft_report

workflows/daily_intelligence/spec.py
  build_daily_intelligence_workflow()
  WORKFLOW_ID / WORKFLOW_VERSION / profile 常量
  daily workflow 使用 WorkflowSpec / StepSpec / EdgeSpec

workflows/daily_intelligence/steps.py
  require_sources / normalize_sources / deduplicate_sources / rank_sources
  build_evidence / quality_gate
  daily step functions 使用 ScopedDataBuffer
```

### K.2 已有雏形，但需要继续收口

```text
StepRunner 默认装配
  已新增 build_default_step_runner_registry()。
  function / router / join / quality_gate / human_review / artifact / parallel_group 可默认注册。
  tool_call / tool_batch / persist / memory_index / notification 依赖注入 ToolRegistry 后注册。
  agent_loop 依赖注入 AgentRunner + agent_registry 后注册。
  subworkflow 依赖注入 workflow_registry 后注册。

WorkflowRunner 边界
  WorkflowRunner 只负责装配并调用 WorkflowExecutor。
  artifact/event/lineage 索引已经收进 WorkflowRunIndexer。
  WorkflowRunIndexer 仍是 Workflow Runtime 到 Storage 的轻量桥接，不在 Runtime 内重新定义 Storage canonical model。

ParallelGroupStepRunner
  支持 function branch 并行执行、输出合并、冲突策略和 branch_results。
  当前仍是本地线程池级别，不是分布式并行调度。

SubworkflowStepRunner
  支持父 workflow 中调用子 WorkflowSpec。
  当前复用注入的 StepRunnerRegistry 和 ArtifactManager，run_id 使用父子层级命名。
  后续如需更严格隔离，再补独立 registry/profile/store 策略。

ToolCallStepRunner / ToolBatchStepRunner
  已接入 ToolRuntime。
  当前将 persist / memory_index / notification 映射为 tool-call 类 step。
  业务持久化语义仍归 Storage/Memory 与 Tool Runtime，不写进 WorkflowExecutor。

AgentLoopStepRunner
  已接入 AgentRunner。
  success / blocked / failed 能映射为 StepOutcome。
  AgentLoop 自身策略、judge、conversation 持久化归 AgentLoop 模块，不放进 WorkflowExecutor。
```

### K.3 暂不做或不在本模块做

```text
不重写 WorkflowExecutor / WorkflowRunner / StepRunnerRegistry / DataBuffer / RoutingEngine。
不新增另一套 graph runtime。
不让 Workflow Runtime 直接依赖 CLI / API / MCP。
不让 Workflow Runtime 直接写 Source / Evidence / Report 业务逻辑。
不在 Workflow Runtime 中重新定义 ArtifactRef / RunStore / ArtifactStore / CheckpointStore。
不把 LLM_DECIDE 用于安全、审批、质量通过、发布等强治理决策。
不在本轮做分布式 worker、复杂 scheduler、Web UI 或人工审核平台。
不继续大拆 daily_intelligence runner；当前只做了最小安全拆分。
```

## L. 基于当前代码继续开发的落地说明

### L.1 默认装配入口

后续新增 step runner 时，优先接入 `build_default_step_runner_registry()`，不要在不同 runner、service、test 中各自手写一套默认注册列表。

依赖注入规则：

```text
FunctionStepRunner / ParallelGroupStepRunner
  依赖 FunctionStepRegistry

ToolCallStepRunner / ToolBatchStepRunner
  依赖 ToolRegistry
  可选依赖 ArtifactManager / run_id / approval_store / secret_provider

AgentLoopStepRunner
  依赖 AgentRunner / agent_registry

SubworkflowStepRunner
  依赖 workflow_registry / StepRunnerRegistry

ArtifactStepRunner
  可先注册，运行前由 WorkflowExecutor 注入 ArtifactManager / run_id
```

### L.2 WorkflowRunner 边界

`WorkflowRunner` 的长期边界保持为：

```text
build ArtifactManager
build default StepRunnerRegistry
build WorkflowExecutor
call execute / resume_from_checkpoint
convert WorkflowResult -> RunResult
call WorkflowRunIndexer
```

`WorkflowRunner` 不应下沉为业务 runner，也不应包含 source parse、report writing、citation checker、LLM prompt、tool execution、database SQL。

### L.3 daily_intelligence runner 收口方案

`workflows/daily_intelligence/runner.py` 已完成最小安全拆分。当前状态：

```text
workflows/daily_intelligence/runner.py
  保留 DailyIntelligenceRunner
  保留 connector / source registry / llm client 装配入口
  保留 run() 对 WorkflowRunner 的调用
  保留依赖 runner 实例状态的 collect_sources / draft_report

workflows/daily_intelligence/spec.py
  已放入 build_daily_intelligence_workflow()
  已放入 WORKFLOW_ID / WORKFLOW_VERSION / profile 常量

workflows/daily_intelligence/steps.py
  已放入无状态 daily workflow step functions
  包含 require_sources / normalize_sources / deduplicate_sources / rank_sources
  build_evidence / quality_gate

tests/workflows/test_daily_intelligence_steps.py
  已补 focused tests
  覆盖 spec validate、require_sources failure、source step chain、evidence + quality gate、daily runner smoke
```

后续如果继续拆，只做渐进式整理：

```text
workflows/daily_intelligence/runner.py
  可继续把 source connector dispatch helper 分组整理，但不改变 public runner API

workflows/daily_intelligence/steps.py
  focused unit tests 已有，后续只在新增 step 行为时补小范围用例
```

不要把 source connector、LLM client、health manager 的实例装配强行搬进 step 函数文件；它们仍属于 workflow-specific runner 的装配边界。

## M. 当前测试验收补充

当前测试应继续覆盖：

```text
StepRunnerRegistry 默认注册
ParallelGroupStepRunner success / conflict / branch output merge
SubworkflowStepRunner success / failure
ToolCallStepRunner / ToolBatchStepRunner success routing
AgentLoopStepRunner fake AgentRunner success / blocked / failed
WorkflowRunner 默认装配不破坏 daily workflow smoke
WorkflowRunner prebuilt StepRunnerRegistry / default artifact runner assembly
Daily workflow spec / stateless steps focused tests
WorkflowExecutor 原有 retry / timeout / fallback / fan-out / pause/resume / blocked / routing failure
```

## N. 当前增量记录（2026-05-13）

### N.1 Advanced StepRunner metrics

本轮在不改变执行语义的前提下，补齐 advanced runner 的 `StepOutcome.metrics`：

```text
ToolCallStepRunner
  记录 tool_name、tool_call_id、tool_status、elapsed_ms、output_bytes、artifact_ref_count、approval_required

ToolBatchStepRunner
  记录 tool_call_count、succeeded_count、failed_count、blocked_count、approval_required_count、timeout_count、status_counts、artifact_ref_count、output_bytes、max_workers

ParallelGroupStepRunner
  记录 branch_count、succeeded_branch_count、conflict_strategy、max_workers、branch_ids、output_keys、output_key_count

SubworkflowStepRunner
  记录 child_run_id、child_workflow_id、child_workflow_version、child_status、child_step_count、child_artifact_count、child_event_count、child_manifest_path、child_events_path
```

这些 metrics 只用于 manifest / step_results / debug / audit，不改变 routing、quality、human approval、publish 等强治理决策。LLM route hint 仍然只能作为 hint 使用。

### N.2 Manifest artifact registration

本轮把 run manifest 的 artifact 注册收口到 `core/framework/workflow/manifest.py`：

```text
register_manifest_artifact()
  统一校验 artifact key 和相对路径。
  禁止 absolute path 和 .. path traversal。
  将 Windows 路径分隔符规范化为 manifest 中的 POSIX 风格路径。

register_manifest_step_artifact()
  统一记录 StepOutcome.artifacts 到 step_artifacts。
  同时注册 step.<step_id>.<artifact_type>.<artifact_id> artifact key。

manifest_step_artifact_key()
  保持 step artifact key 生成逻辑集中，避免 executor 内继续散落字符串拼接。
```

`WorkflowExecutor` 仍然负责决定哪些 artifact 要写，但不再直接散写 `manifest["artifacts"][...] = ...`。这一步不改变 manifest schema，只增强 manifest 写入边界和路径安全。

### N.3 Run manifest validation

本轮增加 `validate_run_manifest()`，并在 `WorkflowExecutor` 写 `manifest.json` 前执行：

```text
validate_run_manifest()
  校验 schema_version 是否为当前支持版本。
  校验 run_id / workflow_id / workflow_version / profile / status / started_at 等基础字段。
  校验 path / steps / artifacts 的结构。
  校验 REQUIRED_RUN_ARTIFACTS 中定义的必需 artifact 是否存在。
  校验 artifact path 仍然满足相对路径和无 path traversal 约束。
  在终态 manifest 中校验 succeeded -> output、paused/waiting_for_human -> pause、failed/blocked/cancelled/budget_exceeded -> error。
  校验 step_artifacts 中的 artifact 是否同步存在于 artifacts map。
```

这一步保持 manifest 输出格式不变，只把“manifest 必须是可 replay/debug/audit 的有效结构”变成代码约束。
