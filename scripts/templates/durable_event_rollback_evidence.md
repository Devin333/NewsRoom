# Durable Event Runtime Rollback Drill Evidence

> Evidence status: TEMPLATE
>
> OpenSpec change: `durable-event-runtime`
>
> Task: `9.5`
>
> Local schema: `newsroom.durable-event-rollback-drill/v1`
>
> External schema: `newsroom.durable-event-rollback-external/v1`
>
> Qualification schema: `newsroom.durable-event-rollback-qualification/v1`

本模板将本地不变量检查与发布级 rollback qualification 明确分开。本地 SQLite
演练永远是 `INCOMPLETE`，不能通过修改 JSON 状态或重算 checksum 晋升为发布证据。
只有真实 staging/deployment 证据通过严格结构校验并由受信 Ed25519 key 签名后，
工具才会生成 `PASSED` qualification bundle。

## 1. 安全前置条件

- 使用隔离且为空的 drill workspace，禁止把 production database 作为脚本输入。
- cutover 后不得恢复 unpersisted Bus/Recorder writer。
- rollback 只允许切换 compatible reader/dispatcher/application binary；canonical
  events、stream counter、delivery、inbox、checkpoint、DLQ 和 expand schema 必须保留。
- schema、security、identity、integrity 和 quarantine gates 在所有阶段保持开启。
- PostgreSQL 使用隔离 staging clone 和真实 transaction；external effect 使用独立、
  可审计的 staging provider/database 或真实 provider idempotency boundary。
- candidate 与 rollback 必须使用不同且不可变的 commit/image digest。人工标签不合格。
- external attestation 与 release qualification 必须由两个独立 Ed25519 key 承担，
  public-key fingerprint 必须不同；private key 由各自部署/发布系统保管，不进入仓库
  或 evidence bundle。Windows key file 使用 protected owner-only DACL，POSIX 使用 `0600`。

## 2. 本地不变量演练

```powershell
$workspace = "artifacts/rollback-drills/<drill-id>/local"
.\.venv\Scripts\python.exe -m scripts.durable_event_rollback_drill run `
  --workspace $workspace `
  --drill-id "<drill-id>" `
  --candidate-release "<candidate-commit-or-image-digest>" `
  --rollback-release "<rollback-commit-or-image-digest>"

# run 预期退出码为 2，状态为 INCOMPLETE。
.\.venv\Scripts\python.exe -m scripts.durable_event_rollback_drill verify `
  --evidence "$workspace/rollback-evidence.json" `
  --allow-incomplete-local
```

如显式传入 `--evidence`，目标必须是 `$workspace` 根目录内尚不存在的 `.json`
文件；工具拒绝 workspace 外路径、内部 database/artifact 别名和既有输出。

本地 bundle 自动证明：

| Phase | 本地证明范围 |
| --- | --- |
| `pre_cutover_shadow_rollback` | synthetic legacy source 不变、backfill/shadow 可复验且不 dispatch |
| `post_cutover_canonical_writer` | event/outbox 在 dispatch 前 durable，external effect 尚未执行 |
| `dispatcher_runtime_recomposition` | 同版本 runtime 重组后 retry/checkpoint 恢复，稳定 idempotency key 只产生一个 effect |
| `rollback_gates_and_sequence_continuity` | schema/security/identity 拒绝不分配 sequence，下一合法事件连续 |
| `same_binary_projection_rebuild` | 同版本 projection 确定性、redaction、high-watermark 和无 store 回写 |

这些 phase 不证明真实 binary/image switch、跨版本 projection compatibility、真实
PostgreSQL continuity、部署流量冻结或外部 provider 幂等。因此严格 `verify`（不带
`--allow-incomplete-local`）必须失败。

## 3. 外部 evidence bundle

部署流程必须生成 `external-evidence.json`，schema 为
`newsroom.durable-event-rollback-external/v1`，并包含以下固定顶层字段：

```json
{
  "schema": "newsroom.durable-event-rollback-external/v1",
  "status": "passed",
  "drill_id": "<same-drill-id>",
  "drill_completed_at": "<UTC timestamp before approval>",
  "candidate_release_digest": "<40/64 hex or sha256:...>",
  "rollback_release_digest": "<different immutable digest>",
  "postgresql": {},
  "external_effect": {},
  "orchestrator": {},
  "approval": {},
  "external_gates": {},
  "artifacts": [],
  "evidence_checksum": "sha256:..."
}
```

`artifacts` 必须且只能包含以下角色，每项记录相对 path、size 和 SHA-256：

```text
orchestrator_run
traffic_control
postgres_before_snapshot
postgres_after_snapshot
external_effect_audit
candidate_projection
rollback_projection
schema_security_negative_tests
approval_record
```

所有外部引用都必须绑定到上述 manifest role，而不是未入 bundle 的任意 URL：

```text
postgresql.before_snapshot_ref                  -> artifact://rollback/postgres_before_snapshot
postgresql.after_snapshot_ref                   -> artifact://rollback/postgres_after_snapshot
external_effect.idempotency_contract_ref       -> artifact://rollback/external_effect_audit
orchestrator.run_ref                           -> artifact://rollback/orchestrator_run#run
orchestrator.traffic_freeze_ref                 -> artifact://rollback/traffic_control#freeze
orchestrator.dispatcher_pause_ref               -> artifact://rollback/traffic_control#dispatcher
orchestrator.candidate_deployment_ref           -> artifact://rollback/orchestrator_run#candidate
orchestrator.rollback_deployment_ref            -> artifact://rollback/orchestrator_run#rollback
approval.record_ref                             -> artifact://rollback/approval_record
```

manifest SHA 只证明文件未变化，不证明文件支持顶层断言。除 `approval_record` 外，每个
portable artifact 都是固定 schema 的 normalized JSON，并包含原生 PostgreSQL snapshot、
orchestrator log、traffic-control log 或 provider audit 的非 bundle `source_ref` 与
`source_checksum`。external attester 对 normalized 内容和原生来源哈希共同签名；工具不尝试
泛化解析不同供应商的原生日志。

PostgreSQL before/after artifact 必须逐字段绑定隔离数据库、server/migration version、
stream、accepted prefix checksum、before/rejection/next/after watermark、零重复 sequence、
零 checksum failure，以及 delivery/inbox/checkpoint/DLQ 的非零 before/after count 与
checksum。当前无 retention/delete 阶段要求 `preserved_event_count == watermark_before > 0`，
四类历史的 count 和 checksum 均不得变化，并发 writer continuity 与 crash recovery 必须通过。

External-effect evidence 必须记录 provider kind、idempotency contract ref、稳定 key
hash、至少两次 invocation、恰好一次 applied effect、前后结果 checksum 相同和审计状态；
`external_effect_audit` normalized artifact 必须与这些字段逐项一致。

Orchestrator evidence 必须记录 run、traffic freeze、dispatcher pause、candidate deploy、
rollback deploy 引用，证明真实 binary switch、切换时 claim 已冻结且没有双 dispatcher。
candidate/rollback deployment id 与 release digest 必须不同并绑定到 `orchestrator_run`；
`traffic_control` 必须证明 traffic frozen、claim paused 和零并发 dispatcher。

candidate/rollback projection normalized artifact 必须绑定各自 release digest、同一 stream、
同一 high watermark、event count、ordered-sequence checksum 和 projection checksum，且原生
projection 的 source checksum 与声明 checksum 一致。negative-test artifact 必须覆盖
`unknown_schema`、`forbidden_payload`、`identity_collision`、`record_checksum_tamper`，全部为
rejected，并证明 watermark 未推进。

Approval evidence 必须由不同的 operator/approver 提供 UTC 时间、`approved` decision
和可审计 record ref。`approved_at` 不得早于 `drill_completed_at`；为容忍部署节点时钟偏差，
时间最多可领先 verifier 时钟 5 分钟；
`approval_record` artifact 必须逐字段绑定 drill id、两个 release digest、operator、approver、
approval time 和 decision。

## 4. 生成签名 qualification bundle

首次接入发布系统时分别生成 external attestation 与 release qualification keypair；
生产中 private key 应由两个独立 KMS/secret manager authority 管理：

```powershell
.\.venv\Scripts\python.exe -m scripts.durable_event_rollback_drill keygen `
  --private-key <external-attester-private-key-path> `
  --public-key <trusted-external-public-key-path>

.\.venv\Scripts\python.exe -m scripts.durable_event_rollback_drill keygen `
  --private-key <qualifier-private-key-path> `
  --public-key <trusted-qualification-public-key-path>
```

先由独立部署证据 authority 验证结构、artifact 和时间并签署 external evidence。输出必须
位于 external bundle 内且是尚不存在的新文件：

```powershell
.\.venv\Scripts\python.exe -m scripts.durable_event_rollback_drill attest-external `
  --evidence <external>/external-evidence.json `
  --private-key <external-attester-private-key-path> `
  --output <external>/external-evidence.signed.json
```

再由 release qualification authority 生成 bundle：

```powershell
.\.venv\Scripts\python.exe -m scripts.durable_event_rollback_drill qualify `
  --local-evidence <local>/rollback-evidence.json `
  --external-evidence <external>/external-evidence.signed.json `
  --private-key <qualifier-private-key-path> `
  --trusted-external-public-key <trusted-external-public-key-path> `
  --output <bundle>/qualification.json
```

严格验证：

```powershell
.\.venv\Scripts\python.exe -m scripts.durable_event_rollback_drill verify `
  --evidence <bundle>/qualification.json `
  --trusted-public-key <trusted-qualification-public-key-path> `
  --trusted-external-public-key <trusted-external-public-key-path>
```

`qualify` 会把 local/external evidence 及所有 artifacts 复制到可移植 bundle，逐项校验
内容和结构，再计算 checksum 并签名。`verify` 会重新验证签名、精确字段/phase/artifact
集合、所有 checksum、release digest、PostgreSQL/effect/orchestrator/approval 不变量，以及
顶层摘要与引用 external bundle 完全一致。qualification 还绑定整个 signed-external 文件
的 SHA-256，并验证 `drill completion <= approval <= external attestation <= qualification`，
因此不能替换同一 logical evidence 的另一份 attestation。qualification 输出目录必须尚不
存在；temporary bundle 在完整 strict verify 后才原子发布，复制或校验中断时会被清理，
修复输入后可用同一路径重试，既有 bundle 不会被覆盖。

## 5. 验收判定

以下任意一项缺失时，任务 9.5 仍为 `INCOMPLETE` 或 `FAILED`：

- accepted event 数量、identity、bytes、checksum 或 sequence 前后不一致；
- sequence counter 被重置/复用，或 rejected event 分配了 sequence；
- pending delivery、inbox、checkpoint 或 DLQ history 被清除；
- external effect 应用超过一次或改变 idempotency key；
- schema/security/identity/integrity negative fixture 被接受；
- candidate/rollback projection 无法跨实际 binary 按 high watermark 重建；
- candidate/rollback 不是不同的不可变 digest；
- 缺 PostgreSQL、orchestrator/traffic control、external effect 或职责分离审批证据；
- 缺任何 required artifact、artifact 被修改、签名不可信或 bundle 摘要不一致。

本地测试、同进程对象重建、操作员输入字符串、普通可重算 checksum 或文档勾选都不能
替代上述外部证据。
