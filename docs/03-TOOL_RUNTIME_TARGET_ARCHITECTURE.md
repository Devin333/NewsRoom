# 03-TOOL_RUNTIME.md

版本：v1.0-target-architecture
适用项目：News Intelligence System
模块：Tool Runtime / Tool System
定位：目标态架构设计，不是 MVP 简化版
日期：2026-05-11

---

### 0.2 v1.3 Tool Test Runner 命名约定

Tool Runtime 可以提供 `ToolTestRunner` 用于本地测试工具 schema、权限、参数校验、redaction 和大结果 artifact pointer。

`ToolTestRunner` 只是测试入口，不是生产执行路径；生产工具调用必须统一经过 `ToolExecutor`。


## 0. 文档定位

本文档定义 News Intelligence System 的 **最终目标态 Tool Runtime**。

注意：

- 本文档不是第一版实现说明。
- 本文档不是 MVP 裁剪方案。
- 本文档先定义最终系统应该具备的工具系统能力。
- 后续 MVP、P1、P2、生产化阶段，都应该从这个目标架构中裁剪实现范围。
- 第一版实现只是目标态 Tool Runtime 的一个子集，而不是反过来用第一版限制最终设计。

Tool Runtime 是 News Intelligence System 中负责 **工具定义、工具注册、工具权限、参数校验、工具执行、结果包装、审计、并发控制、安全隔离和 MCP 集成** 的执行层。

它和其他模块的关系是：

```text
AgentLoop
  -> ToolExecutor
      -> ToolRegistry
          -> Local Tool / MCP Tool / System Tool / Human Tool
```

---

## 0.1 v1.1 设计审查结论：Tool Runtime 的修订边界

本次审查不削弱 Tool Runtime 的目标态，而是区分两种容易混淆的 MCP 语义。

需要保留：ToolDefinition、ToolRegistry、ToolExecutor、ToolPolicy、ToolGuardrails、ToolObservation、artifact pointer、dangerous tool policy、agent-level allowlist。

需要修正：本文档中的 MCP 集成主要指 **News 作为 MCP Client / Tool Adapter 调用外部 MCP 工具**，而 `09-INTERFACES` 中的 MCP Server 指 **News 对外暴露能力**。

```text
Outbound MCP tool integration:
  External MCP Server -> MCPToolAdapter -> ToolRegistry -> ToolExecutor -> AgentLoop

Inbound News MCP Server:
  MCP Client / IDE / Agent -> News MCP Server -> Application Service -> Workflow / Worker / Storage
```

需要做设计减法：

```text
postgres.query / system.execute_command / file.write / file.delete / generic http.request
不应作为默认 LLM 可调用工具。

Source collection 的主路径应是 Source Pipeline deterministic connector，
不是让任意 Agent 通过 fetch_url 自由抓网页。
```

跨文档一致性要求：ToolRuntime 不做 LLM 调用、不做 workflow routing、不直接发布 report；它只执行受控工具并产出 ToolResult / ToolObservation。

---

## 0.2 v1.2 复查修订：Tool Approval 不是全局 Human Review

ToolRuntime 中的 approval 只处理“工具执行是否允许”的问题，尤其是外部写入、发布、文件写入、命令执行、通用 HTTP 请求等危险工具。

它不负责判断一份 report 是否可信，也不负责最终发布审批的业务结论。

```text
ToolApproval:
  这个工具调用能不能执行？

Quality HumanReview:
  这份报告/claim/quality result 能不能通过？

Worker waiting_for_approval:
  任务是否因为等待人工操作而暂停？

Interface Approvals API:
  人从哪里提交 approve/reject/modify？
```

因此 `ToolApprovalRequest` 应该只引用 tool_call、risk、side_effect_level、approval_reason，不应承载 report review 语义。


## 1. 为什么需要 Tool Runtime

在 Agent 系统里，LLM 本身只能“想”和“说”，真正改变外部世界、读取外部数据、查询历史、调用服务、写入系统的动作，都要通过工具完成。

News Intelligence System 最终会需要大量工具：

```text
source fetch tool
RSS parse tool
official blog fetch tool
GitHub search tool
Arxiv search tool
memory search tool
artifact load tool
PostgreSQL query tool
Qdrant search tool
report render tool
citation check tool
source health tool
notification tool
human review tool
publish tool
```

如果没有 Tool Runtime，系统会退化成：

```text
LLM 随便调用 Python 函数
函数随便读写系统
结果随便塞回上下文
失败没有统一记录
权限没有统一控制
工具输出没有统一格式
```

这会导致：

- 工具越权。
- 工具名冲突。
- 工具参数不稳定。
- LLM 调错工具。
- 结果过大塞爆上下文。
- 网络工具泄露 secret。
- 写操作没有审批。
- 无法审计工具到底做了什么。
- 无法判断哪些工具安全并发执行。
- MCP 工具和本地工具混在一起无法管理。

因此，Tool Runtime 是 AgentLoop 的“手”，也是系统安全边界之一。

---

## 2. 参考项目的通俗解释

### 2.1 Hive：像“可管理的工具库”

Hive 的工具系统值得重点参考。

Hive 的 README 里提到，它的安装会设置：

```text
framework - core agent runtime and graph executor
aden_tools - MCP tools for agent capabilities
credential store - encrypted API key storage
```

这说明 Hive 把工具能力和核心 runtime 分开：runtime 负责调度和执行，工具库作为单独能力包存在。

Hive 近期版本也强调 Tool Library / allowlist：queen 和 colony 可以维护自己的工具 allowlist，第一次编辑 allowlist 时会写出 `tools.json` sidecar；如果不编辑，默认行为仍然是允许所有 MCP tools。

通俗理解：

```text
Hive 不是把所有工具硬塞给所有 Agent，
而是让不同 Agent 拥有自己的工具清单。
```

这对 News 很重要。比如：

```text
WriterAgent 不应该拥有 fetch_url 工具
EditorAgent 不应该拥有 publish 工具
SourceCollector 可以拥有 fetch_url
HistorianAgent 可以拥有 search_memory
PublisherAgent 可以拥有 publish_report
```

### Hive 暴露出的几个经验教训

Hive 的 GitHub issue 也暴露了工具系统常见坑：

1. **工具名重复不能静默覆盖**
   Hive 有 issue 指出 `ToolRegistry.register()` 在重复工具名时会 silent overwrite，导致多个 MCP server 提供同名工具时只有最后一个生效，且很难 debug。

2. **异步工具调用不能乱建 event loop**
   Hive 有 issue 指出 HTTP MCP transport 在 async context 中调用工具时错误创建新 event loop，可能导致死锁、线程开销和并发问题。

3. **并发安全工具必须和真实注册名一致**
   Hive 有 issue 指出 `CONCURRENCY_SAFE_TOOLS` 里写的是 `grep`、`glob`、`list_directory`，但真实注册名是 `grep_search`、`glob_search`、`list_dir`，导致 speculative tool execution 死代码。

4. **通用 http_request 工具要非常谨慎**
   Hive 有 issue 提议增加 `http_request` 工具，支持 GET/POST、headers、body、timeout、JSON parsing 等。但这种工具能力很强，也更容易带来 SSRF、secret 泄露、外部副作用等风险。

News 应该吸收这些教训。

---

### 2.2 smolagents：像“函数外面包一层说明书”

smolagents 对工具的解释很清楚：

```text
Tool 本质上是 LLM 可以用的函数，
但不能只是函数。
它还需要 name、description、input types、input descriptions、output type。
所以它应该是一个包着函数和元数据的 class。
```

通俗理解：

```text
普通函数只会做事；
工具 = 会做事 + 会告诉 LLM 自己怎么用。
```

例如一个函数：

```python
def search_memory(query: str) -> list[dict]:
    ...
```

如果给 LLM 用，就必须变成：

```text
name: search_memory
description: Search historical reports and evidence.
inputs:
  query:
    type: string
    description: Search query.
output_type: object
```

News 应该借鉴这个思想：工具必须有稳定的机器可读 schema，而不是裸函数。

---

### 2.3 OpenAI Agents SDK：像“工具调用加护栏”

OpenAI Agents SDK 明确把工具分成 hosted tools、function tools、MCP 等，并强调使用 SDK 时，开发者可以直接控制 tools、MCP servers、runtime behavior、自定义存储和 server-managed conversation strategy。

它的 guardrails 文档也提到：

```text
Tool guardrails wrap function tools.
Input tool guardrails run before execution.
Output tool guardrails run after execution.
```

通俗理解：

```text
工具执行前检查一遍：
  这个工具能不能被调用？
  参数有没有问题？
  是否危险？

工具执行后再检查一遍：
  输出能不能给 LLM？
  是否包含 secret？
  是否太大？
  是否需要替换成安全摘要？
```

News 非常需要 tool guardrails，尤其是：

```text
fetch_url
http_request
publish_report
query_database
execute_command
write_file
send_notification
```

---

### 2.4 MCP：像“标准化外接工具插座”

MCP 可以理解为一种让 Agent 接入外部工具和资源的标准协议。

通俗理解：

```text
本地工具 = 你自己焊在机器上的工具
MCP 工具 = 外接插座，可以接不同服务
```

News 最终态应该支持 MCP，但不应该让 MCP 工具直接绕过自己的 Tool Runtime。

正确方式是：

```text
External MCP Server
  -> MCPToolAdapter
      -> ToolRegistry
          -> ToolPolicy / ToolGuardrails
              -> ToolExecutor
```

这里的 MCP 指 News 作为 MCP client 接入外部工具服务器。
如果是 News 对外暴露 MCP 能力，则属于 `09-INTERFACES_CLI_API_MCP_TARGET_ARCHITECTURE.md` 的 MCP Server。

也就是说，无论工具来自本地 Python、外部 MCP、HTTP，最终都要统一走 News 的工具权限、审计、结果包装和 redaction。

---

## 3. Hive Tool Runtime 是怎么做的

Hive 的工具体系分散在几个层面：

```text
core/framework/runner/tool_registry.py
core/framework/runner/mcp_client.py
core/framework/graph/event_loop_node.py
tools/src/aden_tools/tools/
mcp_servers.json
tools.json allowlist
credential store
```

### 3.1 Hive 的核心思路

Hive 的核心思路可以理解为：

```text
ToolRegistry 保存工具定义和 executor
Agent/Node 通过 allowlist 选择可用工具
EventLoopNode 解析 LLM tool call
ToolExecutor 调用本地工具或 MCP 工具
工具结果写回 conversation
大结果可以通过 pointer 方式保存
```

### 3.2 Hive 值得借鉴的设计

#### 1. 工具注册中心

Hive 有 ToolRegistry，用于把工具名映射到工具定义和 executor。

News 也需要：

```text
ToolRegistry
  register(tool)
  get(tool_name)
  list_tools()
  list_tools_for_agent(agent_id)
  export_schema_for_llm(agent_id)
```

但必须修正 Hive issue 暴露的问题：

```text
重复工具名不能 silent overwrite
必须支持 namespace
必须支持 duplicate conflict policy
```

#### 2. Agent-level allowlist

Hive 的 Tool Library 让 queen / colony 可以有自己的工具 allowlist。

News 也应该这样：

```text
AgentSpec.allowed_tools
ToolPolicy.allowed_tools
ToolPolicy.blocked_tools
ToolScope
```

例如：

```text
WriterAgent:
  allowed_tools = []

HistorianAgent:
  allowed_tools = ["memory.search", "artifact.load"]

SourceCollectorAgent:
  allowed_tools = ["source.fetch_url", "source.parse_rss"]

PublisherAgent:
  allowed_tools = ["report.publish", "notification.send"]
```

#### 3. MCP 工具统一接入

Hive 支持 MCP tools for agent capabilities。

News 也应该支持 MCP，但要统一适配成 `ToolDefinition`：

```text
MCP tool schema
  -> MCPToolAdapter
  -> ToolDefinition
  -> ToolRegistry
```

#### 4. 工具结果 pointer

Hive 架构里有一个很重要的思想：工具结果太大时，不把完整结果塞进 conversation，而是写到文件，再给 LLM 一个 compact reference。

News 必须采用这个模式。

例如：

```text
RSS 抓取结果 500KB
GitHub issue 搜索结果 2MB
Web page 内容 1MB

不要塞进 LLM context
写入 artifact
conversation 里只放 summary + ArtifactRef
```

#### 5. 并发安全工具标记

Hive issue 说明并发安全工具 allowlist 很容易因为命名不一致失效。

News 应该把并发安全变成工具元数据，而不是写死字符串列表：

```text
ToolDefinition.concurrency_safe = True
ToolDefinition.side_effect_level = read_only
```

然后由 ToolRegistry 校验：

```text
所有 concurrency_safe 工具必须真实存在
写操作工具不能标记为 concurrency_safe
并发执行前检查 tool metadata
```

---

## 4. News 最终态 Tool Runtime 目标

News Tool Runtime 最终应该支持：

```text
local Python tools
MCP tools
system control tools
human tools
tool registry
tool namespace
tool versioning
tool allowlist
tool denylist
tool schema export
tool args validation
tool input guardrails
tool output guardrails
tool execution policy
tool timeout
tool retry
tool concurrency control
tool side-effect classification
tool result pointer
tool artifact logging
tool result redaction
tool event logging
tool metrics
tool sandboxing
tool secret policy
tool approval policy
tool discovery
tool testing runner
```

---

## 5. Tool Runtime 和其他模块的边界

### 5.1 AgentLoop 负责

```text
解析 LLM 输出中的 tool_call
决定是否继续循环
把 observation 放回 conversation
使用 judge 判断最终输出
```

### 5.2 Tool Runtime 负责

```text
工具是否存在
Agent 是否有权调用
参数是否合法
工具怎么执行
超时怎么处理
失败怎么包装
结果怎么 redaction
大结果怎么 spill
如何记录事件和 metrics
```

### 5.3 Workflow Runtime 负责

```text
哪个 step 可以运行
step 成功或失败后去哪里
artifact 和 manifest 怎么写
```

### 5.4 LLM Layer 负责

```text
把 tool schema 暴露给 model
解析 provider-native tool call
处理模型响应
```

### 5.5 Security / Guardrails 负责

```text
输入安全
输出安全
危险工具审批
secret redaction
domain allowlist / denylist
```

---

## 6. 工具分类体系

最终态建议把工具分成以下类型。

### 6.1 Source Tools

```text
source.fetch_url
source.parse_rss
source.parse_atom
source.fetch_official_blog
source.check_health
source.probe
```

用途：

```text
真实来源抓取
RSS/Atom 解析
source health
fallback
```

### 6.2 Search / Retrieval Tools

```text
memory.search
artifact.search
report.search
source.search
github.search
arxiv.search
web.search
```

用途：

```text
历史 evidence 召回
报告检索
外部公开信息搜索
```

### 6.3 Storage Tools

```text
postgres.query
postgres.insert_report
postgres.update_source_health
qdrant.upsert
qdrant.search
local_json.save
```

用途：

```text
结构化存储
向量记忆
本地 repository
```

### 6.4 Report Tools

```text
report.render_markdown
report.render_json
report.validate
report.publish
report.export
```

用途：

```text
报告渲染
报告校验
报告发布
```

### 6.5 Quality Tools

```text
quality.citation_check
quality.claim_support_check
quality.duplicate_check
quality.editor_score
```

用途：

```text
质量检查
引用检查
claim 支持性检查
```

### 6.6 Control Tools

```text
control.set_output
control.request_human_review
control.escalate
control.delegate_to_subagent
control.report_progress
```

用途：

```text
AgentLoop 控制
子 Agent 委托
人工介入
```

### 6.7 Notification Tools

```text
notification.email
notification.webhook
notification.slack
notification.rss_publish
```

用途：

```text
发布和通知
```

### 6.8 Dangerous / Privileged Tools

```text
system.execute_command
file.write
file.delete
http.request
publish.external
```

这些工具必须默认关闭，并需要更严格 policy。

---

## 7. 核心模型设计

### 7.1 ToolDefinition

```python
class ToolDefinition(BaseModel):
    tool_id: str
    name: str
    namespace: str
    version: str = "1.0.0"

    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None

    source: Literal["local", "mcp", "system", "human"]
    category: str

    side_effect_level: Literal[
        "read_only",
        "writes_local_state",
        "writes_external_state",
        "destructive",
        "publishing"
    ] = "read_only"

    concurrency_safe: bool = False
    requires_approval: bool = False
    requires_secret: bool = False

    timeout_seconds: int = 30
    max_result_bytes: int = 1_000_000

    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 7.2 ToolCall

```python
class ToolCall(BaseModel):
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]

    requested_by_agent_id: str
    run_id: str
    step_id: str
    conversation_id: str | None = None

    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 7.3 ToolResult

```python
class ToolResult(BaseModel):
    tool_call_id: str
    tool_name: str

    status: Literal["succeeded", "failed", "blocked", "timeout", "approval_required"]

    output: dict[str, Any] | None = None
    output_summary: str | None = None

    error_type: str | None = None
    error_message: str | None = None

    artifact_refs: list[ArtifactRef] = Field(default_factory=list)

    redacted: bool = True
    elapsed_ms: int | None = None
    output_bytes: int | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 7.4 ToolObservation

```python
class ToolObservation(BaseModel):
    tool_call_id: str
    tool_name: str
    status: str

    summary: str
    highlights: list[str] = Field(default_factory=list)

    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    safe_for_llm: bool = True
```

### 7.5 ToolPolicy

```python
class ToolPolicy(BaseModel):
    allowed_tools: list[str] = Field(default_factory=list)
    blocked_tools: list[str] = Field(default_factory=list)

    allow_mcp_tools: bool = False
    allow_dangerous_tools: bool = False

    max_tool_calls_per_iteration: int = 3
    max_tool_calls_per_agent: int = 20

    require_approval_for_side_effects: bool = True
    require_approval_for_external_write: bool = True
    require_approval_for_publish: bool = True

    max_result_chars_inline: int = 8000
    spill_large_results_to_artifact: bool = True

    timeout_seconds_default: int = 30
```

### 7.6 ToolExecutionRecord

```python
class ToolExecutionRecord(BaseModel):
    tool_call: ToolCall
    tool_result: ToolResult

    validation_passed: bool
    guardrails_passed: bool
    approval_required: bool
    approval_id: str | None = None

    started_at: datetime
    finished_at: datetime | None = None

    events: list[str] = Field(default_factory=list)
```

---

## 8. ToolRegistry 目标态设计

### 8.1 ToolRegistry 职责

```text
注册工具
查询工具
按 agent 导出工具 schema
检测重复工具名
管理工具 namespace
管理工具版本
加载 local tools
加载 MCP tools
加载 system tools
加载 human tools
```

### 8.2 ToolRegistry 接口

```python
class ToolRegistry:
    def register(self, definition: ToolDefinition, executor: ToolExecutorFn) -> None: ...
    def unregister(self, tool_name: str) -> None: ...
    def get(self, tool_name: str) -> RegisteredTool: ...
    def list_tools(self) -> list[ToolDefinition]: ...
    def list_tools_for_agent(self, agent_id: str, policy: ToolPolicy) -> list[ToolDefinition]: ...
    def export_schema_for_llm(self, agent_id: str, policy: ToolPolicy) -> list[dict[str, Any]]: ...
    def validate_no_conflicts(self) -> ValidationResult: ...
```

### 8.3 工具命名规则

不要只用短名：

```text
search
fetch
query
```

应该使用 namespace：

```text
memory.search
source.fetch_url
github.search_repositories
artifact.load
report.render_markdown
```

原因：

- 防止 MCP server 工具名冲突。
- 便于 allowlist。
- 便于安全策略。
- 便于日志和审计。

### 8.4 Duplicate Policy

重复工具名不能静默覆盖。

支持：

```text
error
skip
replace_explicit
versioned
namespace_required
```

默认：

```text
error
```

---

## 9. ToolExecutor 目标态设计

### 9.1 执行流程

```text
1. 接收 ToolCall
2. 从 ToolRegistry 找工具
3. 检查 Agent 是否有权限
4. 检查 tool 是否被 blocked
5. 校验 arguments schema
6. 执行 input guardrails
7. 判断是否需要 approval
8. 执行工具
9. 执行 output guardrails
10. redaction
11. 判断是否 spill 到 artifact
12. 构造 ToolResult
13. 构造 ToolObservation
14. 记录 events / metrics / artifact
```

### 9.2 伪代码

```python
class ToolExecutor:
    async def execute(
        self,
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolResult:
        tool = self.registry.get(call.tool_name)

        self.permission_checker.check(
            tool=tool.definition,
            agent_id=call.requested_by_agent_id,
            policy=context.tool_policy,
        )

        args = self.argument_validator.validate(
            schema=tool.definition.input_schema,
            arguments=call.arguments,
        )

        guardrail_result = await self.input_guardrails.check(tool.definition, args, context)
        if guardrail_result.blocked:
            return ToolResult.blocked(...)

        approval = await self.approval_policy.check(tool.definition, args, context)
        if approval.required:
            return ToolResult.approval_required(...)

        raw_result = await self.invoker.invoke(tool, args, context)

        checked_result = await self.output_guardrails.check(tool.definition, raw_result, context)
        redacted = self.redactor.redact(checked_result)

        result = await self.result_builder.build(
            tool=tool.definition,
            raw_result=redacted,
            context=context,
        )

        await self.event_emitter.emit_tool_result(result)
        return result
```

---

## 10. Tool Guardrails 设计

### 10.1 Input Guardrails

执行前检查：

```text
tool 是否允许
参数 schema 是否正确
URL 是否在 allowlist
domain 是否被 denylist
method 是否危险
是否包含 secret
是否请求写操作
是否超过 timeout / size / cost 限制
是否需要 human approval
```

### 10.2 Output Guardrails

执行后检查：

```text
是否包含 secret
是否包含 cookie / token / authorization header
是否太大
是否包含 HTML/script 噪音
是否需要摘要化
是否需要 artifact pointer
是否 safe_for_llm
```

### 10.3 Dangerous Tool Policy

危险工具包括：

```text
execute_command
file.write
file.delete
http.request
publish.external
send.email
database.write
```

默认策略：

```text
disabled_by_default
requires_explicit_allowlist
requires_human_approval
logs_full_redacted_record
no_parallel_execution
```

---

## 11. Tool Result Pointer Pattern

### 11.1 为什么需要

工具结果经常很大：

```text
RSS feed
web page
GitHub issue list
paper search results
memory search results
database query result
```

不能全部塞进 LLM conversation。

### 11.2 设计

```text
raw tool result
  -> artifact file
  -> ToolResult.artifact_refs
  -> ToolObservation.summary
  -> LLM sees compact observation
```

### 11.3 Observation 示例

```json
{
  "tool_name": "github.search_repositories",
  "status": "succeeded",
  "summary": "Found 20 repositories related to agent runtime.",
  "highlights": [
    "3 repositories mention graph executor.",
    "5 repositories expose ToolRegistry-like abstractions."
  ],
  "artifact_refs": [
    {
      "artifact_id": "artifact_tool_result_001",
      "path": "steps/analyze/tool_results/github_search_001.json"
    }
  ],
  "safe_for_llm": true
}
```

---

## 12. MCP 集成设计

### 12.1 MCPToolAdapter

```python
class MCPToolAdapter:
    async def list_tools(self, server: MCPServerConfig) -> list[ToolDefinition]: ...
    async def call_tool(self, server: MCPServerConfig, call: ToolCall) -> ToolResult: ...
```

### 12.2 MCPServerConfig

```python
class MCPServerConfig(BaseModel):
    server_id: str
    name: str

    transport: Literal["stdio", "http", "sse"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    headers_env: dict[str, str] = Field(default_factory=dict)

    enabled: bool = True
    timeout_seconds: int = 30
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 12.3 MCP 接入规则

```text
MCP 工具必须 namespace 化
MCP 工具必须进入 ToolRegistry
MCP 工具必须受 Agent allowed_tools 控制
MCP 工具必须经过 guardrails
MCP 工具结果必须 redaction
MCP 工具不得直接绕过 ToolExecutor
```

---

## 13. 并发与副作用设计

### 13.1 ToolSideEffectLevel

```text
read_only
writes_local_state
writes_external_state
destructive
publishing
```

### 13.2 Concurrency Rules

```text
read_only + concurrency_safe = 可并发
writes_local_state = 默认串行
writes_external_state = 默认串行 + approval
destructive = 禁止自动执行
publishing = human approval required
```

### 13.3 ToolBatchExecutor

最终态支持批量工具：

```python
class ToolBatchExecutor:
    async def execute_batch(
        self,
        calls: list[ToolCall],
        context: ToolExecutionContext,
    ) -> list[ToolResult]:
        ...
```

执行策略：

```text
parallel_for_read_only
serial_for_writes
fail_fast
continue_on_error
threshold_success
```

---

## 14. Secret 与 Credential 设计

### 14.1 Secret 来源

```text
.env
environment variables
credential store
runtime secret provider
```

### 14.2 Tool 不应该直接保存 secret

工具定义中只允许写：

```text
required_secret_names
```

例如：

```python
required_secret_names = ["GITHUB_TOKEN"]
```

真实 secret 由：

```text
SecretProvider
```

在执行时注入。

### 14.3 Redaction

必须 redaction：

```text
Authorization header
API key
cookie
session token
database password
signed URL
personal access token
```

### 14.4 Artifact 要求

工具 artifact 只能写：

```text
redacted arguments
redacted result
elapsed time
status
error type
artifact refs
```

不能写真实 secret。

---

## 15. Human Approval 设计

某些工具不能让 Agent 自动执行。

需要 approval 的场景：

```text
publish report
send notification
write database
delete file
execute command
external POST/PUT/PATCH/DELETE
costly operation
```

### 15.1 ApprovalRequest

```python
class ToolApprovalRequest(BaseModel):
    approval_id: str
    run_id: str
    step_id: str
    agent_id: str
    tool_call: ToolCall
    reason: str
    risk_level: Literal["low", "medium", "high", "critical"]
    created_at: datetime
```

### 15.2 Approval Decision

```text
approved
rejected
modified
expired
```

### 15.3 Workflow 行为

```text
approval_required
  -> workflow paused
  -> checkpoint created
  -> human decision recorded
  -> workflow resumed
```

---

## 16. Tool Events 与 Metrics

### 16.1 Event Types

```text
tool_registered
tool_registration_conflict
tool_call_requested
tool_call_blocked
tool_args_validated
tool_input_guardrail_failed
tool_approval_required
tool_started
tool_succeeded
tool_failed
tool_timeout
tool_output_guardrail_failed
tool_result_redacted
tool_result_spilled
tool_observation_created
```

### 16.2 Metrics

```python
class ToolMetrics(BaseModel):
    total_calls: int = 0
    succeeded_calls: int = 0
    failed_calls: int = 0
    blocked_calls: int = 0
    approval_required_calls: int = 0

    total_elapsed_ms: int = 0
    total_output_bytes: int = 0
    spilled_result_count: int = 0

    calls_by_tool: dict[str, int] = Field(default_factory=dict)
    failures_by_error_type: dict[str, int] = Field(default_factory=dict)
```

---

## 17. News 专属工具设计

### 17.1 MVP 到最终态都会需要的核心工具

```text
source.fetch_url
source.parse_rss
source.normalize_url
source.extract_items
report.render_markdown
quality.citation_check
artifact.load
artifact.write
```

### 17.2 Post-MVP 工具

```text
memory.search
memory.index
postgres.query
postgres.save_report
qdrant.search
github.search_repositories
github.fetch_release
arxiv.search_papers
notification.send_email
notification.webhook
report.publish
```

### 17.3 高风险工具

```text
http.request
system.execute_command
file.write
file.delete
database.write_raw
notification.send_external
publish.public
```

默认禁用。

---

## 18. 目标态目录结构建议

```text
core/framework/tools/
  __init__.py

  specs/
    tool_definition.py
    tool_policy.py
    tool_schema.py
    approval_spec.py

  registry/
    registry.py
    registered_tool.py
    namespace.py
    conflict_policy.py
    discovery.py

  execution/
    executor.py
    batch_executor.py
    invoker.py
    context.py
    result_builder.py

  validation/
    args_validator.py
    schema_exporter.py
    compatibility.py

  guardrails/
    input_guardrails.py
    output_guardrails.py
    dangerous_tool_policy.py
    domain_policy.py

  observations/
    observation.py
    observation_builder.py
    pointer.py

  mcp/
    server_config.py
    adapter.py
    client.py
    discovery.py

  approval/
    approval_request.py
    approval_store.py
    approval_handler.py

  secrets/
    secret_provider.py
    redactor.py

  events/
    event_models.py
    event_emitter.py

  metrics/
    models.py
    collector.py

  builtin/
    source_tools.py
    artifact_tools.py
    report_tools.py
    quality_tools.py
    control_tools.py

  errors/
    error_types.py
    exceptions.py
```

---

## 19. 和 Hive 的最终取舍

### 19.1 借鉴 Hive

```text
ToolRegistry
MCP tools for agent capabilities
agent/queen/colony-level allowlist
tools.json sidecar 思路
credential store 思路
EventLoopNode 调用工具并写回 conversation
tool result pointer pattern
MCP server config
concurrency-safe 工具思路
synthetic control tools
```

### 19.2 不照搬 Hive

```text
不允许重复工具名 silent overwrite
不把所有 MCP 工具默认暴露给所有 Agent
不把 concurrency-safe 写成不可校验的字符串列表
不让 HTTP/MCP 工具绕过 async runtime
不让通用 http_request 默认开启
不把大工具结果直接塞进 conversation
不让 Writer 拥有外部 fetch/search 工具
不让 Editor 拥有新增事实的工具
```

### 19.3 News 自己的目标态

```text
ToolDefinition 是一等 contract
ToolRegistry 必须 namespace + version
ToolPolicy 必须 agent-level
ToolGuardrails 必须 input/output 双向
ToolResult 默认支持 artifact pointer
Dangerous tools 默认关闭
MCP tools 统一适配为 ToolDefinition
Tool execution 必须有 event、metrics、artifact
Side effect level 决定并发和 approval
Evidence boundary 决定 Agent 可用工具
```

---

## 20. 分阶段裁剪原则

本文档定义最终态。后续第一阶段可以只实现子集，但不能破坏最终架构。

裁剪原则：

```text
目标态先定完整边界
第一阶段只取最小可运行链路
命名、接口、目录和最终态保持兼容
后续只是补 MCP、approval、guardrails、batch、sandbox、discovery
不要推翻 Tool Runtime
```

例如第一阶段可以只实现：

```text
ToolDefinition
ToolCall
ToolResult
ToolObservation
ToolRegistry
ToolExecutor
ArgsValidator
SchemaExporter
BasicToolPolicy
BasicRedactor
```

但目录和接口应与最终态兼容。

---

## 21. 最终态验收标准

Tool Runtime 最终完成时，应该满足：

```text
支持 local Python tools
支持 MCP tools
支持 tool namespace
支持 tool versioning
支持 duplicate conflict detection
支持 agent-level allowlist
支持 blocked tools
支持 args schema validation
支持 input guardrails
支持 output guardrails
支持 human approval
支持 side-effect classification
支持 concurrency control
支持 tool batch execution
支持 tool result pointer
支持 artifact logging
支持 secret redaction
支持 ToolObservation
支持 tool events
支持 tool metrics
支持 dangerous tool policy
支持 tool discovery
支持 Tool schema export for LLM
```

---

## 22. 总结

News Tool Runtime 的最终目标不是一个简单函数注册器，也不是把 Python 函数直接暴露给 LLM。

它应该是：

```text
面向情报生产的受控工具执行系统
```

它吸收 Hive 的 ToolRegistry、MCP tools、allowlist、tool result pointer、credential store 和 EventLoopNode 工具调用思想，也参考 smolagents 的 Tool metadata、OpenAI Agents SDK 的 function tools / guardrails / handoffs、MCP 的外部工具接入方式。

但 News 必须强化自己的业务和安全边界：

```text
agent-level tool allowlist
evidence boundary
citation boundary
dangerous tool approval
tool result artifact pointer
secret redaction
tool audit events
side-effect-aware concurrency
MCP tool namespace
```

后续 MVP、第一版、第二版都应该从这个最终态目标中裁剪实现，而不是用第一版的简单实现反向定义 Tool Runtime 的上限。

---
# 本版保留说明

以上内容为原目标态文档主体内容，已完整保留。下面追加的是 v2.0 设计书级补强，用于把原目标态说明转化为更可开发、可验收、可维护的工程设计书。

---
# v2.0 设计书级补强：Tool Runtime 工程化设计

## A. 本模块最终职责

ToolRuntime 是 AgentLoop 的“手”，负责工具定义、注册、权限、参数校验、执行、结果包装、审计和风险控制。

它不负责：

```text
LLM 调用
workflow routing
report 可信度判断
source 主链路采集
API/MCP 对外入口
```

## B. 核心对象

```text
ToolDefinition
ToolParameter
ToolCall
ToolResult
ToolObservation
ToolExecutionRecord
ToolRegistry
ToolExecutor
ToolPolicy
ToolApprovalRequest
MCPToolAdapter
```

## C. ToolDefinition

```python
class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None

    side_effect_level: Literal["none", "read", "write", "external_write", "dangerous"]
    concurrency_safe: bool = False
    timeout_seconds: int = 30

    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

## D. 默认禁止工具

默认不能给 LLM：

```text
system.execute_command
file.write
file.delete
postgres.query
generic_http_request
publish_report
send_email
modify_source_registry
```

这些必须经过显式 allowlist + approval policy。

## E. Agent 级 allowlist

```text
AgentSpec.allowed_tools 是第一层。
ToolPolicy 是第二层。
ApprovalPolicy 是第三层。
ToolExecutor 是唯一执行入口。
```

## F. ToolResult 设计

```python
class ToolResult(BaseModel):
    call_id: str
    tool_name: str
    status: Literal["succeeded", "failed", "blocked", "approval_required"]

    output: Any | None = None
    observation_text: str | None = None
    artifact_ref: ArtifactRef | None = None

    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int
```

大结果必须转 artifact pointer，不能塞满 Agent prompt。

## G. MCP 边界

Outbound MCP：

```text
External MCP Server -> MCPToolAdapter -> ToolRegistry -> ToolExecutor -> AgentLoop
```

Inbound MCP：

```text
MCP Client -> News MCP Server -> Application Service -> Workflow/Storage
```

二者目录、命名和权限必须分开。

## H. 代码组织建议

初期：

```text
runtime/tools.py
```

内部 section：

```text
Models
Policies
Registry
Executor
FunctionTool
MCPToolAdapter
TestRunner
Built-in Tools
```

## I. 测试矩阵

```text
test_register_duplicate_tool_fails
test_tool_args_validation
test_denied_tool_blocked
test_tool_timeout
test_large_output_spills_to_artifact
test_approval_required
test_concurrency_safe_metadata
test_mcp_tool_name_namespace
```

## J. 验收清单

```text
[ ] 工具名重复不允许 silent overwrite。
[ ] 所有工具调用都有 ToolExecutionRecord。
[ ] WriterAgent 默认没有 fetch_url。
[ ] dangerous tool 必须 approval。
[ ] generic http request 不默认开放。
[ ] tool result 支持 artifact pointer。
```

## K. 当前代码进度映射：v2.1-current-code-aligned

截至 2026-05-14，仓库中的 Tool Runtime 已经不是简单函数注册器。后续开发应基于现有 `core/framework/tools` 继续收口，而不是重写工具系统。

| 能力 | 当前状态 | 对应代码 | 说明 |
|---|---|---|---|
| ToolDefinition | 已实现 | `core/framework/tools/models.py` | 已有 name、description、input_schema、side_effect、dangerous、approval、timeout、retry、result size、secret、version |
| ToolPolicy | 已实现 | `core/framework/tools/models.py` | 支持 allowlist、blocklist、MCP gate、dangerous gate、approval、inline size、timeout、attempts |
| ToolCall | 已实现 | `core/framework/tools/models.py` | 支持 call_id、tool_name、arguments、requested_by_agent_id，序列化时会脱敏 |
| ToolResult | 已实现 | `core/framework/tools/models.py` | 支持 succeeded/failed/blocked/approval_required/timeout、artifact refs、error、approval_id、output_bytes |
| ToolObservation | 已实现 | `core/framework/tools/models.py` | AgentLoop 可消费的安全 observation 形态，包含 summary、highlights、safe_for_llm |
| ArtifactRef | 已实现 | `core/framework/tools/models.py` | Tool Runtime 内部轻量 artifact pointer，不替代 Storage canonical model |
| ToolRegistry | 已实现 | `core/framework/tools/registry.py` | 支持注册、查找、重复策略、agent schema export、冲突校验 |
| Duplicate policy | 已实现 | `core/framework/tools/registry.py` | 支持 error、skip、replace_explicit，避免 silent overwrite |
| ToolExecutor | 已实现 | `core/framework/tools/executor.py` | 唯一生产执行入口，执行 policy、schema、approval、secret、retry、timeout、redaction、artifact spill、event、metrics |
| Argument validation | 已实现 | `core/framework/tools/validation.py` | 支持 required、type、enum、object/list 等基础 JSON schema 子集 |
| Dangerous gate | 已实现 | `core/framework/tools/executor.py` | dangerous tool 默认 blocked，必须显式 allow_dangerous_tools |
| MCP gate | 已实现 | `ToolPolicy + ToolExecutor` | `mcp.*` 默认不可调用，需 allow_mcp_tools |
| Approval request | 已实现 | `core/framework/tools/approval.py` + `executor.py` | Tool Approval 只处理工具调用是否允许，不承载 report review 语义 |
| Secret provider | 已实现 | `core/framework/tools/secrets.py` | 工具可声明 required_secret_names，通过 provider 注入 runtime secrets |
| Redaction | 已实现 | `core/framework/tools/redaction.py` | 参数、输出、事件、record 序列化路径会脱敏 |
| Large result spill | 已实现 | `ToolExecutor + ArtifactManager` | 大输出可写 artifact，observation 返回 artifact ref |
| Retry / timeout | 已实现 | `ToolExecutor` | 支持 tool-level 与 policy default attempts/timeout |
| Telemetry | 已实现 | `core/framework/tools/telemetry.py` | ToolEvent、ToolMetrics、ToolExecutionRecord 已有 |
| ToolBatchExecutor | 已实现 | `core/framework/tools/batch.py` | 支持顺序/并发批量执行与 budget guard |
| ToolTestRunner | 已实现 | `core/framework/tools/testing.py` | 本地测试入口，不是生产执行路径 |
| Built-in registry factory | 已实现 | `core/framework/tools/catalog.py` | `build_builtin_tool_registry()` 通过可选依赖注入注册当前可用工具 |
| ToolCatalog | 已实现 | `core/framework/tools/catalog.py` | 支持按 policy 导出工具目录和 namespace summary |
| Agent/tool boundary audit | 已实现 | `core/framework/tools/boundary.py` | 可检查 Writer/Editor 误暴露外部 fetch/search 工具 |
| Outbound MCP adapter | 基础可用 | `core/framework/tools/mcp_adapter.py` | 定义外部 MCP tool adapter 边界，生产 transport 仍需按环境接入 |
| Built-in artifact tools | 已实现 | `artifact_tools.py` | artifact.load/write/search 等受 ArtifactManager 注入控制 |
| Built-in source tools | 已实现 | `source_tools.py` | source.fetch_url、parse_rss、normalize_url、extract_items、health 等受控工具 |
| Built-in report tools | 已实现 | `report_tools.py` | render/validate/search/export/publish 等工具按依赖注入启用 |
| Built-in quality tools | 已实现 | `quality_tools.py` | duplicate_check、claim_support、editor_score、citation_check 等确定性质量工具 |
| Built-in memory/qdrant tools | 已实现 | `memory_tools.py` / `qdrant_tools.py` | memory.search/index、qdrant.search/upsert 通过 vector store 注入启用 |
| Built-in GitHub/arXiv/web tools | 已实现 | `github_tools.py` / `arxiv_tools.py` / `web_search_tools.py` | 网络工具由 `include_network_tools` 和 provider/connector 注入控制 |
| Built-in notification tools | 已实现 | `notification_tools.py` | webhook/email/slack/rss publish 等 side-effect 工具按依赖注入启用 |
| Built-in PostgreSQL/local JSON tools | 已实现 | `postgres_tools.py` / `local_json_tools.py` | 持久化工具通过 repository/root 注入启用 |
| Runtime inspection | 本轮新增 | `core/framework/tools/inspection.py` | 汇总 registry、policy、risk、boundary、executor metrics/events/records |

总体判断：

```text
Tool Runtime 已经达到 P2/P3 核心完成：
  ToolDefinition / ToolPolicy / ToolRegistry / ToolExecutor / ToolObservation 稳定；
  approval / secret / redaction / telemetry / artifact pointer / batch 已落地；
  大量内置工具已按可选依赖注入方式接入；
  需要继续收口的是 inspection、当前代码映射、生产 MCP transport、跨模块治理边界。
```

## L. 当前完成、雏形、暂不做

### L.1 已完成能力

```text
ToolDefinition / ToolPolicy / ToolCall / ToolResult / ToolObservation
ToolRegistry 注册、查找、重复策略、冲突校验
ToolExecutor policy gate、argument validation、approval gate
dangerous tool 默认阻断
MCP tool 默认阻断
tool timeout / retry
tool output redaction
large result artifact pointer
ToolEvent / ToolMetrics / ToolExecutionRecord
ToolBatchExecutor
ToolTestRunner
ToolCatalog / build_builtin_tool_registry
Agent/tool boundary audit
artifact/source/report/quality/memory/qdrant/postgres/local_json/notification/control built-in tools
```

### L.2 雏形可用能力

```text
Outbound MCP adapter:
  已有 adapter 和 registry 接入边界；
  生产级 MCP transport、认证、streaming、错误 taxonomy 还需要继续和 09 Interfaces 区分。

Notification tools:
  webhook/email/slack/rss publish 已可按依赖注入注册；
  生产 delivery retry、provider audit、template policy 可继续增强。

PostgreSQL/Qdrant tools:
  已有 repository/vector store 注入路径；
  生产连接池、权限隔离、tenant policy 继续归 Storage/Memory 和 deployment 层。

Runtime inspection:
  本轮新增 registry/policy/executor inspection；
  后续可接入 CLI/API/MCP 的只读诊断接口，但不能绕过 ToolExecutor 执行工具。
```

### L.3 暂不做能力

```text
不新增 generic shell/file/http tool 作为默认 LLM 可调用工具。
不让 Tool Runtime 直接调用 LLM provider。
不让 Tool Runtime 负责 workflow routing。
不让 Tool Approval 替代 Evidence/Quality 的 report human review。
不把 Source/Evidence/Report/Storage canonical model 搬进 Tool Runtime。
不让 MCP server inbound interface 绕过 Application Service / Workflow / Storage。
不把所有工具拆成大型插件系统；当前 flat package 继续保留。
```

## M. 当前代码边界说明

目标调用链仍然是：

```text
AgentLoop
  -> ToolExecutor.execute(ToolCall, ToolPolicy)
      -> ToolRegistry.get(tool_name)
          -> registered executor function
```

Tool Runtime 拥有：

```text
ToolDefinition
ToolPolicy
ToolCall
ToolResult
ToolObservation
ToolRegistry
ToolExecutor
ToolBatchExecutor
ToolEvent
ToolMetrics
ToolExecutionRecord
ToolCatalog
ToolTestRunner
ToolRuntimeInspectionReport
```

Tool Runtime 不拥有：

```text
WorkflowSpec / routing / checkpoint
Agent prompt / parser / judge
LLMRequest / provider fallback
SourceDefinition / SourceConnector canonical model
EvidenceItem / Claim / Report canonical model
RunStore / ArtifactStore / EventStore canonical model
CLI/API/MCP response model
Worker TaskStatus
```

## N. Runtime Inspection 设计

本轮新增 `core/framework/tools/inspection.py`，目的不是再造一个治理系统，而是把已有运行时状态变成可检查对象。

支持：

```text
inspect_tool_registry(registry, policy=None, agent_id=None, agent_tool_policies=None)
inspect_tool_policy(registry, policy, agent_id=None)
inspect_tool_executor(executor, recent_limit=20)
inspect_tool_runtime(registry, policy=None, executor=None, agent_id=None, agent_tool_policies=None)
classify_tool_risk(definition)
```

输出对象：

```text
ToolRuntimeInspectionReport
ToolRegistryInspection
ToolPolicyInspection
ToolExecutorInspection
ToolDefinitionInspection
ToolNamespaceSummary
ToolRiskSummary
ToolInspectionFinding
```

Inspection 只读：

```text
读取 registry definitions
读取 policy exposure
读取 executor metrics/events/records
读取 agent_tool_policies 做边界审计
不执行工具
不调用外部服务
不写 artifact
不修改 policy
不替代 ToolExecutor gate
```

典型用途：

```text
CI 检查 tool registry posture
调试 Agent 可见工具列表
检查 Writer/Editor 是否误暴露外部 fetch/search 工具
查看 dangerous/side-effect/approval/secret tool 分布
查看 ToolExecutor 最近执行记录和状态分布
作为 CLI/API/MCP 只读诊断接口的数据来源
```

## O. 后续落地路线

### O.1 P2/P3 收口

```text
1. 保持 ToolExecutor 为唯一生产执行入口。
2. 保持 build_builtin_tool_registry 通过可选依赖注入启用工具。
3. 在 AgentRunner / workflow step 中继续传入明确 ToolPolicy。
4. 为 agent-facing policies 增加 inspection smoke。
5. 将 ToolRuntimeInspectionReport 接入只读 diagnostics service，但不在本轮改 CLI/API。
```

### O.2 P4/P5 生产化

```text
1. Outbound MCP transport 生产化。
2. approval store 和 worker waiting 状态进一步对齐。
3. notification delivery retry / audit。
4. tool execution record 持久化到 Storage-owned store。
5. tenant/project scoped tool policies。
6. secrets provider 对接部署环境。
```

### O.3 暂缓

```text
1. 默认开放 generic_http_request。
2. 默认开放 shell/file write/delete。
3. 在 Tool Runtime 内做 LLM tool selection。
4. 将 Tool Runtime 改造成独立远程执行平台。
```

## P. 本轮测试验收

本轮新增/覆盖：

```text
test_classify_tool_risk_is_deterministic
test_inspect_tool_policy_reports_exposure_and_unknown_tools
test_inspect_tool_registry_reports_risk_namespaces_and_findings
test_inspect_tool_executor_summarizes_success_failed_and_blocked_calls
test_inspect_tool_runtime_combines_registry_and_executor
test_builtin_registry_inspection_stays_offline_and_marks_network_tools_optional
```

必须继续保持：

```text
pytest tests/core/framework/tools -q
pytest -q
openspec validate tool-runtime-target-closure --strict
openspec validate --all --strict
```
