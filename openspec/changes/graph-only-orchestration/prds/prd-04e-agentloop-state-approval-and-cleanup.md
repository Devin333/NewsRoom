# 叶子 PRD 04e：AgentLoop State、Approval 与 Legacy Cleanup

## 目标

完成 AgentLoop conversation/cursor/checkpoint/approval boundary，并删除旧 runner registry、Workflow smoke fixture 和只服务旧 runner 的测试。

## 任务来源与前置

- 根任务：`tasks.md` 6.3-6.7。
- 前置：04d、05a 的 Wait/approval application contract 可先以接口形式消费。
- 后续：06d 负责最终全局 legacy deletion proof。

## 允许修改

- conversation cursor、iteration checkpoint、AgentLoop diagnostics/retry/judge/tool policy/structured output tests。
- Graph Wait registration/approval candidate wiring、runner registry and only-legacy fixture deletion。

## 不允许修改

- AgentLoop 不能自己恢复、路由、批准或写 memory；cause durable commit 后由 Harness 自动 resume。
- 不删除仍被 Graph activity 使用的 artifact/raw storage primitives。

## 完成标准

1. cursor/checkpoint/message/transcript/receipt 使用 exact Graph checkpoint/node-instance identity。
2. approval candidate 进入 Harness Graph Wait registration；AgentLoop 不提供 resume executor。
3. diagnostics/retry/judge/tool policy 证明 outer gate/budget/authorization 仍由 Harness 决定。
4. `AgentLoopStepRunner`、旧 runner registry binding、Workflow smoke fixture 和 only-legacy tests 无 production caller。

## 验证与证据

```powershell
python -m pytest tests/framework/agent tests/framework/harness/subagents tests/interfaces/services -q
python -m pytest tests/framework/agent/loop tests/framework/agent/models -q
```

提交 AgentLoop state/approval cleanup evidence；跨模块删除要留 zero-reference scan。
