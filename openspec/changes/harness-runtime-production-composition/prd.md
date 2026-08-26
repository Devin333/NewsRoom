# NewsRoom Harness Runtime Production Wiring PRD

## 1. 文档定位

| 项目 | 内容 |
| --- | --- |
| Change | `harness-runtime-production-composition` |
| 交付切片 | Production Execution Wiring |
| 优先级 | P0 / P1 / P2 |
| 状态 | Implementation complete；Docker live-isolation qualification remains environment-blocked |
| 产品原则 | LLM as worker, Harness as control plane |

本 PRD 只解决一个问题：**把已经存在的 `ExecutionEnvironment` 能力接入真实生产调用链**。它不是新的 Agent 平台，也不重新定义 child lifecycle、durable event 或 side-effect authority。

## 2. 实现基线

已有能力：

- `framework/execution_environment` 已有 execution profile、capability admission、request/receipt 和 provider registry。
- `infrastructure/execution_environment/docker.py` 已有 Docker provider、文件挂载、环境变量、网络限制、timeout 和 termination receipt。
- `framework/tool/runtime/executor.py` 已能在 sandboxed activity 缺少 provider 时 fail closed。
- `ChildAgentSupervisor`、runtime event projection 和 durable event runtime 已分别由现有 OpenSpec change 定义或实现。

本切片已经完成默认 execution wiring：

1. `AgentRunner`、Harness tool activity、batch executor 和 external subagent tool path 从 process composition 获取 execution registry/profile policy。
2. API、worker、CLI、Harness 与 Research 使用同一 composition/config/policy 解析结果，并保留各自的 process-local 对象实例。
3. Research Marker/MinerU parser 通过 `ResearchParserExecutionAdapter` 进入 Docker provider contract；业务 parser 不再拥有 host-process fallback。
4. provider、profile、Graph identity、capability、execution spec 和 composition drift 均有稳定 typed denial 与 readiness/admission diagnostics。
5. `GraphExecutionIdentity` 从 Research activity 经 compiler 与 parser cascade 原样传入执行 adapter；`ExecutionEnvironmentError` 不会被 parser fallback 或 abstract fallback 吞掉。
6. authoring host 的 Docker daemon 不可用，因此真实 isolation receipt 仍明确标记为 blocked；本地 contract/smoke 通过不替代目标部署资格。

Child lifecycle、durable event/operator reconnect、business side-effect recovery 与 outbound MCP/sidecar 纵向切片仍由第 10 节列出的后续 change 负责，不是本 change 的未完成实现。

## 3. 目标

### P0：生产 execution wiring

建立一个轻量的 composition factory，在 API、worker、CLI、Harness 和 Research 入口提供同一套 execution ports。每个进程可以拥有自己的对象实例，但必须使用同一份配置和 policy 解析结果；本阶段不引入跨进程 manifest 服务或配置漂移平台。只有本 PRD 选定的 Research parser 纵向切片会在生产 profile 中启用，其他入口先完成接线兼容性验证。

生产执行必须满足：

- `sandboxed`/`external_process` activity 没有 provider、profile、Graph identity 或 capability 时直接 typed denial；
- 不得因为 provider 未配置而回退到宿主进程；
- `ExecutionRequest` 明确绑定工作目录、mount、环境变量、argv、timeout、取消策略和 Graph identity；
- `ExecutionReceipt` 记录 provider、profile、capability、termination 和 checksum；
- 只有显式登记的纯函数可以使用 `trusted_in_process`。

### P1：完成一个真实业务纵向切片

先选择 Research PDF parser 作为第一个 production-managed external process：

- parser 通过 execution adapter 运行，而不是业务 service 直接持有进程句柄；
- 输入目录只读挂载，输出目录受控，默认禁止网络；
- provider 不可用或 capability 不支持时返回可诊断的 typed blocked；
- timeout 或 termination 无法确认时，不报告普通成功。

本阶段不要求把所有未来的 parser、compiler 或 MCP adapter 一次迁完，但必须建立可复用的 adapter 规范和 caller inventory。

### P2：验证和证据

补齐与本切片直接相关的测试和证据：

- `AgentRunner`、Harness tool activity、batch executor 和 Research parser 的 provider 注入；
- provider 缺失、profile 不匹配、Graph identity 错误和 unsupported capability 的 fail-closed；
- timeout、终止确认、文件根目录和环境变量边界；
- Research parser 的真实 provider contract；
- 生产 caller inventory，区分必须迁移、明确豁免、测试代码和 provider 内部实现；
- compile、focused tests、strict OpenSpec validation，以及 Docker 不可用时的明确 blocked 证据。

## 4. 用户场景

### 场景 A：Research 解析 PDF

Research worker 请求 parser。Harness 根据 Graph identity 和 activity policy 创建 `ExecutionRequest`，adapter 通过已注册的 Docker provider 启动 parser。parser 只能看到声明的输入/输出目录和允许的环境变量；完成后返回 `ExecutionReceipt` 和结构化 observation。

### 场景 B：部署没有 Docker

Research 请求 external parser，但目标环境没有可用 Docker daemon。admission 返回 `execution_environment_unavailable` 或等价 typed denial，run 进入受控 blocked/failed 状态，不改用宿主机 `subprocess.run`。

### 场景 C：AgentRunner 调用 sandboxed tool

AgentRunner 创建的 `ToolExecutor` 使用 composition 注入的 execution port。sandboxed tool 没有明确 profile 或 Graph identity 不匹配时，在执行前被拒绝；trusted pure function 仍可以按显式注册路径运行。

## 5. 范围

### 5.1 必须交付

- 新增明确的 production execution composition factory；名称和模块位置以现有 composition 结构为准，不预先引入完整 distributed manifest。
- 将 execution port 注入 `AgentRunner`、Harness tool activity、batch executor 以及 Research parser adapter。
- 为 Research PDF parser 建立受控 process adapter，统一传递 cwd、mount、env、timeout、cancellation 和 receipt；`PDF compiler` 先纳入 caller inventory，迁移作为后续 change，除非它被纳入本次纵向切片。
- 对 Harness-managed external activity 做生产 caller inventory 和静态检查。
- 保持 `trusted_in_process`、`sandboxed`、`external_process` 的显式 profile；禁止隐式安全降级。
- 保留现有 Graph、approval、artifact、retry、redaction 和 runtime event contract，不在本 change 重写它们。

### 5.2 明确不交付

- 不在本 change 内让 `ChildAgentSupervisor` 接管所有真实 child dispatch；这需要单独的业务纵向场景和 `harness-child-supervisor-integration` change。
- 不重新定义 `StoredEvent`、per-stream sequence、outbox、replay、projection checkpoint 或 durable event schema；这些属于 `durable-event-runtime`。
- 不把 runtime projection/API operator status 从可选服务一次升级成完整 app-server reconnect 平台。
- 不实现跨系统 exactly-once。业务 side effect 的 intent/outbox/reconciliation 另立 `runtime-recovery-qualification`，本切片只保证 execution process 的 receipt 和 termination 语义。
- 不新增跨进程 `RuntimeCompositionManifest`、tenant authorization 平台、secret handle provider 或外部治理签名链。
- 不要求把所有 `subprocess.run` 都删除；只扫描和迁移 Harness-managed external activity。Docker provider 自身的内部启动逻辑、tests、build/development tooling 不属于该扫描范围。

## 6. 设计原则

### 6.1 Composition 只做接线

composition factory 负责创建和注入 execution registry/provider，不负责 Graph routing、quality gate、approval decision、memory write 或 publication。Harness 仍是 control plane，LLM 和 worker 只返回 candidate/observation。

### 6.2 缺 provider 就阻断

缺 provider、缺 capability 或 provider 无法证明终止时，系统返回稳定的 typed denial。禁止用 `allow_unsafe`、调用方布尔值、日志提示或宿主机回退把 blocked 伪装成成功。

### 6.3 Execution receipt 与业务副作用分离

`ExecutionReceipt` 只证明某个受控进程如何被启动、限制和终止，不替代 artifact publication、memory write 或外部业务副作用的 receipt。这样可以复用现有 side-effect authority，而不把执行环境和业务事务耦合成一个大抽象。

### 6.4 Caller inventory 只管 Harness-managed process

扫描目标是生产业务/基础设施运行包中的 Harness-managed external activity。每个豁免必须记录 owner、理由、非 Harness-managed 证明、复核日期和静态检查/测试；新增未登记 caller 默认使质量门禁失败。

## 7. 目标运行路径

```text
Harness / AgentRunner / Research
              |
              v
       Execution Composition
              |
              +--> ToolExecutor --> ExecutionEnvironmentRegistry --> Docker provider
              |
              +--> Research process adapter ---------------------> Docker provider
              |
              +--> existing runtime_event_sink (observation only)
```

本图只描述 execution wiring。child supervisor、durable event store 和 approval service 继续由各自现有 owner 管理，不在本 change 建立第二套 authority。

## 8. 验收标准

| ID | 验收条件 | 证据 |
| --- | --- | --- |
| AC-01 | composition factory 能向 `AgentRunner`、Harness tool activity、batch executor 和 Research parser 注入 execution port；本次只有 Research parser 被生产启用 | composition/injection tests |
| AC-02 | sandboxed/external activity 缺 provider、profile、Graph identity 或 capability 时 fail closed | negative tests + typed denial |
| AC-03 | Research parser 通过受控 adapter 运行，不能从业务 service 直接启动 process | adapter integration test + scoped caller inventory |
| AC-04 | parser 的文件根目录、mount、环境变量、网络、timeout 和 termination receipt 可验证 | provider contract/adversarial tests |
| AC-05 | Docker 不可用时记录 blocked/skip，不宣称真实 sandbox qualification，也不执行宿主机 fallback | environment evidence |
| AC-06 | `trusted_in_process` 只对显式注册的纯函数开放，不能由调用方把 sandboxed activity 降级 | profile/admission tests |
| AC-07 | 现有 Graph routing、approval、artifact publication 和 side-effect authority 行为没有被 execution adapter 接管 | regression tests + boundary scan |
| AC-08 | focused tests、compile、`openspec validate harness-runtime-production-composition --strict` 和适用 smoke 有可追溯记录 | evidence entry |

## 9. 实施顺序

1. **Inventory**：锁定当前 commit，列出所有 Harness-managed external process 和 `ToolExecutor` 生产构造点，标记迁移/豁免。
2. **Composition**：实现最小 composition factory 和 execution provider 注入，不引入 distributed manifest。
3. **Injection**：接通 `AgentRunner`、Harness tool activity、batch executor 和 Research parser adapter。
4. **Vertical slice**：让 Research PDF parser 走真实 provider contract；Docker 不可用时只验证 typed blocked。
5. **Qualification**：补 timeout、termination、路径/环境边界、caller scan、compile、focused tests 和严格 OpenSpec 证据。

## 10. 依赖与后续 Change

| 项目 | 关系 | 说明 |
| --- | --- | --- |
| `harness-runtime-execution-safety` | 复用 | 复用其 execution model、provider、supervisor 和 projection contract；不重复定义底层契约。 |
| `source-policy-contract-convergence` | 已完成基线 | 不重新打开 Source policy；Research parser 只消费其允许的 application/service 边界。 |
| `durable-event-runtime` | 并行依赖 | 本 change 只使用现有 event sink/receipt，不重新定义 durable event；其外部发布资格不阻断本切片代码实现。 |
| `harness-child-supervisor-integration` | 后续 change | 选择真实 child 业务场景后，再接入 supervisor 的生产 dispatch、lease 和 restart。 |
| `runtime-event-operator-wiring` | 后续 change | 再把 canonical publisher、projection、API cursor reconnect 接入默认入口。 |
| `runtime-recovery-qualification` | 后续 change | 专门处理跨系统 side effect、intent/outbox/reconciliation、rollback 和发布资格。 |

## 11. 发布与回滚

以 capability gate 灰度启用 Research parser：

- provider 可用且 profile 完整时启用 adapter；
- provider 不可用时保持 typed blocked；
- 不允许在灰度期间对 sandboxed/external activity 使用宿主机 fallback；
- 回滚只切回已批准的 composition 配置，不删除 execution receipt、已有 event 或 artifact；
- 回滚验证只覆盖本切片的 execution receipt、termination 和业务结果一致性，不宣称完成整个 durable event 或 child recovery 发布资格。

## 12. Definition of Done

- 本 PRD 范围内的 composition、ToolExecutor 注入和 Research parser adapter 已进入真实调用链。
- Harness-managed external process 没有未登记的宿主机旁路；豁免有 owner、理由和复核日期。
- provider 缺失、capability 不支持、路径越界、环境变量越权、timeout 和 termination uncertainty 都有 fail-closed 测试。
- Docker 可用时有真实 provider contract 证据；Docker 不可用时证据明确为 blocked/skip，不把 contract test 写成生产资格。
- 现有 Harness control-plane authority、Graph routing、approval、artifact publication 和 side-effect authority 没有被新 composition 取代。
- 通过 focused tests、compile、strict OpenSpec validation 和适用 smoke，并更新本 change 的 evidence。
