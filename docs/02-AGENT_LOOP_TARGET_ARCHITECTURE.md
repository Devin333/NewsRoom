# 02-AGENT_LOOP.md

版本：v1.0-target-architecture
适用项目：News Intelligence System
模块：AgentLoop / Agent Runtime
定位：目标态架构设计，不是 MVP 简化版

---

### 0.2 v1.3 AgentRunner 命名约定

本模块的单 Agent 调试、contract 验证和回归入口统一命名为 `AgentRunner`。

`AgentRunner` 负责装配 AgentSpec、LLMClient、ToolRegistry、ConversationStore、ArtifactStore，并调用 `AgentLoop`。它不替代 AgentLoop，也不持有业务逻辑。

```text
Test / Workflow StepRunner
  -> AgentRunner
      -> AgentLoop
          -> LLM Layer / Tool Runtime / ConversationStore
```


## 0. 文档定位

本文档定义 News Intelligence System 的 **最终目标态 AgentLoop / Agent Runtime**。

注意：

- 本文档不是第一版实现说明。
- 本文档不是 MVP 裁剪方案。
- 本文档先定义最终系统应该长什么样。
- 后续 MVP、P1、P2、生产化阶段，都应该从这个目标架构中裁剪实现范围。
- 第一版实现只是目标态 AgentLoop 的一个子集，而不是反过来用第一版限制最终设计。

AgentLoop 是 News Intelligence System 中负责 LLM 推理、工具调用、观察结果、输出校验、自我修正和质量判断的执行内核。

它和 Workflow Runtime 的关系是：

```text
Workflow Runtime 负责“流程怎么走”
AgentLoop 负责“单个 LLM Agent 节点怎么思考、行动、观察和收敛”
```

也就是说：

```text
WorkflowExecutor
  -> FunctionStepRunner
  -> AgentLoopStepRunner
        -> AgentLoop
```

---

## 0.1 v1.1 设计审查结论：AgentLoop 的修订边界

本次审查不删除 AgentLoop 的 planner / analyst / verifier / writer / editor / historian 等目标态能力，而是明确 AgentLoop 只负责单个 Agent 节点内部的受控循环。

需要保留：多轮 LLM、tool calling、observation、structured output、judge retry、conversation persistence、compaction、subagent delegation、stall detection。

需要修正：OutputJudge 与 Quality Gate 的职责要分层：

```text
OutputJudge:
  检查单个 Agent 输出是否满足 schema、agent-level rules、tool 权限、局部 evidence boundary。

Quality Gate:
  检查整份 report 是否满足 citation coverage、claim support、editor decision、rewrite/block/finalize 路径。
```

需要做设计减法：

```text
WriterAgent 默认不拥有外部 fetch/search 工具。
EditorAgent 默认不拥有新增 source 或修改 evidence 的工具。
SubAgent delegation 必须默认关闭，只有明确允许的 Agent 才能使用。
control tools 只作为 AgentLoop 控制协议，不应混入普通业务工具列表。
```

跨文档一致性要求：AgentLoop 调 LLM 必须走 `04-LLM_LAYER`，调工具必须走 `03-TOOL_RUNTIME`，写 conversation 和 artifact 必须走 `07-STORAGE_AND_MEMORY`。

---

## 0.2 v1.2 复查修订：OutputJudge 不替代 Quality Gate

AgentLoop 的 OutputJudge 只判断单个 Agent 节点输出是否满足 schema、tool policy、局部 evidence boundary 和当前 Agent 的 output contract。

它不能替代最终报告级 Quality Gate。

```text
OutputJudge:
  单 Agent 输出是否可写入 DataBuffer？

Quality Gate:
  整份 report 是否有足够 citation、claim support、uncertainty handling、editor decision？
```

因此 WriterAgent 输出通过 OutputJudge，并不代表 final report 可以发布；仍需进入 `citation_check -> editor_gate -> finalize/blocked`。


## 1. 为什么需要 AgentLoop

News Intelligence System 最终不会只是让 LLM 一次性生成报告。

它需要支持：

```text
planner agent
research analyst agent
verifier agent
writer agent
editor agent
historian agent
trend hunter agent
source quality reviewer
human-review assistant
memory recall assistant
subscription alert writer
```

这些 Agent 都需要一个受控循环：

```text
读取上下文
构造 prompt
调用 LLM
解析动作
执行工具
观察结果
更新 conversation
判断是否完成
不合格则重试
合格则输出结构化结果
失败则升级或阻断
```

如果没有 AgentLoop，系统会退化成：

```text
prompt -> LLM -> string
```

这种方式无法保证：

- 输出结构稳定。
- 工具调用可审计。
- LLM 不越过 evidence。
- Writer 不乱引用来源。
- Editor 能判断 pass / rewrite / blocked。
- 长任务能分多轮推进。
- 失败能重试或升级。
- 成本和 token 能被记录。
- 每次 Agent 行为能被回放。

因此，AgentLoop 是 News 系统中保证 LLM 可控、可审计、可恢复的关键模块。

---

## 2. 参考项目的通俗解释

### 2.1 Hive：像“会自我检查的工人”

Hive 的 `event_loop` node 是它的核心 Agent 执行单元。

通俗理解：

```text
一个工人拿到任务
先看当前资料
想一想
可能调用工具
看到工具结果
再想一想
如果结果不够好，就继续修正
如果完成了，就把结果写回共享仓库
```

Hive 的 event_loop node 不是一次 LLM 调用，而是多轮循环：

```text
LLM reasons
  -> maybe calls tools
  -> observes results
  -> judge checks quality
  -> accept / retry / escalate
```

值得借鉴：

- 多轮 LLM loop。
- 工具调用和 observation。
- Judge 判断是否完成。
- Conversation 持久化。
- EventBus 发布事件。
- Sub-agent delegation。
- Human-in-the-loop。
- Tool result pointer pattern。
- Stall / doom-loop 检测。
- Crash recovery 和 cursor checkpoint。

不应照搬：

- Hive 把 `event_loop` 作为唯一核心 node type。
- News 不能让所有业务都变成 AgentLoop。
- News 的 Writer / Editor 必须受 evidence 和 citation contract 限制。
- News 不需要一开始支持自动改写 agent graph 的 evolution loop。

---

### 2.2 smolagents：像“最小可读的 ReAct 循环”

smolagents 的 `MultiStepAgent` 很适合用来理解 AgentLoop 的最小内核。

通俗理解：

```text
目标还没完成时：
  LLM 给出一个动作
  系统执行动作
  把观察结果给回 LLM
  继续下一步
直到最终答案出现或达到 max_steps
```

值得借鉴：

- ReAct 的 action / observation 循环。
- max_steps 防止无限循环。
- step callbacks。
- final answer checks。
- 工具列表和 managed agents。

不应照搬：

- smolagents 很强调 code agent。
- News 的 Agent 不应该默认执行代码。
- News 更需要 structured output、evidence boundary、citation constraint。

---

### 2.3 OpenAI Agents SDK：像“标准化 Agent 工厂”

OpenAI Agents SDK 的 Agent 概念比较标准：

```text
Agent = instructions + tools + handoffs + guardrails + structured outputs
```

通俗理解：

```text
给 LLM 一个角色说明
给它一些工具
告诉它什么时候可以交给别的 Agent
再加上输入输出安全检查
最后用 Runner 执行
```

值得借鉴：

- Agent 配置对象。
- tools。
- handoffs。
- guardrails。
- structured outputs。
- sessions。
- tracing。
- human-in-the-loop。

不应照搬：

- News 想自研 AgentLoop，不能把核心循环交给 SDK。
- SDK 的 Runner 适合产品快速集成，但不适合作为你的学习型自研 runtime 内核。
- News 的 citation/evidence 规则比通用 guardrails 更具体。

---

### 2.4 AutoGen：像“多个人开会做事”

AutoGen 的价值是多 Agent 协作。

通俗理解：

```text
一个 Agent 负责规划
一个 Agent 负责执行
一个 Agent 负责审核
它们互相发消息
一起完成任务
```

值得借鉴：

- multi-agent conversation。
- agent roles。
- human-in-the-loop。
- tool execution。
- team orchestration。

不应照搬：

- AutoGen 当前处于维护模式，新项目不建议依赖它作为核心。
- 多 Agent 聊天容易失控。
- News 更适合 Workflow 控制 Agent，而不是让 Agent 自由聊天控制流程。

---

### 2.5 CrewAI：像“角色 + 任务 + 团队”

CrewAI 的思路是：

```text
Agent 有角色
Task 有目标
Crew 把多个 Agent 组织起来
Flow 把过程结构化
```

通俗理解：

```text
找几个人组成项目组：
  研究员负责研究
  作者负责写
  审稿人负责审查
然后按任务流推进
```

值得借鉴：

- role / goal / backstory。
- task description。
- structured output。
- human review。
- Flow 和 Crew 分离。

不应照搬：

- News 不应该只靠角色扮演。
- News 更需要 DataBuffer、Evidence、CitationChecker、EditorGate 这类强约束。
- CrewAI 的抽象适合参考，不适合替代自研 runtime。

---

## 3. Hive 的 AgentLoop 是怎么写的

Hive 里 AgentLoop 的核心不是叫 `AgentLoop`，而是：

```text
EventLoopNode
NodeConversation
ConversationJudge
SubagentJudge
Tool execution
EventBus
ConversationStore
```

主要相关文件：

```text
core/framework/graph/
  event_loop_node.py
  conversation.py
  conversation_judge.py
  node.py

core/framework/runtime/
  event_bus.py
  llm_debug_logger.py

core/framework/llm/
  provider.py
  stream_events.py
```

### 3.1 Hive EventLoopNode 的职责

Hive 的 `EventLoopNode` 是一个多轮 LLM streaming loop。

它负责：

```text
调用 LLMProvider.stream()
处理 text deltas
处理 tool calls
处理 finish events
执行工具
把工具结果写回 conversation
调用 judge 判断是否完成
发布 lifecycle events 到 EventBus
把 conversation 和 outputs 持久化到 ConversationStore
```

这说明 Hive 的 AgentLoop 不是简单：

```text
call LLM once
```

而是完整的：

```text
LLM -> tool -> observation -> judge -> retry/accept/escalate
```

### 3.2 Hive 的 JudgeVerdict

Hive 的 EventLoopNode 中有一个简单但清晰的 judge 协议：

```text
ACCEPT
RETRY
ESCALATE
```

含义：

| Verdict | 含义 |
|---|---|
| ACCEPT | 输出可接受，节点完成 |
| RETRY | 输出还不够好，把反馈给 LLM，再来一轮 |
| ESCALATE | 当前节点无法恢复，交给错误处理或上级 |

News 应该吸收这个思想，但要增加情报系统自己的 verdict：

```text
ACCEPT
RETRY
REWRITE_REQUIRED
BLOCK
ESCALATE
NEED_HUMAN_REVIEW
```

### 3.3 Hive 的 Conversation

Hive 的 NodeConversation 管理消息历史。

它的 message 至少包含：

```text
seq
role
content
tool_use_id
tool_calls
is_error
phase_id
is_transition_marker
```

值得参考：

- 每条消息有 seq。
- tool message 可以标记 is_error。
- conversation 可以序列化。
- conversation 可以持久化。
- conversation 支持 phase-aware compaction。
- tool result 太大时可以 spill 到文件。

News 最终态也应该有自己的 AgentConversation：

```text
AgentConversation
  messages
  tool observations
  judge feedback
  phase markers
  compaction summaries
  artifact refs
```

### 3.4 Hive 的 ConversationStore

Hive 的 ConversationStore 是持久化协议。

它支持：

```text
write_part
read_parts
write_meta
read_meta
write_cursor
read_cursor
delete_parts_before
close
destroy
```

这对最终态很重要，因为 AgentLoop 可能很长：

- LLM 调用中断。
- 用户介入后 resume。
- 流程暂停。
- 节点 crash。
- 需要从上次 cursor 恢复。

News 最终态应该支持：

```text
ConversationStore
ConversationCursor
ConversationCheckpoint
ConversationCompaction
```

### 3.5 Hive 的 synthetic tools

Hive 的 EventLoopNode 内置了一些 synthetic tools：

```text
ask_user
ask_user_multiple
set_output
escalate
delegate_to_sub_agent
report_to_parent
```

这些不是普通业务工具，而是 AgentLoop 控制工具。

值得借鉴：

| Hive Tool | News 可借鉴点 |
|---|---|
| ask_user | Agent 需要人工输入时暂停 |
| ask_user_multiple | 批量澄清问题 |
| set_output | Agent 明确设置结构化输出 |
| escalate | 向 Reviewer / Operator / Orchestrator 升级 |
| delegate_to_sub_agent | 分派给专门 Agent |
| report_to_parent | 子 Agent 汇报进度 |

News 最终态可以定义自己的 control tools：

```text
set_output
request_human_review
request_rewrite
escalate_to_reviewer
delegate_to_subagent
report_progress
load_artifact
load_memory_snapshot
```

### 3.6 Hive 的 sub-agent delegation

Hive 的父 EventLoopNode 可以通过 `delegate_to_sub_agent` 创建子 Agent。

子 Agent 特点：

```text
独立 EventLoopNode
只读 memory snapshot
自己的 conversation
filtered tools
SubagentJudge
可并行运行
通过 report_to_parent 回传结果
可升级给用户
阻止 nested delegation
```

News 非常适合参考，但要更严格。

例如：

```text
WriterAgent
  可以委托:
    citation_sanity_checker
    section_draft_agent
    style_rewriter

AnalystAgent
  可以委托:
    entity_extractor
    trend_signal_agent
    risk_note_agent
```

但需要限制：

```text
子 Agent 只能读 evidence snapshot
子 Agent 不能新增 source
子 Agent 不能写 final_report
子 Agent 结果必须经过 parent judge
不允许无限嵌套
```

### 3.7 Hive 的 tool result pointer pattern

Hive 的架构文档中提到：工具结果太大时，不把完整内容塞进 conversation，而是保存到文件，并在 conversation 里放一个 compact file reference。

通俗理解：

```text
工具查到了 10 万字网页
不要把 10 万字直接塞给 LLM
把内容存成文件
对话里只放：
  “结果已保存到 xxx.txt，需要时用 load_data 读取”
```

News 非常需要这个设计。

因为 source、webpage、RSS、GitHub issue、论文摘要都可能很长。

News 应该支持：

```text
ToolResultPointer
ArtifactRef
load_artifact
load_data_chunk
conversation compaction
```

### 3.8 Hive 的 doom-loop / stall 检测

Hive 里有对工具 doom loop、stall、重复响应的处理思路。

通俗理解：

```text
如果 Agent 一直调用同一个工具、同一组参数、得到同样错误，
系统应该提醒它换方法，
或者升级给人，
而不是无限烧 token。
```

News 最终态需要：

```text
repeated_tool_call_detector
repeated_output_detector
no_progress_detector
budget_guard
max_iterations
max_tool_calls
max_same_tool_retries
```

---

## 4. News 最终态 AgentLoop 目标

News AgentLoop 最终应该支持：

```text
multi-turn LLM loop
tool calling
structured output
schema validation
judge retry
quality feedback
evidence boundary enforcement
citation boundary enforcement
conversation persistence
conversation compaction
tool result pointer
sub-agent delegation
human escalation
cost tracking
event streaming
checkpoint/resume
stall detection
artifact logging
guardrails
multi-provider LLM
```

---

## 5. AgentLoop 和 Workflow Runtime 的边界

### 5.1 Workflow Runtime 负责

```text
哪个 step 执行
step 读写哪些 buffer key
step 成功后去哪里
step 失败后去哪里
artifact 怎么写
workflow 怎么暂停/恢复
```

### 5.2 AgentLoop 负责

```text
如何构造 LLM messages
如何调用 LLM
如何解析 LLM 输出
如何执行工具
如何把工具结果变成 observation
如何维护 conversation
如何判断输出是否完成
如何重试
如何升级
如何写入 step output
```

### 5.3 Tool Runtime 负责

```text
工具注册
工具 schema
参数校验
工具执行
工具结果包装
工具权限控制
```

### 5.4 LLM Layer 负责

```text
provider adapter
model request
streaming / non-streaming
usage tokens
retryable status
rate limit
raw response parsing
```

### 5.5 Quality Gate 负责

```text
citation check
unsupported claims
editor review
pass/rewrite/block
```

AgentLoop 可以调用 Quality Gate，但不应该把所有质量规则硬编码在自己里面。

---

## 6. 最终态核心模型

### 6.1 AgentSpec

```python
class AgentSpec(BaseModel):
    agent_id: str
    name: str
    description: str = ""

    role: str
    goal: str
    instructions: str

    input_keys: list[str] = Field(default_factory=list)
    output_key: str
    output_schema: str | None = None

    allowed_tools: list[str] = Field(default_factory=list)
    allowed_subagents: list[str] = Field(default_factory=list)

    model_policy: ModelPolicySpec
    loop_policy: AgentLoopPolicySpec
    tool_policy: ToolPolicySpec = Field(default_factory=ToolPolicySpec)
    judge_policy: JudgePolicySpec = Field(default_factory=JudgePolicySpec)
    memory_policy: MemoryPolicySpec = Field(default_factory=MemoryPolicySpec)
    guardrail_policy: GuardrailPolicySpec = Field(default_factory=GuardrailPolicySpec)
    artifact_policy: AgentArtifactPolicySpec = Field(default_factory=AgentArtifactPolicySpec)

    system_prompt_template: str
    task_prompt_template: str

    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 6.2 AgentLoopPolicySpec

```python
class AgentLoopPolicySpec(BaseModel):
    max_iterations: int = 5
    max_tool_calls: int | None = None
    max_same_tool_retries: int = 2
    max_wall_time_seconds: int = 180
    stop_on_first_valid_output: bool = True
    allow_human_escalation: bool = False
    allow_subagent_delegation: bool = False
```

### 6.3 ModelPolicySpec

```python
class ModelPolicySpec(BaseModel):
    provider: str
    model_name: str
    temperature: float = 0.2
    max_output_tokens: int = 1200
    timeout_seconds: int = 90
    retryable_status_codes: list[int] = Field(default_factory=lambda: [429, 500, 502, 503, 504])
    max_retries: int = 2
```

### 6.4 ToolPolicySpec

```python
class ToolPolicySpec(BaseModel):
    require_explicit_allowlist: bool = True
    allow_parallel_tool_calls: bool = False
    max_tool_result_chars_inline: int = 8000
    spill_large_results_to_artifact: bool = True
    blocked_tools: list[str] = Field(default_factory=list)
```

### 6.5 JudgePolicySpec

```python
class JudgePolicySpec(BaseModel):
    judge_type: str = "schema_and_rules"
    use_llm_judge: bool = False
    max_judge_retries: int = 2
    accept_confidence_threshold: float = 0.8
    retry_on_schema_error: bool = True
    retry_on_quality_error: bool = True
    escalate_on_repeated_failure: bool = True
```

### 6.6 AgentConversation

```python
class AgentConversation(BaseModel):
    conversation_id: str
    run_id: str
    step_id: str
    agent_id: str

    messages: list[AgentMessage] = Field(default_factory=list)
    cursor: ConversationCursor | None = None
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 6.7 AgentMessage

```python
class AgentMessage(BaseModel):
    seq: int
    role: Literal["system", "user", "assistant", "tool", "judge", "control"]
    content: str

    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    is_error: bool = False

    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    token_count: int | None = None
    created_at: datetime
```

### 6.8 AgentAction

```python
class AgentAction(BaseModel):
    action_type: Literal[
        "final_output",
        "tool_call",
        "tool_calls",
        "delegate_to_subagent",
        "request_human_input",
        "escalate",
        "continue"
    ]

    output: dict[str, Any] | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)

    subagent_id: str | None = None
    subagent_task: str | None = None

    human_prompt: str | None = None
    escalation_reason: str | None = None
```

### 6.9 JudgeVerdict

```python
class JudgeVerdict(BaseModel):
    decision: Literal[
        "accept",
        "retry",
        "rewrite_required",
        "block",
        "escalate",
        "need_human_review"
    ]

    confidence: float = 0.0
    feedback: str | None = None
    missing_output_keys: list[str] = Field(default_factory=list)
    schema_errors: list[str] = Field(default_factory=list)
    quality_errors: list[str] = Field(default_factory=list)
    policy_violations: list[str] = Field(default_factory=list)
```

### 6.10 AgentLoopResult

```python
class AgentLoopResult(BaseModel):
    success: bool
    status: Literal[
        "accepted",
        "retry_exhausted",
        "blocked",
        "escalated",
        "human_review_required",
        "failed"
    ]

    output: dict[str, Any] = Field(default_factory=dict)
    verdict: JudgeVerdict | None = None

    conversation_id: str
    iterations: int
    tool_calls: int
    subagent_calls: int = 0

    metrics: AgentLoopMetrics
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    error: str | None = None
```

---

## 7. 最终态执行流程

### 7.1 AgentLoop 主循环

```text
1. AgentLoopStepRunner 从 Workflow DataBuffer 读取 input_keys
2. AgentRegistry 获取 AgentSpec
3. ConversationStore 创建或恢复 conversation
4. PromptBuilder 构造 system/user messages
5. 调用 LLMClient
6. AgentActionParser 解析 LLM 输出
7. 如果是 tool_call，ToolExecutor 执行工具
8. 工具结果写入 conversation，必要时 spill 到 artifact
9. 如果是 subagent delegation，SubAgentExecutor 执行子 Agent
10. 如果是 final_output，OutputJudge 校验 schema、规则和质量
11. Judge ACCEPT，写 output_key 到 DataBuffer
12. Judge RETRY，反馈写回 conversation，进入下一轮
13. Judge BLOCK，返回 blocked
14. Judge ESCALATE，暂停或交给 human review / parent workflow
15. 写 AgentLoopResult、conversation、metrics、artifacts
```

### 7.2 伪代码

```python
class AgentLoop:
    async def run(
        self,
        context: AgentLoopContext,
        scoped_buffer: ScopedDataBuffer,
    ) -> AgentLoopResult:
        agent = self.agent_registry.get(context.agent_id)

        inputs = {
            key: scoped_buffer.read(key)
            for key in agent.input_keys
        }

        conversation = await self.conversation_store.load_or_create(context)

        await self.prompt_builder.ensure_initial_messages(
            agent=agent,
            inputs=inputs,
            conversation=conversation,
        )

        for iteration in range(agent.loop_policy.max_iterations):
            llm_response = await self.llm_client.complete(
                self.request_builder.build(agent, conversation)
            )

            action = self.action_parser.parse(llm_response)

            await conversation.add_assistant_message(
                content=llm_response.text,
                tool_calls=action.tool_calls,
            )

            if action.action_type in {"tool_call", "tool_calls"}:
                tool_results = await self.tool_executor.execute_actions(
                    action=action,
                    allowed_tools=agent.allowed_tools,
                    policy=agent.tool_policy,
                )
                observations = await self.observation_builder.build(tool_results)
                await conversation.add_tool_observations(observations)
                continue

            if action.action_type == "delegate_to_subagent":
                sub_result = await self.subagent_executor.run(action, context, inputs)
                await conversation.add_tool_observation(sub_result.to_observation())
                continue

            if action.action_type == "request_human_input":
                return await self.human_escalation_handler.pause(context, action, conversation)

            if action.action_type == "final_output":
                verdict = await self.output_judge.evaluate(
                    agent=agent,
                    action=action,
                    inputs=inputs,
                    conversation=conversation,
                )

                await conversation.add_judge_feedback(verdict)

                if verdict.decision == "accept":
                    scoped_buffer.write(agent.output_key, action.output)
                    return AgentLoopResult.accepted(...)

                if verdict.decision == "retry":
                    continue

                if verdict.decision in {"block", "escalate", "need_human_review"}:
                    return AgentLoopResult.from_verdict(verdict, ...)

        return AgentLoopResult.retry_exhausted(...)
```

---

## 8. PromptBuilder 目标态设计

PromptBuilder 不应该只是字符串拼接。

它要负责：

```text
agent role
task goal
input data
available tools
output schema
evidence constraints
citation constraints
memory context
previous judge feedback
conversation summary
budget hints
forbidden behavior
```

### 8.1 Prompt Sections

```text
System Role
Agent Goal
Workflow Context
Input Data
Evidence Boundary
Allowed Tools
Output Contract
Quality Criteria
Judge Feedback
Safety / Security Constraints
```

### 8.2 对 News 特别重要的 Prompt 约束

WriterAgent 必须包含：

```text
只能使用 evidence_bundle 和 verified_findings 中的来源
不能新增 URL
不能编造发布时间、公司、模型、benchmark
不确定内容必须标记 uncertain
每个 section 必须列出 sources
```

EditorAgent 必须包含：

```text
不能新增事实
不能新增 source
只能审查 report_draft 是否被 evidence 支持
必须输出 pass / rewrite_required / blocked
```

VerifierAgent 必须包含：

```text
supporting_sources 必须来自 evidence
低置信 claim 必须进入 uncertain
rejected claim 不能进入 final report
```

---

## 9. AgentActionParser 目标态设计

LLM 输出不可靠，所以 parser 要多层处理。

### 9.1 支持输出格式

```text
strict JSON
tool call JSON
OpenAI tool calls
provider-native tool calls
markdown fenced JSON
partial JSON recovery
```

### 9.2 Parser 不做什么

Parser 只负责：

```text
LLM response -> AgentAction
```

Parser 不执行工具，不判断质量，不写 DataBuffer。

### 9.3 Parser 错误处理

```text
json_parse_error
unknown_action_type
missing_tool_name
invalid_tool_args
missing_final_output
provider_response_shape_invalid
```

Parser 错误一般可以进入 Judge RETRY。

---

## 10. OutputJudge 目标态设计

OutputJudge 是 AgentLoop 能否可靠的关键。

### 10.1 Judge 层级

最终态建议分多层：

```text
Level 1: Schema Judge
Level 2: Rule Judge
Level 3: Quality Judge
Level 4: LLM Judge
Level 5: Human Judge
```

### 10.2 Schema Judge

检查：

```text
required output key 是否存在
output 是否符合 Pydantic schema
字段类型是否正确
必填字段是否缺失
```

### 10.3 Rule Judge

检查：

```text
Writer 是否使用 evidence 外 URL
Verifier supporting_sources 是否来自 evidence
Analyst importance_scores 是否对应 evidence_id
Editor decision 是否合法
工具是否越权
输出是否包含 secret
```

### 10.4 Quality Judge

检查：

```text
citation coverage
unsupported claims
重复内容
结构完整性
是否缺少关键 section
是否过度推断
```

### 10.5 LLM Judge

用于复杂语义判断：

```text
报告是否真的被 evidence 支持
trend conclusion 是否过度推断
risk note 是否合理
摘要是否忠实于 sections
```

### 10.6 Human Judge

用于：

```text
发布前审批
高风险报告
多次 rewrite 失败
低置信重大结论
source 可信度争议
```

---

## 11. Tool 调用与 Observation 设计

### 11.1 Tool Call 生命周期

```text
tool_call_requested
tool_args_validated
tool_started
tool_succeeded
tool_failed
tool_result_spilled
tool_observation_added
```

### 11.2 Observation 不是原始工具结果

工具结果可能很大，不能直接塞给 LLM。

Observation 应该是：

```json
{
  "tool_name": "search_memory",
  "status": "success",
  "summary": "Found 5 related historical reports.",
  "highlights": [
    "Agent framework topic appeared 3 times in the past 14 days."
  ],
  "artifact_refs": [
    "artifacts/tool_results/search_memory_001.json"
  ]
}
```

### 11.3 Pointer Pattern

如果工具结果很大：

```text
完整结果 -> artifact
conversation -> compact reference
Agent 如需细节 -> load_artifact / load_data_chunk
```

---

## 12. SubAgent 目标态设计

### 12.1 SubAgent 使用场景

```text
并行研究多个来源
拆分 report sections
单独抽取 entities
单独检查 citation
单独生成 timeline
单独总结历史 memory
```

### 12.2 SubAgent 约束

```text
子 Agent 只能拿 read-only snapshot
子 Agent 必须有明确 output schema
子 Agent 不能写 parent DataBuffer
子 Agent 结果必须交给 parent judge
禁止无限嵌套
子 Agent 工具集必须比 parent 更窄或相等
```

### 12.3 SubAgentExecutor

```python
class SubAgentExecutor:
    async def run(
        self,
        parent_context: AgentLoopContext,
        subagent_id: str,
        task: str,
        memory_snapshot: dict[str, Any],
        allowed_tools: list[str],
    ) -> SubAgentResult:
        ...
```

---

## 13. Conversation Compaction

### 13.1 为什么需要

AgentLoop 会越来越长：

```text
source 结果很大
工具结果很大
judge feedback 很多
多轮 rewrite
多 Agent 协作
```

如果不压缩，会超过上下文窗口。

### 13.2 Compaction 策略

```text
保留 system prompt
保留 output schema
保留最近 N 轮
保留 tool call 结构
保留 artifact refs
把旧自然语言总结成 summary
把大工具结果 spill 到 artifact
```

### 13.3 不允许压缩掉

```text
evidence boundary
source URLs
rejected claims
judge feedback
final output contract
tool error trace
```

---

## 14. Stall / Doom-loop Detection

最终态必须防止 Agent 空转。

### 14.1 检测项

```text
重复调用同一个工具 + 同样参数
连续多轮没有写 output
连续多轮 schema error
连续多轮相同 judge feedback
LLM 只聊天不工作
重复生成相同草稿
token 消耗超过预算
```

### 14.2 处理方式

```text
inject warning feedback
force different strategy
reduce tool access
escalate to parent
request human review
block workflow
```

---

## 15. Agent Event 设计

### 15.1 Event Types

```text
agent_loop_started
agent_iteration_started
agent_llm_request_started
agent_llm_response_received
agent_action_parsed
agent_tool_call_requested
agent_tool_call_succeeded
agent_tool_call_failed
agent_observation_added
agent_judge_started
agent_judge_accept
agent_judge_retry
agent_judge_block
agent_judge_escalate
agent_subagent_started
agent_subagent_completed
agent_human_input_requested
agent_loop_completed
agent_loop_failed
conversation_compacted
tool_result_spilled
```

### 15.2 AgentLoopMetrics

```python
class AgentLoopMetrics(BaseModel):
    iterations: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    failed_tool_calls: int = 0
    subagent_calls: int = 0

    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0

    wall_time_ms: int = 0
    judge_retries: int = 0
    schema_retries: int = 0
    quality_retries: int = 0
```

---

## 16. News Agent 类型设计

最终态至少支持以下 Agent：

### 16.1 PlannerAgent

职责：

```text
根据 request 生成 ResearchPlan
决定需要哪些 source type
决定 expected sections
```

限制：

```text
不直接抓取 source
不直接写 report
```

### 16.2 AnalystAgent

职责：

```text
从 evidence 中提取 key findings
识别 trend signals
识别 risk notes
识别 importance scores
```

限制：

```text
不能使用 evidence 外事实
不能编造来源
```

### 16.3 VerifierAgent

职责：

```text
把 claim 分成 accepted / rejected / uncertain
标记 supporting_sources
标记 rejecting_sources
```

限制：

```text
supporting_sources 必须来自 evidence
低置信进入 uncertain
```

### 16.4 WriterAgent

职责：

```text
根据 analysis_result、verified_findings、evidence_bundle 写 report_draft
```

限制：

```text
不能新增 source
不能直接搜索
不能把 rejected claim 写成事实
每个 section 必须有 sources
```

### 16.5 EditorAgent

职责：

```text
审查 report_draft
结合 citation_check_result
输出 pass / rewrite_required / blocked
```

限制：

```text
不能新增事实
不能替代 CitationChecker
只能给 rewrite instruction 或 block reason
```

### 16.6 HistorianAgent

职责：

```text
从 memory 中召回历史事件
构建 timeline
提供历史对照
```

限制：

```text
历史 memory 必须有来源
不能把历史推断写成当前事实
```

### 16.7 TrendHunterAgent

职责：

```text
识别跨天趋势
识别热点上升
识别异常信号
```

限制：

```text
趋势判断必须给 evidence 和 confidence
```

### 16.8 ReviewerAgent

职责：

```text
最终质量复核
高风险 claim 检查
发布前建议
```

限制：

```text
不能直接修改 final_report
只能输出 review decision
```

---

## 17. Guardrails 设计

### 17.1 输入 Guardrails

```text
request 是否合法
topic 是否过宽
source limit 是否过大
预算是否允许
是否包含敏感 secret
```

### 17.2 输出 Guardrails

```text
schema valid
no secret leakage
no unsupported URL
no rejected claim as fact
no fabricated benchmark
no fabricated date
no direct investment advice
```

### 17.3 Tool Guardrails

```text
tool allowlist
args schema validation
timeout
max result size
domain allowlist / denylist
rate limit
```

### 17.4 Evidence Guardrails

```text
Writer 只能读 evidence
Editor 只能审查 evidence
Verifier supporting_sources 必须来自 evidence
Historian memory 必须标记 historical
```

---

## 18. Artifact 设计

### 18.1 Agent-level Artifacts

```text
agent_request.redacted.json
agent_response.redacted.json
agent_conversation.jsonl
agent_judge_results.json
agent_tool_calls.jsonl
agent_metrics.json
agent_output.json
agent_error.json
```

### 18.2 Redaction

不能写入：

```text
API key
Authorization header
secret env value
cookie
credential
```

可以写入：

```text
model name
provider name
token usage
redacted prompt
redacted response
tool name
tool args after redaction
tool result summary
artifact refs
```

---

## 19. 目标态目录结构建议

```text
core/framework/agent_loop/
  __init__.py

  specs/
    agent_spec.py
    policy_spec.py
    prompt_spec.py
    judge_spec.py

  runtime/
    loop.py
    context.py
    runner.py
    lifecycle.py

  conversation/
    message.py
    conversation.py
    store.py
    cursor.py
    compaction.py

  prompts/
    builder.py
    templates.py
    render.py

  parser/
    action.py
    parser.py
    recovery.py

  judge/
    base.py
    schema_judge.py
    rule_judge.py
    quality_judge.py
    llm_judge.py
    human_judge.py

  observations/
    observation.py
    builder.py
    pointer.py

  subagents/
    executor.py
    result.py
    policy.py

  guardrails/
    input_guardrails.py
    output_guardrails.py
    tool_guardrails.py
    evidence_guardrails.py

  events/
    event_models.py
    event_emitter.py

  artifacts/
    artifact_writer.py
    redaction.py

  metrics/
    models.py
    collector.py

  errors/
    error_types.py
    exceptions.py
```

---

## 20. 和 Hive 的最终取舍

### 20.1 借鉴 Hive

```text
EventLoopNode 多轮 LLM 循环
JudgeVerdict: ACCEPT / RETRY / ESCALATE
ConversationStore 写穿式持久化
set_output control tool
ask_user / escalate 思路
delegate_to_sub_agent 思路
report_to_parent 思路
tool result pointer pattern
EventBus lifecycle events
stall / doom-loop 检测
conversation cursor / checkpoint
```

### 20.2 不照搬 Hive

```text
不把 event_loop 作为唯一节点类型
不让 AgentLoop 控制整个 workflow
不让 LLM 自由决定所有路由
不让子 Agent 无限嵌套
不默认给 Writer 搜索工具
不允许 Editor 新增事实
不把 evidence/citation 规则藏在 prompt 里
不把大工具结果直接塞进 conversation
```

### 20.3 News 自己的目标态

```text
AgentLoop 是 Workflow StepRunner 的一种
AgentSpec 明确输入输出和约束
Evidence boundary 是硬规则
Citation boundary 是硬规则
OutputJudge 分 schema/rule/quality/LLM/human 多层
Tool result 默认可 pointer 化
Conversation 必须可持久化、可压缩、可回放
SubAgent 只读 snapshot，不直接改 parent buffer
Agent 事件和 artifacts 是一等能力
```

---

## 21. 分阶段裁剪原则

本文档定义最终态。后续第一阶段可以只实现子集，但不能破坏最终架构。

裁剪原则：

```text
目标态先定完整边界
第一阶段只取最小可运行链路
命名、接口、目录和最终态保持兼容
后续只是补 judge、subagent、compaction、checkpoint、human review
不要推翻 AgentLoop
```

例如第一阶段可以只实现：

```text
AgentSpec
AgentLoopPolicySpec
AgentConversation
AgentMessage
AgentAction
AgentActionParser
PromptBuilder
SchemaJudge
RuleJudge
AgentLoop
AgentLoopResult
AgentLoopMetrics
```

但目录和接口应与最终态兼容。

---

## 22. 最终态验收标准

AgentLoop 最终完成时，应该满足：

```text
支持多轮 LLM 循环
支持工具调用和 observation
支持结构化输出
支持 schema judge
支持 rule judge
支持 quality judge
支持 LLM judge
支持 human judge
支持 conversation persistence
支持 conversation compaction
支持 tool result pointer
支持 sub-agent delegation
支持 human escalation
支持 stall / doom-loop detection
支持 guardrails
支持 event streaming
支持 artifact logging
支持 token/cost/latency metrics
支持 checkpoint/resume
支持 evidence boundary enforcement
支持 citation boundary enforcement
```

---

## 23. 总结

News AgentLoop 的最终目标不是一个普通的 LLM wrapper，也不是单纯的 ReAct demo。

它应该是：

```text
面向情报生产的受约束 Agent 执行内核
```

它吸收 Hive 的 EventLoopNode、Conversation、Judge、SubAgent、EventBus、Pointer Pattern 思想，也参考 smolagents 的最小 ReAct loop、OpenAI Agents SDK 的 Agent/Tools/Guardrails/Handoffs、AutoGen 的多 Agent 协作经验、CrewAI 的角色任务设计。

但 News 必须强化自己的业务约束：

```text
evidence boundary
citation boundary
source lineage
report quality gate
editor block/rewrite
artifact replay
conversation persistence
cost guard
human review
```

后续 MVP、第一版、第二版都应该从这个最终态目标中裁剪实现，而不是用第一版的简单实现反向定义 AgentLoop 的上限。

---
# 本版保留说明

以上内容为原目标态文档主体内容，已完整保留。下面追加的是 v2.0 设计书级补强，用于把原目标态说明转化为更可开发、可验收、可维护的工程设计书。

---
# v2.0 设计书级补强：AgentLoop 工程化设计

## A. 本模块最终职责

AgentLoop 负责“单个 Agent 节点怎么思考、调用工具、观察结果、判断收敛”。

它不是：

```text
不是 workflow executor。
不是多 Agent 自由聊天室。
不是 ToolExecutor。
不是 LLM provider adapter。
不是最终报告 Quality Gate。
```

它拥有：

```text
AgentSpec
AgentLoopState
AgentAction
AgentObservation
AgentLoopResult
PromptBuilder
ActionParser
OutputJudge
AgentRunner
ConversationCompactor
StallDetector
```

## B. 最小受控循环

```text
build prompt
call LLM
parse action
if tool_call:
  ToolExecutor.execute()
  append observation
  continue
if final_output:
  OutputJudge.check()
  if accept: return result
  if retry: append feedback and continue
  if escalate/block: return failure
if max_steps exceeded:
  return failed/stalled
```

## C. 第一批 Agent 设计

```text
PlannerAgent
  输入：request、source summary、history hints
  输出：ResearchPlan
  工具：无或 load_context

ResearchAnalystAgent
  输入：EvidenceBundle、history memory
  输出：AnalysisResult
  工具：search_memory、load_evidence

VerifierAgent
  输入：candidate claims、evidence
  输出：VerifiedFindings
  工具：load_evidence、check_claim_support

ReportWriterAgent
  输入：VerifiedFindings、ReportStyle
  输出：ReportDraft
  工具：load_evidence、render_markdown
  禁止：fetch_url、generic_http_request

EditorAgent
  输入：ReportDraft、EvidenceBundle、CitationCheckResult
  输出：EditorReview
  工具：check_citations、load_evidence
  禁止：新增 source、修改 evidence、发布 report

HistorianAgent
  输入：topic、current evidence
  输出：HistoricalContext
  工具：search_memory、search_vectors、load_past_report
```

## D. AgentSpec

```python
class AgentSpec(BaseModel):
    agent_id: str
    name: str
    role: str
    goal: str

    instructions: str
    output_schema: dict[str, Any]

    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)

    max_steps: int = 6
    max_retries: int = 2
    temperature: float = 0.2

    evidence_boundary: EvidenceBoundaryPolicy | None = None
    budget_policy: AgentBudgetPolicy | None = None
```

## E. OutputJudge 与 Quality Gate 分层

OutputJudge 只判断：

```text
schema 是否正确
字段是否完整
是否调用了未授权工具
是否越过当前 Agent 的 evidence boundary
是否满足当前 Agent output contract
```

Quality Gate 判断：

```text
整份 report citation coverage
claim support matrix
uncertain/rejected claim
editor decision
rewrite/block/finalize
```

WriterAgent 通过 OutputJudge 不代表报告可发布。

## F. Conversation 设计

AgentConversation 至少保存：

```text
messages
tool calls
tool observations
judge feedback
compaction summary
artifact refs
usage/cost
step index
```

过大的 tool result 不进入 prompt，应该写 artifact pointer。

## G. Stall / Doom Loop 检测

必须检测：

```text
连续重复相同 tool call
连续输出无法解析
judge 连续 retry
没有新增 observation
max_steps 达到
budget 达到
```

触发后：

```text
return AgentLoopResult(status="stalled")
write diagnostic artifact
交给 WorkflowRuntime 路由
```

## H. 代码组织建议

初期集中：

```text
runtime/agent_loop.py
```

内部 section：

```text
Models
Conversation
PromptBuilder
ActionParser
OutputJudge
AgentLoop
AgentRunner
Built-in Agent Specs
```

超过 2200 行再拆 prompt/parser/judge。

## I. 测试矩阵

```text
test_agent_loop_final_output_success
test_agent_loop_tool_call_observation
test_agent_loop_denied_tool_blocked
test_output_judge_schema_retry
test_writer_cannot_fetch_url
test_editor_cannot_add_source
test_max_steps_stops_loop
test_tool_result_pointer
```

## J. 验收清单

```text
[ ] AgentLoop 不直接调用 provider SDK。
[ ] AgentLoop 调工具必须经过 ToolExecutor。
[ ] AgentRunner 只装配，不写业务逻辑。
[ ] WriterAgent 不能绕过 evidence。
[ ] EditorAgent 不能新增事实。
[ ] OutputJudge 不替代 Quality Gate。
```

---

## K. 当前代码进度映射：v2.1-current-code-aligned

本章节用于把目标态文档和当前仓库实现对齐。AgentLoop 当前已经不是空白模块，后续开发必须在现有 `core/framework/agent_loop` 基础上继续增强，不能重新发明一套 Agent 框架。

### K.1 当前已实现

| 能力 | 状态 | 对应代码 | 说明 |
|---|---|---|---|
| AgentSpec | 已实现 | `core/framework/agent_loop/models.py` | 已有 agent_id、role、goal、instructions、input_keys、output_key、allowed_tools、tool_policy、loop_policy |
| AgentLoopPolicy | 已增强 | `core/framework/agent_loop/models.py` | 支持 max_iterations、judge/parser retry、重复工具调用检测、trace 开关 |
| AgentAction | 已实现 | `core/framework/agent_loop/models.py` | 支持 `tool_call` 和 `final_output` |
| AgentActionParser | 已实现 | `core/framework/agent_loop/parser.py` | 解析 LLM JSON action，错误进入 retry/diagnostics |
| PromptBuilder | 已实现 | `core/framework/agent_loop/prompt.py` | 通过内部 `LLMRequest` 构造 prompt，不直接调用 provider SDK |
| OutputJudge | 已实现基础版 | `core/framework/agent_loop/judge.py` | 检查 required output key、tool allowlist、source boundary、secret-like output |
| AgentLoop | 已大幅增强 | `core/framework/agent_loop/loop.py` | 支持多轮 LLM、tool call、observation、judge retry、control output、stall、approval wait、diagnostics、trace |
| AgentRunner | 已实现 | `core/framework/agent_loop/runner.py` | 装配 LLMClient、ToolRegistry、ToolExecutor、ConversationStore 并调用 AgentLoop，持久化后写 latest conversation cursor |
| ToolRuntime 边界 | 已实现 | `core/framework/tools/*` + AgentLoop | AgentLoop 调工具必须经过 `ToolExecutor` |
| LLM Layer 边界 | 已实现 | `core/framework/llm/*` + AgentLoop | AgentLoop 调 LLM 必须经过 `LLMClient` |
| Conversation persistence | 已有基础 | `storage/conversation/*` + `AgentRunner` | 持久化 user/tool/judge/diagnostic/assistant message，assistant result 保持最后 |
| Workflow 集成 | 已实现 | `AgentLoopStepRunner` | Workflow step 可调用 AgentRunner，把 run_id/step_id/checkpoint metadata 传入 cursor，并把 AgentLoop result/events/metrics 写入 DataBuffer |
| Deterministic smoke workflow | 已实现 | `workflows/daily_intelligence/test_agent_loop.py` | FakeLLM + fake tool 的离线回归 workflow |

### K.2 本轮大增强内容

本轮不是小字段补丁，而是把 AgentLoop 的可诊断性提升为一等能力：

```text
AgentLoopStatus 新增：
  waiting_for_approval
  stalled

AgentLoopStopReason 新增：
  final_output_accepted
  control_output_accepted
  judge_blocked
  secret_blocked
  tool_approval_required
  tool_budget_exceeded
  repeated_tool_call_stalled
  parser_retry_exhausted
  judge_retry_exhausted
  max_iterations_exceeded
  llm_failed
  tool_failed
  unknown_failed
```

新增代码模块：

```text
core/framework/agent_loop/events.py
  AgentLoopEvent
  AgentLoopEventRecorder
  typed event helpers

core/framework/agent_loop/trace.py
  AgentLoopTrace
  IterationTrace
  LLMCallTrace
  ParserErrorTrace
  ToolCallTrace
  JudgeTrace
  ToolCallSignature

core/framework/agent_loop/diagnostics.py
  AgentLoopDiagnosticsBuilder
  AgentLoopStallDetector
  StallDetection
  max_iterations_detection
```

AgentLoopResult 现在包含：

```text
status
output
verdict
iterations
metrics
events
trace
diagnostics
error
```

AgentLoopMetrics 现在包含：

```text
iterations
llm_calls
tool_calls
parser_errors
judge_retries
judge_accepts
judge_blocks
tool_successes
tool_failures
tool_blocks
tool_timeouts
tool_approval_requests
repeated_tool_calls
stalled_iterations
llm_error_count
total_tool_elapsed_ms
token_usage
```

### K.3 当前能力成熟度

| 能力 | 当前状态 | 说明 |
|---|---|---|
| 多轮 LLM loop | 已实现 | FakeLLM/真实 LLMClient 均走同一协议 |
| tool call / observation | 已实现 | 通过 ToolExecutor，observation 会回填 prompt |
| control.set_output | 已实现 | 可通过 control tool 设置结构化输出 |
| schema/key judge | 已增强 | 已支持 output_key、JSON Schema 常用约束、source boundary、evidence boundary 的 deterministic judge |
| source boundary | 已实现基础版 | 检查 output 中 source/url 是否越界 |
| secret-like output block | 已实现 | 命中后 BLOCK，不进入发布逻辑 |
| parser retry diagnostics | 已实现 | parser error 进入 trace/diagnostics |
| judge retry diagnostics | 已实现 | retry exhausted 有 stop_reason/issue/suggestion |
| repeated tool-call stall | 已实现 | 相同 tool+args hash 超限后 STALLED |
| tool approval wait | 已实现 | approval_required 映射为 AgentLoopStatus.WAITING_FOR_APPROVAL |
| human escalation wait | 已实现基础版 | `control.request_human_review` / `control.escalate` 写入 approval store 后，AgentLoop 进入 WAITING_FOR_APPROVAL 并暴露 approval_id / approval_kind |
| Workflow pause mapping | 已实现 | AgentLoopStepRunner 将 waiting_for_approval 映射为 StepStatus.PAUSED |
| approval decision resume context | 已增强 | ApprovalApplicationService 可为已决 approval 生成标准 buffer_updates / resume_metadata；API、CLI、MCP、Python SDK 已可读取该 resume context，Workflow resume 会记录 metadata |
| approval context checkpoint resume | 已实现基础版 | WorkflowRunner 可消费 approval resume context，按原 run_id 找最新 checkpoint 并恢复 paused Workflow |
| Workflow stalled mapping | 已实现 | AgentLoopStepRunner 将 stalled 映射为 StepStatus.BLOCKED |
| conversation diagnostics | 已实现 | conversation 中写入 diagnostic message，assistant result 仍保持最后 |
| agent artifact 输出 | 已增强 | WorkflowExecutor 会把 redacted LLM call request/response 写为 `llm_call` step artifacts，并写回 manifest/step result |
| sub-agent delegation | 暂不做 | 仍为目标态，不在本轮实现 |
| conversation compaction | 已实现基础版 | LocalJsonConversationStore 可生成 redacted deterministic compaction summary，AgentRunner 可按阈值自动触发 |
| cursor resume | 已实现基础版 | Workflow checkpoint/resume 已有；ConversationStore 已补 latest cursor 读写；AgentRunner 会在持久化/compaction 后写 cursor，并支持 opt-in cursor/summary resume context；Workflow AgentLoop step 已传 run_id/step_id/checkpoint metadata 和 resume flag；approval decision 可生成 resume context 并驱动 latest checkpoint resume；尚未做 mid-iteration replay |
| multi-layer LLM judge | 暂不做 | 当前 OutputJudge 仍是 deterministic local judge |

### K.4 边界保持

```text
AgentLoop 不直接调用 provider SDK。
AgentLoop 不直接调用业务 source/evidence/report 函数。
AgentLoop 不替代 WorkflowExecutor。
AgentLoop 不替代 final report Quality Gate。
AgentLoop 不直接执行工具函数，必须经 ToolExecutor。
AgentRunner 只负责装配，不写 daily intelligence 业务逻辑。
```

当前标准调用链：

```text
WorkflowExecutor
  -> AgentLoopStepRunner
      -> AgentRunner
          -> AgentLoop
              -> LLMClient
              -> ToolExecutor
              -> OutputJudge
              -> ConversationStore
```

### K.5 后续建议

下一阶段应优先做：

```text
1. Approval replay API/CLI/MCP 入口：在现有 resume context 接口之上，提供 approval decision 后一键恢复 paused Workflow 的受控入口。
2. AgentLoop mid-iteration replay 与 Workflow checkpoint 的更深绑定。
3. SubAgent delegation，但默认关闭。
4. 更完整的 JSON Schema keyword 覆盖和 schema registry 复用。
5. Phase-aware / LLM-assisted conversation compaction。
```
