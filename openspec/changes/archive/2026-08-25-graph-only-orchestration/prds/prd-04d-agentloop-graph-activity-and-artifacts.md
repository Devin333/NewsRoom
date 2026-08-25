# 叶子 PRD 04d：AgentLoop Graph Activity 与 Artifact Binding

## 目标

让 AgentLoop 只作为 Graph leaf activity 运行，并将 LLM request/response artifacts、activity receipt 和 node outcome 接入 Artifact owner 与 Graph node-output。

## 任务来源与前置

- 根任务：`tasks.md` 6.1-6.2。
- 前置：03a/03d、04a；依赖 physical dispatcher 和 artifact terminal contract。
- 后续：04e 处理 state/approval/cleanup。

## 允许修改

- `framework/agent/loop/**`、AgentLoop activity binding、artifact recorder/publisher adapter、Graph result receipt。
- AgentLoop Graph smoke、artifact integrity、committed-output and receipt tests。

## 不允许修改

- 不保留 `AgentLoopStepRunner` 作为 outer runner，不让 AgentLoop 发布 manifest 或决定 Graph route/gate。
- LLM 输出不能成为 committed node result，必须经过 Harness VERIFY。

## 完成标准

1. `AgentRunner` 只组装依赖，Graph activity 负责调用 bounded single-agent loop。
2. LLM request/response artifacts 由 Artifact owner 持久化并绑定 Graph/node/activity/attempt。
3. AgentLoop smoke 有 preflight、activity receipt、VERIFY evidence、manifest metrics、zero real network。

## 验证与证据

```powershell
python -m pytest tests/framework/agent tests/framework/harness/agent_loop tests/interfaces/services/test_agent_loop_smoke_service.py -q
python -m interfaces.cli.news dev run-test-agent-loop --topic "AI agents" --artifact-root .newsroom\smoke --json
```

提交 AgentLoop activity/artifact evidence；不要在本叶子处理 approval resume。
