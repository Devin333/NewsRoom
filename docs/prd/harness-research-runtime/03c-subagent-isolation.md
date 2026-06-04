# 阶段 3C：SubAgent Isolation

## 阶段目标

建立 Harness-controlled 子 Agent 隔离机制。框架层只定义通用隔离协议、显式传参、上下文裁剪、工具白名单、memory namespace、预算和 transcript；业务层按 workflow 声明具体子 Agent 角色。

本阶段不实现任何具体业务角色，不出现 `Research`、`paper_radar` 或旧业务专有名词。后续 Research、Reader Repair、Benchmark 验证、Skill Evolution 都通过这个通用机制复用子 Agent 隔离。

## 真实依赖与接口预留

| 类型 | 内容 |
| --- | --- |
| 真实实现依赖 | 阶段 3 的 SubAgentWorkerPort、MemoryPort、MCPToolPort、QualityGatePort、ArtifactPort。 |
| 真实输出 | `SubAgentSpec`、`SubAgentInvocation`、`SubAgentContextEnvelope`、`SubAgentHandoff`、独立 transcript refs。 |
| 接口预留 | 阶段 3D 会把通用 `ContextEnvelope` 投影成 `SubAgentContextEnvelope`；阶段 3A 会复用 handoff 做 skill candidate/evaluator/promoter 隔离。 |
| 禁止提前实现 | 不在本阶段实现 ContextAssembler、RAG session controller、skill evolution 生命周期或 Research 子 Agent。 |

## 为什么需要

你项目里的旧多 Agent 代码已经出现过共享 workspace / session access policy 的雏形，说明项目确实需要多 Agent 协作。但新架构不能继续依赖旧业务定制实现，也不能把所有子 Agent 放进同一个上下文窗口。

必须隔离的风险：

| 风险 | 后果 |
| --- | --- |
| 共享 raw context | 生成型 worker 的猜测污染验证型 worker。 |
| 共享 private history | 子 Agent 互相看到草稿、失败尝试、私有推理。 |
| 共享 tool allowlist | 一个子 Agent 间接借用另一个子 Agent 的工具权限。 |
| 共享 memory namespace | 当前任务读到不该读的用户记忆、业务记忆或 skill evolution 经验。 |
| 隐式 handoff | Harness 无法审计谁把什么信息传给了谁。 |
| 共用 transcript | replay 时无法判断哪个子 Agent 影响了哪个结果。 |

## 核心原则

| 原则 | 要求 |
| --- | --- |
| Harness 创建子 Agent | LLM 不能自行启动、选择或路由子 Agent。 |
| 独立上下文 | 每个子 Agent 只收到 Harness 构造的 `SubAgentContextEnvelope`；阶段 3D 完成后可由 `ContextEnvelope` 投影生成。 |
| 显式传参 | 子 Agent 之间只能通过 Harness-approved `SubAgentHandoff` 交换结构化 payload。 |
| 工具白名单 | 每个子 Agent 的工具权限独立声明、独立校验。 |
| 记忆命名空间隔离 | 每个子 Agent 只能读写 workflow 允许的 memory namespace。 |
| 独立 transcript | 每个子 Agent invocation 都必须有独立 transcript，并被父 run trace 引用。 |
| 纯函数 gate | 上下文边界、handoff schema、工具权限、memory 权限、预算和输出 schema 都由 deterministic gate 校验。 |

## 新增目录

```text
framework/harness/subagents/
  __init__.py
  models.py
  context.py
  runtime.py
  handoff.py
  policy.py
  gates.py
  transcript.py
  fake.py
```

如果实现时已有 `framework/agent/session` 可复用，应只复用 domain-neutral 的模型思想、store pattern、access policy 和 context assembler 经验；不能让旧 `framework.agent` 或旧 `paper_radar` 控制新 Harness 流程。

## 核心模型

### SubAgentSpec

字段建议：

```text
subagent_id
role
purpose
input_schema
output_schema
allowed_tools
allowed_memory_namespaces
context_policy
budget
metadata
```

约束：

- `subagent_id` 必须稳定。
- `role` 是 workflow 内角色名，不是框架枚举。
- `allowed_tools` 必须显式声明。
- `allowed_memory_namespaces` 必须显式声明。
- `input_schema` 和 `output_schema` 必须可验证。

### SubAgentInvocation

字段建议：

```text
invocation_id
parent_run_id
child_run_id
workflow_id
step_id
subagent_spec
input_refs
context_envelope
budget_snapshot
metadata
```

### SubAgentContextEnvelope

字段建议：

```text
child_run_id
parent_run_id
subagent_id
role
allowed_input_refs
context_pack
memory_context_refs
tool_policy_ref
budget_snapshot
redaction_report
metadata
```

禁止包含：

```text
parent_raw_messages
sibling_raw_history
sibling_private_notes
hidden_prompt
unapproved_memory
unapproved_tool_results
full_transcript
```

### SubAgentHandoff

字段建议：

```text
handoff_id
from_subagent_id
to_subagent_id
parent_run_id
payload
payload_schema
input_refs
artifact_refs
redaction_report
created_at
metadata
```

约束：

- handoff payload 必须结构化。
- handoff payload 必须通过 schema gate。
- handoff 只能传 approved output，不传 private notes。
- 大内容必须用 artifact refs。

### SubAgentResult

字段建议：

```text
invocation_id
child_run_id
subagent_id
status
output
artifact_refs
memory_write_candidates
tool_call_refs
warnings
errors
transcript_ref
metadata
```

禁止字段：

```text
next_step
quality_passed
write_memory
publish_artifact
promote_skill
halt_workflow
```

## PLAN / EXECUTE / VERIFY 流程

### PLAN

Harness 根据 workflow spec 和当前 state 选择是否调用子 Agent。

PLAN 阶段必须生成：

```text
SubAgentInvocationPlan
SubAgentContextPolicy
SubAgentToolPolicy
SubAgentMemoryPolicy
SubAgentBudget
```

LLM 不能决定调用哪个子 Agent，也不能决定把 sibling context 传给谁。

### EXECUTE

Harness 通过 `SubAgentRuntime` 调用子 Agent worker：

```text
SubAgentRuntime.invoke(invocation)
```

要求：

- 每次 invocation 使用独立 `child_run_id`。
- 每次 invocation 使用独立 context envelope。
- 每次 invocation 使用独立 transcript。
- 子 Agent 只能通过端口访问工具、记忆、RAG 和 skill。
- 子 Agent 不能直接写父 HarnessState。

### VERIFY

每次 invocation 前后必须经过 gate：

| Gate | 校验内容 | 失败处理 |
| --- | --- | --- |
| `SubAgentContextBoundaryGate` | context envelope 不包含 parent raw messages、sibling history、private notes、hidden prompt。 | fail 或 rebuild context。 |
| `SubAgentInputSchemaGate` | 输入符合 declared input schema。 | fail。 |
| `SubAgentToolAllowlistGate` | tool calls 只使用 allowed_tools。 | reject tool call 或 fail。 |
| `SubAgentMemoryNamespaceGate` | memory recall/write 只访问 allowed namespaces。 | reject memory op 或 fail。 |
| `SubAgentHandoffSchemaGate` | handoff payload 符合 schema，不含 private fields。 | fail 或 redact。 |
| `SubAgentOutputSchemaGate` | 输出符合 schema，无非法流程字段。 | replan 或 fail。 |
| `SubAgentBudgetGate` | 不超过 child budget 和 parent run budget。 | halted。 |
| `SubAgentTranscriptGate` | invocation transcript 已完整写入。 | fail。 |

## 子 Agent 之间怎么传信息

错误方式：

```text
SubAgent A raw context -> SubAgent B
SubAgent A private notes -> SubAgent B
SubAgent A full transcript -> SubAgent B
```

正确方式：

```text
SubAgent A output candidate
-> HandoffSchemaGate
-> Harness state / artifact ref
-> SubAgent B context envelope
```

跨 Agent 信息必须显式建模，例如：

```text
CandidatePayload
VerificationInput
RepairCandidate
EvidenceSummary
BenchmarkClaimCandidate
SkillPatchCandidate
```

这些名字由业务 workflow 定义，框架只处理 schema、refs、权限和 transcript。

## 与 RAG / Memory / Skill 的关系

### RAG

子 Agent 可以请求 RAG，但必须通过阶段 3B 的 Harness RAG session controller：

```text
SubAgent
-> RAG request candidate
-> Harness RAG gate
-> RAGContextPack
-> SubAgent context envelope
```

子 Agent 不能自己进入无限检索循环。

### Memory

子 Agent 可以输出 memory write candidate，但不能直接 commit：

```text
SubAgentResult.memory_write_candidates
-> MemoryNamespaceGate
-> MemoryWriteGate
-> Harness commit decision
```

### Skill

子 Agent 可以调用 active skill，也可以在 skill evolution workflow 中生成 skill candidate，但不能直接发布 active skill。

## Trace / Transcript 要求

父 Harness transcript 必须记录：

```text
subagent_invocation_planned
subagent_context_built
subagent_started
subagent_tool_call_allowed
subagent_tool_call_rejected
subagent_memory_recall_allowed
subagent_memory_recall_rejected
subagent_handoff_created
subagent_handoff_verified
subagent_completed
subagent_failed
subagent_halted
```

子 Agent transcript 必须记录：

```text
child_run_id
parent_run_id
subagent_id
context_envelope_ref
input_refs
tool_call_refs
memory_context_refs
output_ref
gate_results
budget_snapshot
errors
timestamps
```

Trace 必须能解释：

- 子 Agent 为什么被调用。
- 子 Agent 看到了哪些 context refs。
- 哪些 sibling 信息被拒绝。
- 子 Agent 使用了哪些工具和 memory namespace。
- handoff 传了什么结构化 payload。
- invocation 为什么 pass、fail、replan 或 halted。

## Fake implementation

新增：

```text
FakeSubAgentRuntime
FakeSubAgentWorker
FakeSubAgentContextBuilder
FakeSubAgentGateSuite
FakeSubAgentTranscriptStore
```

Fake 必须支持：

- 输出合法 payload。
- 输出非法流程字段。
- 尝试访问未授权 tool。
- 尝试访问未授权 memory namespace。
- 尝试读取 sibling private notes。
- 超出 child budget。

## 测试要求

新增：

```text
tests/framework/harness/subagents/test_subagent_models.py
tests/framework/harness/subagents/test_context_boundary_gate.py
tests/framework/harness/subagents/test_tool_allowlist_gate.py
tests/framework/harness/subagents/test_memory_namespace_gate.py
tests/framework/harness/subagents/test_handoff_schema_gate.py
tests/framework/harness/subagents/test_subagent_runtime.py
tests/framework/harness/subagents/test_subagent_transcript.py
tests/framework/harness/subagents/test_fake_subagent_runtime.py
```

必须覆盖：

- 子 Agent 只能看到 context envelope，不能看到 parent raw messages。
- 子 Agent 不能读取 sibling private notes。
- 子 Agent 不能继承 sibling tool allowlist。
- 未授权 tool call 被拒绝。
- 未授权 memory namespace 被拒绝。
- handoff payload 必须符合 schema。
- 输出里的 `next_step`、`quality_passed`、`write_memory`、`promote_skill` 被拒绝或剥离。
- 子 Agent budget 耗尽后受控 halted。
- 每个 invocation 有独立 transcript。
- 父 trace 能引用子 transcript。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- `framework/harness/subagents` 有完整模型、context builder、runtime、handoff、policy、gate、transcript、fake。
- 子 Agent 不能共享 raw context、private history、tool allowlist 或 memory namespace。
- 所有跨子 Agent 信息传递必须通过 Harness-approved handoff。
- 子 Agent transcript 可独立导出，并能被父 run trace 引用。
- 不接 Research，不做 UI。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/03c-subagent-isolation.md。
要求：
1. 在 framework/harness/subagents 下实现通用子 Agent 隔离机制，不写任何 Research、paper_radar 或旧业务专有逻辑。
2. 定义 SubAgentSpec、SubAgentInvocation、SubAgentContextEnvelope、SubAgentHandoff、SubAgentResult、SubAgentToolPolicy、SubAgentMemoryPolicy、SubAgentTranscript。
3. Harness 创建子 Agent invocation；LLM 不能决定调用哪个子 Agent、不能决定 handoff、不能决定 workflow routing。
4. 每个子 Agent 必须有独立 child_run_id、context envelope、tool allowlist、memory namespace、budget 和 transcript。
5. 子 Agent 之间只能通过 Harness-approved SubAgentHandoff 传结构化 payload；不能共享 raw context、private notes、hidden prompt、sibling history。
6. 实现 SubAgentContextBoundaryGate、SubAgentInputSchemaGate、SubAgentToolAllowlistGate、SubAgentMemoryNamespaceGate、SubAgentHandoffSchemaGate、SubAgentOutputSchemaGate、SubAgentBudgetGate、SubAgentTranscriptGate。
7. 子 Agent 输出里的 next_step、quality_passed、write_memory、publish_artifact、promote_skill、halt_workflow 必须被 gate 拒绝或剥离。
8. 添加 subagent models、context boundary、tool allowlist、memory namespace、handoff schema、runtime、transcript、fake runtime 测试。
9. 运行 python -m scripts.dev compile、python -m pytest tests/framework/harness -q、openspec validate harness-research-runtime --strict。
10. 修改完成后提交。
全部回复和问题用中文。
```
