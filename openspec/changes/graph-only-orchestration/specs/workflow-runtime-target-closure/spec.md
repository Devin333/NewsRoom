## REMOVED Requirements

### Requirement: Target-State Workflow Runtime Models

**Reason**：Graph runtime 已接管 step/node、edge、policy、validation、routing、pause 和 resume；保留 Workflow models/constructors 会维持第二套编排权威。

**Migration**：将仍有价值的确定性能力映射到 `harness-graph`、Harness control plane 或 domain-neutral owner，并删除 Workflow aggregate、constructor 和 runtime。

### Requirement: Workflow spec compatibility is preserved

**Reason**：Graph-only cutover 不支持旧 Workflow spec import compatibility。

**Migration**：调用方迁到明确 owner 的 Graph/activity contract；旧 import 在切换时成为 hard failure，且不提供 forwarding facade。
