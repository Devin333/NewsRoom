# 阶段 3：七层端口

## 阶段目标

建立 Harness 可调度的七层端口：LLM、Skills、SubAgent、Retrieval、Memory、MCP、Quality/Artifact。每个端口都要可替换、可 fake、可单测。

## 七层职责

| 层 | 职责 | Harness 决策点 |
| --- | --- | --- |
| LLM Worker | 生成候选结构化内容。 | 是否调用、用哪个输入、是否采纳。 |
| Skills | 执行确定性业务能力。 | 是否执行、参数是否有效、结果是否进入 state。 |
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
framework/harness/memory/
  __init__.py
  ports.py
  fake.py
framework/harness/skills/
  __init__.py
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
FakeSubAgentWorker
FakeRetrievalPort
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
tests/framework/harness/ports/test_memory_port.py
tests/framework/harness/ports/test_mcp_policy.py
tests/framework/harness/ports/test_fake_runtime.py
```

必须覆盖：

- 所有 fake 可被 Harness 调用。
- EvidencePack 可序列化。
- Memory candidate 不会自动写入。
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
- 每层 fake implementation 可单测。
- Harness 通过端口调 worker，不直接依赖具体实现。
- 没有接 Research，仍不做 UI。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/03-seven-layer-ports.md。
要求：
1. 建立 Harness 七层端口：LLMWorkerPort、SkillWorkerPort、SubAgentWorkerPort、RetrievalPort、MemoryPort、MCPToolPort、QualityGatePort、ArtifactPort。
2. 每个端口提供 fake implementation。
3. EvidencePack、RetrievalRequest、Memory write candidate、MCP policy、Artifact ref 都要可序列化和可测试。
4. Harness 只能依赖端口，不直接依赖真实实现。
5. 添加端口和 fake runtime 测试。
6. 运行 python -m scripts.dev compile、python -m pytest tests/framework/harness -q、openspec validate harness-research-runtime --strict。
7. 修改完成后提交。
全部回复和问题用中文。
```
