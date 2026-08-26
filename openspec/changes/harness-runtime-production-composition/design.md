## Context

NewsRoom 已有 `ExecutionEnvironmentRegistry`、Docker provider、execution profiles、capability admission、request/receipt contracts 与 fail-closed `ToolExecutor`。缺口是生产入口装配不一致：runner、Harness tool activity、batch executor 与 Research parser 可能各自构造执行对象，导致同一安全契约没有稳定进入真实调用链。

`prd.md` 将本 change 收敛为 production execution wiring。child supervision、durable runtime event、operator reconnect、approval 与跨系统 recovery 继续由既有 owner 或后续 change 负责。本设计不得通过无类型的 port bundle、fake/in-memory repository 或兼容层伪装这些能力已经生产装配。

## Goals / Non-Goals

**Goals:**

- 建立轻量、进程本地的 `RuntimeExecutionComposition`，稳定解析 composition、policy 与 provider/profile fingerprints。
- 为 API、worker、CLI、Harness、`AgentRunner`、batch executor 与 Research 提供同一 execution registry/profile policy；对象实例可以不同。
- 让 `sandboxed` / `external_process` activity 在 provider、profile、Graph identity、capability 或 termination contract 不完整时 typed fail closed。
- 让选定的 Research Marker/MinerU parser 通过受控 adapter 使用 Docker provider，并验证 cwd、roots、environment、timeout、cancellation 与 receipt。
- 维护 production caller inventory 与静态门禁，明确区分受控 adapter、provider 内部实现、测试/开发工具与后续迁移项。
- 用可复现证据区分 contract pass、environment blocked 与真实 provider qualification。

**Non-Goals:**

- 不新增跨进程 manifest/config drift 服务；每个进程只验证相同的本地配置解析结果与可选部署 fingerprint。
- 不让 `ChildAgentSupervisor` 接管全部真实 child dispatch，不实现 child lease/restart recovery。
- 不重定义 durable event/outbox/projection/cursor，也不建设 operator reconnect 平台。
- 不实现业务 side-effect intent/outbox/reconciliation 或跨系统 exactly-once。
- 不实现 secret handle provider、Docker 尚未声明的 network allowlist/CPU isolation，或外部治理签名链。
- 不迁移所有 parser/compiler/MCP sidecar；PDF compiler 与 outbound MCP 只进入 inventory/handoff，除非另有纵向切片。

## Decisions

### 1. Composition 只拥有 execution wiring

`interfaces/composition/runtime_execution.py` 是 production composition boundary。factory 创建 immutable local manifest identity、profile registry、execution environment registry、provider bindings 与 `ToolExecutor` factory。它不拥有 child repository、event outbox、projection checkpoint、operator service、approval service 或业务 side-effect repository。

composition manifest 是进程内的 versioned value object，用来计算确定性 fingerprints；它不是跨进程配置服务。API、worker、CLI 与 Research 从同一 factory/config 解析同一 identity，部署可通过 `NEWSROOM_RUNTIME_COMPOSITION_FINGERPRINT` 声明确切 expected fingerprint。值漂移时 startup/health/admission fail closed。

### 2. Provider requirement 按角色声明

profile catalog 可以声明目标 provider，而“某进程是否必须在 startup ready”由 `required_provider_ids` 显式决定。默认 API/worker/CLI composition 只完成 execution wiring compatibility，不因尚未执行 external activity 而要求 Docker；Research parser composition 将 `docker` 声明为 role-required。

这避免两种错误：把 catalog 中所有未来 provider 都当作全局 startup dependency，或在 Research 真正需要 Docker 时把 unavailable 伪装成 ready。

### 3. External activity admission 由 Harness policy 决定

`sandboxed` 与 `external_process` activity 必须提供精确 Graph identity、已登记 profile、argv、working roots、allowlisted environment、timeout 与 cancellation contract。registry 比较 provider capability；缺项返回稳定 denial code 和结构化 details。

`trusted_in_process` 只允许显式登记的确定性纯函数。caller、worker 或 LLM 不能把 sandboxed activity 降级为 trusted，也不能通过 `allow_unsafe` 或 host-process fallback 绕过 admission。

### 4. 所有 ToolExecutor 调用点使用 composition 注入

`AgentRunner`、Harness tool-result adapter、batch executor 与外部 subagent tool path 接收 composition 的 execution registry/profile resolver。API、worker 与 CLI 在 process composition root 创建一次 composition，再向 application services 传递同一实例。测试可以注入 fake provider，但必须使用同一 port 与 identity checks。

入口接线不意味着所有 profile 都生产启用。本切片只有 Research parser 的 external profile 被选择；其他入口证明 wiring 与 typed denial compatibility。

### 5. Research parser adapter 是业务边界

`ResearchParserExecutionAdapter` 把 parser command 转换成 `ExecutionRequest`，包括：

- exact Graph/attempt/activity identity；
- argv 与 canonical working directory；
- read-only input roots、受控 output roots 与 cache/config roots；
- allowlisted environment；
- network deny、timeout 与 cancellation semantics；
- `ExecutionReceipt` 到 parser observation/result 的映射。

Marker/MinerU business parser 不持有 provider，也不调用 host `subprocess.run`。Docker 不可用、capability 不支持或 termination 无法确认时返回 typed unavailable/indeterminate，不切回宿主执行。PDF compiler 未被本切片选中，只保留 adapter-required fail-closed 行为和 inventory handoff。

### 6. Caller inventory 是生产门禁

`caller-inventory.json` 与 source validation 只扫描 production runtime packages 中 Harness-managed process creation、raw external tool execution、child launch 与 executor construction。每项分类为 migrated、trusted exemption 或 blocked；豁免必须记录 owner、理由、非 Harness-managed proof、review date 与自动检查。

Docker provider 内部启动、tests 与 build/development tooling 不属于该门禁。新增未登记 production caller 使验证失败。

### 7. Existing authorities 不随 execution adapter 迁移

execution receipt 只证明受控进程的启动、约束、结果与 termination，不授权 Graph routing、quality verdict、approval、memory write、artifact publication 或业务 side effect。existing `runtime_event_sink` 可以接收 bounded observation，但本 change 不创建第二个 event authority。

## Risks / Trade-offs

- **Docker 在开发机不可用。** 通过 capability report 与 typed blocked evidence 保持诚实；没有 daemon 时不宣称真实 isolation qualification。
- **进程间配置可能漂移。** 当前用确定性 fingerprints 与可选 expected fingerprint 检查，不引入 distributed config service；更复杂部署协调留给后续 change。
- **PDF compiler/MCP 仍未迁移。** inventory 与 fail-closed default 防止静默 host fallback；真实业务纵向切片另立 change。
- **旧扩大版 artifacts 可能制造错误 completion pressure。** 本 change 以 `prd.md` 为范围控制文件，child/event/recovery requirements 已明确 handoff，不作为本 change 未完成债务或完成声明。

## Migration Plan

1. 固定 baseline、caller inventory、profile/provider catalog 与稳定 denial taxonomy。
2. 创建 process-local execution composition，并接通 API、worker、CLI、Harness、AgentRunner 与 batch executor。
3. 将 Research Marker/MinerU parser 注入 `ResearchParserExecutionAdapter`，移除 host-process fallback。
4. 增加 provider/profile/Graph identity/capability/manifest drift/termination/path/environment 的 negative tests。
5. 运行 focused tests、compile、smoke 与 strict OpenSpec validation，记录 Docker blocked 或真实 provider evidence。
6. 独立复核 authority boundary、inventory 与文档；按路径提交，不把后续 change 当成本 change completion。

## Scope Handoff

| Boundary | Owner / follow-up | This change |
| --- | --- | --- |
| child lifecycle, lease, heartbeat, restart | `harness-child-supervisor-integration` | reuse existing contracts only |
| durable event, projection cursor, reconnect | `durable-event-runtime`, `runtime-event-operator-wiring` | keep existing observation sink; no new authority |
| side-effect intent/outbox/reconciliation | `runtime-recovery-qualification` | execution receipt only |
| outbound MCP/sidecar vertical slice | future dedicated change | inventory/capability denial only |
| external release signatures | owning deployment changes | record as external; not a completion requirement here |

## Open Questions

- 目标部署何时提供可用 Docker daemon，以补充真实 isolation receipt；在此之前 qualification 保持 blocked。
- PDF compiler 或 outbound MCP 哪个业务场景应成为下一条 execution-adapter 纵向切片。
