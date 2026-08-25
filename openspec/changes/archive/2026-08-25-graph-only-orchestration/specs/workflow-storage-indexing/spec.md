## REMOVED Requirements

### Requirement: Workflow runs populate the artifact index

**Reason**：artifact index 的 live identity 改为 Graph run；旧 requirement 和 capability 名称不再代表受支持模型。

**Migration**：迁移到 `graph-storage-indexing`。旧 index record 仅由隔离 history-only tooling 分类并 quarantine，不转换为 live Graph index authority。

### Requirement: Workflow runs populate the event store

**Reason**：event store 的 live contract 改为 Graph events；旧 Workflow event projection 退役。

**Migration**：迁移到 `graph-storage-indexing`，不可转换旧事件进入只读 quarantine。
