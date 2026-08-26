## Context

本 change 处理的是生产装配缺口，不是重新设计 Harness 控制面。当前代码已经有 `ExecutionEnvironmentRegistry`、Docker provider、`ChildAgentSupervisor`、`RuntimeEventProjection` 和 `CanonicalRuntimeEventPublisher`，但默认入口大多只传递可选 sink/provider；部分 Research parser/PDF compiler 仍直接调用 `subprocess.run`。因此需要在 composition boundary 统一绑定这些已有端口，并让失败状态可观测、可恢复、可审计。这里的“统一”指各进程从同一份 versioned manifest 解析相同的 configuration/policy/provider fingerprint，不要求跨进程共享 Python 对象。

约束如下：

- Harness 是唯一 control plane；LLM、worker、tool 和 child 只能提供 candidate/observation。
- Graph identity、TaskPlan、deterministic VERIFY、approval、side-effect authority 和 artifact owner 继续沿用现有契约。
- `durable-event-runtime` 的外部发布资格尚未完全具备；本 change 可以接入其 port，但不能声称替它完成外部治理。
- Docker daemon 可能在开发机不可用；没有真实 provider 时必须保留 fail-closed/blocked 语义。
- 生产 composition 不能隐式创建 fake/in-memory store 来满足依赖。

## Goals / Non-Goals

**Goals:**

- 建立一个明确的 `RuntimeExecutionComposition`，对所有进程入口提供 fingerprint 一致的 execution, durable receipt, child lease, event/outbox、projection checkpoint 和 operator authorization ports。
- 将外部工具和直接子进程纳入 `ExecutionEnvironment`，并在 admission 时校验 profile、capability、Graph identity 和 cancellation contract。
- 让 `ChildAgentSupervisor` 成为真实 child dispatch 的唯一 lifecycle owner，并提供 restart-safe lease/receipt recovery。
- 让 canonical runtime event 先进入 durable event runtime，再由 projection/API 提供 bounded read/reconnect。
- 通过集成、对抗性测试和 capability matrix 证明“真实支持什么”和“明确不支持什么”。

**Non-Goals:**

- 不修改 Graph scheduler、TaskPlan planner、deterministic gate 的控制权。
- 不在本 change 内完成 durable event 外部签名链或 Graph production cutover。
- 不把 Docker provider 扩展成超出其能力声明的 network allowlist、secret handle 或 CPU isolation 实现；不支持的能力继续拒绝。
- 不提供兼容性的宿主进程 fallback 来绕过隔离。

## Decisions

### 1. 由单一 composition root 装配所有 runtime ports

每个进程的 `RuntimeExecutionComposition` 从 immutable `RuntimeCompositionManifest` 解析 `composition_id`、version、checksum、policy fingerprint 和 provider/config identity。它负责创建/接收 `ExecutionEnvironmentRegistry`、`ToolExecutor` factory、durable execution intent/receipt repository、side-effect idempotency/reconciliation port、durable child lease/receipt repository、`ChildAgentSupervisor`、canonical event store/outbox publisher、projection checkpoint store、operator authorizer 和 operator read service。API、worker、CLI、Harness 和 Research 入口只接收这组已绑定的 ports；生产端口不得隐式退回 in-memory。

选择原因：当前各入口的可选注入导致“契约存在但默认不生效”。versioned manifest 可以让多个进程在不共享对象的前提下验证 provider/config identity、Graph policy、event schema 和 store lifecycle 一致；checksum 漂移必须在 startup/health/admission 阶段拒绝。

备选方案：让每个调用方自行 new provider。该方案短期改动少，但会形成多个 registry、多个 event authority 和不同的 fail-closed 行为，拒绝采用。

### 2. 按 activity profile 做 admission，而不是按调用方布尔值降级

所有 activity 在进入执行前解析为 `trusted_in_process`、`sandboxed` 或 `external_process` profile。`sandboxed`/`external_process` 必须匹配已注册 provider、完整 capability profile 和精确 Graph identity；缺失时返回稳定 typed denial。

选择原因：安全边界必须由 Harness 和 immutable policy 决定，不能由 worker 或接口层传 `allow_unsafe=true`。纯函数仍可保留 trusted profile，但必须显式注册。

备选方案：缺 provider 时自动改为 in-process。该方案会把“部署没配好”变成隐蔽的安全降级，拒绝采用。

### 3. direct subprocess 通过受控 adapter 收敛

对 parser、compiler、MCP sidecar 等直接 `subprocess.run` caller 建立明确的 activity adapter，将命令、cwd、mount、env、timeout 和 cancellation 转换为 `ExecutionRequest`。业务 service 不直接持有 provider，也不自行解释 receipt。

选择原因：既能保留业务接口，又能消除绕过 ToolExecutor 的旁路。adapter 只负责输入/输出映射，授权和 routing 仍由 Harness 负责。

production caller inventory 只扫描业务和基础设施运行包，不包含 tests/dev/build tooling。豁免项必须进入 versioned allowlist，记录 owner、理由、非 Harness-managed 证明、到期日和复核条件；新增未登记 caller 使 CI 失败。

备选方案：只在日志中记录 direct subprocess。该方案无法限制文件/网络/环境/子进程，不能满足 P0。

### 4. 明确 MCP 入站与出站边界

入站 MCP server 只执行鉴权、schema 校验和 application service routing，不能直接访问 execution provider/store。只有 `ToolRuntime` 出站 MCP adapter 和本地 MCP sidecar 属于 external activity，必须通过 execution admission，并显式声明 network、credential handle、timeout 和 cancellation capability。

选择原因：两类 MCP 的信任方向和职责相反；合并会导致 interface 层直接拥有 executor 或把远端 tool invocation 当成本地入站请求。

### 5. `ChildAgentSupervisor` 取代并行 child owner

把现有 `SubAgentRuntime` 收敛为 supervisor 使用的执行 adapter，而不是保留两套生命周期语义。每次 spawn 先生成 parent/child/lease/attempt identity，再用 admitted `ExecutionRequest` 启动 child；execution receipt 必须绑定 lease/attempt，heartbeat、cancel、close 和 recovery 都由 supervisor 写入 durable child repository 和 canonical event。

选择原因：并行 owner 会导致父进程重启、取消和重复副作用无法判定。保留 adapter 可以复用已有 worker，但不保留第二套 lifecycle authority。

备选方案：让 `SubAgentRuntime` 和 supervisor 互相同步。该方案存在双写、竞态和不一致 terminal state，拒绝采用。

### 6. canonical event publisher 是事实权威，projection 只是读模型

运行时事实先由 canonical publisher 写入 durable event runtime，使用稳定 event id、scope、checksum 和 redaction metadata。durable store 在 append 时原子分配 per-run monotonic sequence，并强制 `(run_id, sequence)` 唯一；相同 event id/checksum 幂等返回原 receipt，不同 checksum 或并发 sequence 冲突返回 typed conflict。projection 通过幂等 apply/rebuild 和持久化 checkpoint 生成 operator view；cursor 编码 schema version、run/Graph scope、sequence 和 authorization fingerprint，API 只能在重新鉴权后读取。

选择原因：当前 projection 已有 in-memory 默认，需要把它放在 durable event 之后，避免重启丢事实和出现第二事件源。cursor 以 durable sequence 为准，重连不依赖进程内状态。

备选方案：让各模块直接写 projection。该方案无法可靠重放，也会把 operator read model 变成隐式写入 authority，拒绝采用。

### 7. 外部副作用使用 recoverable intent/outbox 状态机

每个授权 attempt 在 dispatch 前原子提交 immutable intent、idempotency key、authority checksum 和 `PREPARED` 状态。外部 provider 必须支持同 key 的幂等查询/执行或 reconciliation；如果无法确认外部结果，Harness 进入 `INDETERMINATE`，绝不盲目重发。execution/side-effect receipt 是外部结果的 authoritative record；receipt commit 同时写入 terminal-event outbox，publisher 可重试 outbox 而不重复外部调用。状态至少包含 `PREPARED -> DISPATCHED -> RECEIPT_COMMITTED -> EVENT_PUBLISHED`，每个 crash point 只有一个允许的恢复分支。

选择原因：外部系统无法参与本地数据库事务，不能声称真正的跨系统 exactly-once。intent + provider idempotency/reconciliation + authoritative receipt + transactional outbox 能把不可避免的不确定性显式化。

备选方案：外部调用后直接写 event。它会在“调用成功、receipt/event 未写入”时重复副作用，拒绝采用。

### 8. 恢复遵循“receipt-first、evidence-first”

重启恢复先读取 intent、execution/side-effect receipt、child lease/transcript/output ref、outbox 和 event history，再决定 resume、reconcile、retry、quarantine 或 manual repair。已有 authoritative receipt 时只补发 outbox/event；只有 `PREPARED` 且确认从未 dispatch 才能执行。`DISPATCHED` 但无 receipt 时必须 reconciliation 或进入 `INDETERMINATE`，不得猜测成功，也不得无条件重跑。

child transcript/output 使用受控 artifact reference、immutable checksum、parent/child access scope 和 retention owner；缺少 production encryption/locking/retention binding 时 cross-process recovery 保持 qualification-blocked。

### 9. approval command 与事件投影闭环

只有 Harness approval application service 可在 deterministic authorizer 验证 principal、approval scope、Graph Wait identity 和幂等 key 后提交决定。requested/decided/rejected/expired 都写 authoritative approval receipt 和 terminal-event outbox；operator projection 保持只读，重启后从 receipt/event 恢复。

选择原因：只投影 approval event 而不约束决定写入，会让 event 看似统一但控制权仍分散。

选择原因：进程崩溃发生在外部副作用前后都可能留下不确定状态，只有 durable evidence 能区分。该策略与现有 Harness replay/side-effect authority 一致。

备选方案：按最后内存状态重跑。它在 crash 后不可靠，且会重复发布、写 memory 或调用外部 source。

## Risks / Trade-offs

- [Docker daemon 不可用] -> composition 在 startup/admission 返回 typed blocked capability；测试明确 skip/blocker，生产资格不使用 fake provider 替代。
- [旧入口仍创建 bypass executor] -> 做全仓 caller inventory 和静态扫描；未豁免 direct subprocess/ToolExecutor/child construction 作为验收失败。
- [durable event schema 与现有 EventRuntime 不兼容] -> 通过 `CanonicalRuntimeEventPublisher` adapter 做 checksum/version 校验；兼容性不明时停止发布而非丢 event。
- [child cancel 竞态] -> 把未确认终止标为 `INDETERMINATE`/`LOST`，要求 receipt/heartbeat 证据和受控人工修复，禁止报告普通成功。
- [projection 重复投递] -> 以 event id + sequence + payload checksum 做幂等；冲突事件进入 quarantine，不覆盖原事实。
- [migration 期间多套 composition 并存] -> shadow mode 只比较 admission/event 计划，不执行 external side effect；灰度旧路径只允许 inventory 中已验证的 pure `trusted_in_process` activity，sandboxed/external activity 没有真实 provider 时返回 typed blocked。
- [测试只覆盖 fake/in-memory] -> 将测试分成 contract、provider integration、restart/recovery、API reconnect 四层；任何声称生产就绪的能力必须有真实部署证据。

## Migration Plan

1. 建立 versioned caller inventory、activity profile registry、manifest 和 composition interface；shadow mode 只记录/比较 admission 与 event 计划，不启动 external activity 或副作用。
2. 接入真实 execution provider 与 durable event publisher；对 sandboxed/external activity 开启 fail-closed admission。
3. 将 Harness/Research child dispatch 切换到 supervisor，启用 lease/heartbeat/recovery，并保留可回滚的 feature gate。
4. 启用 projection/API cursor reconnect，验证重启、重复事件和跨 run 隔离。
5. 完成 capability matrix、部署观察、回滚演练和 OpenSpec evidence 后，才允许扩大到默认 production profile。

回滚必须回到已批准的旧 composition，并保留已经提交的 receipt/event。禁止删除 durable history、清空 projection 或通过重复执行副作用修复不确定状态。

## Open Questions

- `durable-event-runtime` 的最终 production publisher/store binding 由哪个部署 owner 提供，何时取得独立签名？
- Windows/Linux 的默认 provider 是否都采用 Docker，还是需要另一个同样满足 capability contract 的 provider？
- `SourceRuntimeComposition` 中哪些 Research source activity 需要标记为 external process，哪些可留在 trusted profile？
- operator reconnect 是否通过现有 REST cursor API 扩展，还是由 app-server/MCP streaming adapter 提供统一 transport？
- child transcript/output receipt 的生产存储 retention、加密和跨进程锁由哪个基础设施 owner 负责？
