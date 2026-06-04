# 阶段 3：七层端口

## 阶段目标

建立 Harness 可调度的七层端口：LLM、Skills、SubAgent、Retrieval、Memory、MCP、Quality/Artifact。每个端口都要可替换、可 fake、可单测。

## 七层职责

| 层 | 职责 | Harness 决策点 |
| --- | --- | --- |
| LLM Worker | 生成候选结构化内容。 | 是否调用、用哪个输入、是否采纳。 |
| Skills | 执行确定性业务能力，暴露 versioned skill 能力。 | 是否执行、参数是否有效、结果是否进入 state；是否允许进入离线进化流程。 |
| SubAgent | 执行受控子任务。 | 调谁、预算、输入、验收。 |
| Retrieval | 返回 EvidencePack/ContextPack。 | 检索时机、检索范围、证据是否足够。 |
| Memory | 读写长期/短期记忆。 | 何时读、何时写、写什么。 |
| MCP | 外部工具协议边界。 | 权限、审批、超时、审计、结果截断。 |
| Quality/Artifact | 验收和发布运行产物。 | 是否通过、返工、失败、发布。 |

## 新增目录

```text
framework/harness/workers/
  ports.py
  fake.py
framework/harness/retrieval/
  __init__.py
  ports.py
  request.py
  evidence_pack.py
  fake.py
framework/harness/rag/
  __init__.py
  models.py
  session.py
  gates.py
  fake.py
framework/harness/memory/
  __init__.py
  ports.py
  fake.py
framework/harness/skills/
  __init__.py
  ports.py
  fake.py
framework/harness/skills/evolution/
  __init__.py
  models.py
  ports.py
  fake.py
framework/harness/mcp/
  __init__.py
  ports.py
  policy.py
  fake.py
framework/harness/artifacts/
  __init__.py
  ports.py
  fake.py
```

如果已有 `framework/skills`、`framework/tool`、`framework/memory` 可复用，不要复制实现；Harness 层只定义控制平面端口和 adapter 边界。

## 端口定义

### LLMWorkerPort

输入：

```text
step spec
context payload
run metadata
```

输出：`HarnessWorkerResult`

约束：

- 只返回候选内容。
- 不返回流程决策。
- 不直接调用工具。

### SkillWorkerPort

输入：

```text
skill name
validated input
execution context
```

输出：`HarnessWorkerResult`

约束：

- 技能必须有 schema。
- 输入验证失败是 worker failure，不是 Harness 崩溃。
- 运行时必须记录 skill name、skill version、package hash，便于 trace、experience 和 rollback。
- Skill 执行结果只能进入候选 output；是否采纳、是否写入 memory、是否发布 artifact 由 Harness 决定。

### SkillEvolutionPort

能力：

```text
collect_experience(request)
propose_candidate(request)
evaluate_candidate(request)
promote_candidate(request)
rollback_release(request)
```

输出：

```text
SkillExperience
SkillCandidate
SkillEvaluationResult
SkillPromotionDecision
SkillRelease
SkillRollbackPlan
```

约束：

- LLM optimizer 只能生成 skill patch candidate，不能直接发布。
- candidate 必须先进入 candidate store，不能覆盖 active skill。
- held-out eval 没有严格改进不得晋升。
- active skill 必须版本化，且每次发布都有 rollback plan。
- 普通业务 run 只能产生 experience，不自动触发 promotion。

### SubAgentWorkerPort

输入：

```text
subagent id
task payload
budget
context refs
```

输出：`HarnessWorkerResult`

约束：

- 子 Agent 不能自己调度其他顶层 step。
- 子 Agent 输出要结构化。

### RetrievalPort

输入：`RetrievalRequest`

输出：`EvidencePack`

EvidencePack 必须包含：

```text
evidence_id
title
summary
source_refs
confidence
freshness
lineage
metadata
```

约束：

- RetrievalPort 只负责一次检索或读取 source，不负责多轮 RAG loop。
- 多轮搜索、补查、上下文组装和停止条件由阶段 3B 的 `framework/harness/rag` 控制。
- RetrievalPort 不能决定 evidence 是否最终采纳。

### Bounded Agentic RAG

阶段 3 只需要预留 RAG 所需端口兼容性，完整实现放在 [03b-bounded-agentic-rag.md](03b-bounded-agentic-rag.md)。

要求：

- `RetrievalRequest`、`EvidencePack`、`MemoryPort`、`MCPToolPort` 和 `QualityGatePort` 的数据结构要能被 RAG session controller 组合使用。
- EvidencePack 必须保留 `lineage`、`source_refs`、`metadata`，否则 RAG source/evidence gate 无法做确定性校验。
- fake retrieval 数据要包含可验证的 source refs、section refs、citation refs，不要只返回纯文本。

### MemoryPort

能力：

```text
recall(request)
propose_write(candidate)
commit_write(approved_write)
```

约束：

- LLM 可以生成 memory candidate。
- Harness 决定是否 commit。

### MCPToolPort

能力：

```text
list_tools()
call_tool(request)
```

约束：

- side effect tool 必须支持 approval policy。
- 结果过大要转 artifact ref。
- 记录 audit event。

### ArtifactPort

能力：

```text
write_artifact(request)
read_artifact(ref)
```

约束：

- Harness 负责决定何时发布。
- worker 只能返回 artifact candidate 或 content ref。

## Fake implementation

每个端口必须有 fake：

```text
FakeLLMWorker
FakeSkillWorker
FakeSkillEvolutionPort
FakeSubAgentWorker
FakeRetrievalPort
FakeRAGSessionController
FakeRAGPlanner
FakeMemoryPort
FakeMCPToolPort
FakeQualityGate
FakeArtifactPort
```

Fake 必须用于 Harness 单测，不允许测试依赖真实 LLM、真实 Qdrant、真实 MCP server。

## 测试要求

新增：

```text
tests/framework/harness/ports/test_llm_worker_port.py
tests/framework/harness/ports/test_retrieval_port.py
tests/framework/harness/rag/test_rag_port_compatibility.py
tests/framework/harness/ports/test_memory_port.py
tests/framework/harness/ports/test_mcp_policy.py
tests/framework/harness/ports/test_fake_runtime.py
tests/framework/harness/skills/evolution/test_skill_evolution_port.py
```

必须覆盖：

- 所有 fake 可被 Harness 调用。
- EvidencePack 可序列化。
- EvidencePack 有 lineage 和 source refs，可被 RAG gate 使用。
- Memory candidate 不会自动写入。
- Skill candidate 不会自动覆盖 active skill。
- MCP side effect 请求未批准时拒绝。
- Artifact 写入返回 ref。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- 七层端口完整。
- Skill evolution 端口和 fake implementation 完整，但真正生命周期细节在阶段 3A 实现。
- Retrieval / Memory / MCP / QualityGate / Artifact 端口可支撑阶段 3B 的 Bounded Agentic RAG。
- 每层 fake implementation 可单测。
- Harness 通过端口调 worker，不直接依赖具体实现。
- 没有接 Research，仍不做 UI。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/03-seven-layer-ports.md。
要求：
1. 建立 Harness 七层端口：LLMWorkerPort、SkillWorkerPort、SkillEvolutionPort、SubAgentWorkerPort、RetrievalPort、MemoryPort、MCPToolPort、QualityGatePort、ArtifactPort。
2. 每个端口提供 fake implementation。
3. EvidencePack、RetrievalRequest、Memory write candidate、Skill candidate ref、MCP policy、Artifact ref 都要可序列化和可测试。
4. Harness 只能依赖端口，不直接依赖真实实现。
5. RetrievalPort 只做一次检索/读取，不实现多轮 RAG loop；但 EvidencePack 必须保留 lineage/source refs，支撑阶段 3B。
6. 添加端口和 fake runtime 测试。
7. 运行 python -m scripts.dev compile、python -m pytest tests/framework/harness -q、openspec validate harness-research-runtime --strict。
8. 修改完成后提交。
全部回复和问题用中文。
```
