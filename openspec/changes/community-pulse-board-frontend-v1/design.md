## Context

NewsRoom 已经有 `business/boards/community_pulse` 运行时、`community_pulse-productized-board` artifact、`frontend/src/lib/community` 真实数据读取路径、`/community` 页面、topic 详情页和 Evidence Graph 对 CommunityTopic 的使用。PRD-06 需要的是把已有社区 topic 表达升级为信号流体验，同时不破坏现有兼容面。

## Goals / Non-Goals

**Goals:**

- 以 `/community` 为 Community Pulse Board 主入口，并让 `/news?source=community` 兼容跳转。
- 在 TypeScript 层补齐 PRD 对齐的 `CommunitySignal`、`CommunitySource`、`CommunitySentiment`、`DebateCluster` 和 signals list/detail payload。
- 从已有 board cards/topics 派生 signals、facets、clusters、metrics 和 details，保持后端 artifact 优先、本地 artifact 兜底、无数据时显式空态。
- 让页面满足前台阅读体验：快速看出热议、争议、来源、摘要、热度和跨板块关联。

**Non-Goals:**

- 不实现 HN/Reddit/GitHub 实时采集，不做情绪模型推理，不新增后端持久化 schema。
- 不做社交平台登录、评论回复、社区内容发布或后台采集监控。
- 不用运行时假数据填充业务内容。

## Decisions

- 继续复用 `CommunityTopic` 作为兼容模型，并新增 `CommunitySignal` 作为 PRD 主模型。Evidence Graph 和 topic 详情继续消费 `CommunityTopic`，新页面和新 BFF 消费 signals。
- 在 `frontend/src/lib/community` 增加 signals 派生层，而不是重写 server-data。这样能共享后端 artifact、本地 artifact、敏感字段清洗和现有测试夹具。
- Source 规范化使用 PRD 枚举：`hackernews`、`reddit`、`github`、`github_trending`、`x`、`blog`、`other`；旧 `github_discussion` 映射到 `github`，非社区或未知来源映射到 `other`。
- Sentiment 规范化使用 PRD 枚举：`positive`、`neutral`、`negative`、`mixed`、`controversial`；旧 `unknown` 在 signals API 中降级为 `neutral`。
- DebateCluster 只基于已有公开 artifact 字段生成：summary、代表评论、sentiment、controversy score、related refs。缺少真实论点时展示可解释空态，不编造支持/反对观点。
- Cursor 采用 base64url 编码的 offset 游标；旧 `page/pageSize` 仍可解析为同一个分页结果。
- `/news?source=community` 在页面层重定向到 `/community`，同时映射 `q/topic/sentiment/period/sort/limit/cursor`。

## Risks / Trade-offs

- 真实 artifact 当前可能包含官方来源而非纯社区来源 -> 映射到 `other`，页面用 notices 明确来源状态，不伪造成社区平台。
- 旧 topic 和新 signal 双模型会带来重复字段 -> 通过 adapter 派生和共享类型控制重复，不拆散现有 Evidence Graph。
- 当前 artifact 不一定有评论论点 -> DebateCluster 必须宁可为空也不生成假观点。
- PRD 文档当前存在历史乱码 -> 本次只更新状态和实现说明，不大面积重写整份 PRD，避免非必要文档 churn。
