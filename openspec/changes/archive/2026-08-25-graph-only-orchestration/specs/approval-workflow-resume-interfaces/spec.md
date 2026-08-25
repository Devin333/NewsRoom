## REMOVED Requirements

### Requirement: Service resumes workflow from approval

**Reason**：旧 Workflow resume service 由 Harness Graph resume application service 取代。

**Migration**：调用方迁到 `approval-graph-resume-interfaces` 的 Graph run/wait/checkpoint contract。

### Requirement: API resumes workflow from approval

**Reason**：`resume-workflow` endpoint 暴露已退役的执行模型。

**Migration**：发布 Graph approval-decision major endpoint；durable cause commit 后由 Harness 自动 resume，并在调用方清单完成后删除旧 endpoint。

### Requirement: CLI resumes workflow from approval

**Reason**：`resume-workflow` command 暴露已退役的执行模型。

**Migration**：发布 Graph approval-decision command，并在调用方清单完成后删除旧 command。

### Requirement: MCP and SDK resume workflow from approval

**Reason**：MCP/SDK 旧 contract 依赖 Workflow identity。

**Migration**：发布 Graph approval-decision MCP tool 和 SDK method，并在 major cutover 后删除旧 surface。
