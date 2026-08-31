# PRD：Research Paper Intelligence Backend v1

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 产品名称 | Research Paper Intelligence Backend |
| 版本 | v1 |
| 所属产品 | Agora Hub |
| 负责模块 | `backend/research` |
| 文档落点 | `openspec/changes/research-paper-catalog-backend-v1/prd.md` |
| 业务参考 | Papers with Code 的 paper/task/method/dataset/benchmark 组织方式 |
| 前端范围 | 本变更不修改 `frontend` |
| 默认存储 | durable filesystem artifact/catalog store |
| 调用模式 | 有界同步 application call，返回 durable `run_id` |
| 外部依赖边界 | 不依赖 Papers with Code 实时数据库或 API，不执行第三方代码 |

本文是 `research-paper-catalog-backend-v1` 的产品需求文档，约束后续领域模型、application service、ports、infrastructure adapter、HTTP API、CLI、artifact 和测试的实现边界。它描述的是后端业务闭环，不是前端页面设计，也不替换当前 framework/Harness 的基础契约。

## 2. 产品定位

Research Paper Intelligence Backend 将来自 arXiv、OpenReview、DOI/Crossref、publisher、local artifact 和 GitHub 的论文输入，转换为可追溯的结构化论文文档、证据包以及 Paper-with-Code Catalog。

Catalog 借鉴 Papers with Code 的信息组织方式，把 `paper` 连接到 `task`、`method`、`dataset`、`benchmark`、`metric`、`score` 和 `code_repository`。它只把 Papers with Code 作为产品信息架构参考，不抓取或复制其实时数据库，不把其站点或 API 当作事实来源。Agora Hub 的事实来源必须能回溯到自身保存的 `ResearchSourceSnapshot`、document locator、artifact checksum 和 provenance。

业务结果的最低保证不是“模型生成了一段论文摘要”，而是：

1. 输入来源和论文身份可识别、可合并、可审计。
2. 解析结果能够定位回原始来源中的章节、页码、图表、公式或文本范围。
3. Catalog 关系、benchmark score 和 SOTA claim 有明确状态；候选内容不会伪装成事实。
4. 失败、降级、冲突、重试和隔离都能通过 durable run/event trace 解释。
5. API、CLI 和后续前端使用同一 application contract，不绕过业务编排层。

参考信息架构：[Papers with Code 论文页面示例](https://paperswithcode.com/paper/measuring-coding-challenge-competence-with)。相关论文入口当前可能跳转到 Hugging Face：[Hugging Face Papers](https://huggingface.co/papers/trending)。这些链接只用于说明交互和信息组织，不构成本系统的运行时依赖。

## 3. 产品目标

### 3.1 v1 目标

- 支持 `arxiv`、`openreview`、`doi`/`crossref`、`publisher`、`local`、`github` 等输入类型。
- 对同一论文完成跨来源 identity resolution，保留版本、快照和冲突，而不是静默覆盖。
- 通过统一的 `ParsePaperUseCase` 复用现有解析能力，得到结构化 `ResearchDocument`、chunk manifest、evidence pack、parser attempts 和 quality report。
- 建立 typed Paper-with-Code Catalog，使 paper 与任务、方法、数据集、benchmark、metric、score 和代码仓库成为可查询的关系。
- 从论文表格、正文、caption、代码链接和来源元数据抽取 benchmark/score/SOTA 候选，并用确定性规则验证可比较性。
- 补充 GitHub 仓库的 README、安装、license、examples、training、inference、checkpoint 等可复现性观察，但不执行仓库代码或自动推断“可运行”。
- 为 API、CLI、artifact 和后续 RAG/阅读/问答能力提供稳定、带 provenance 的 JSON contract。
- 在 tenant/user scope 内提供幂等 ingest、故障诊断、重试、降级、历史快照和 durable event trace。

### 3.2 成功指标

| 指标 | 验收目标 |
| --- | --- |
| 论文身份归并 | 同一论文的 arXiv、DOI、publisher 输入归并为同一 canonical identity；不同版本保留独立 snapshot |
| 受限来源行为 | 全文被拒绝或不可访问时只返回 `metadata_only`，不创建虚假的 `parsed` |
| 解析可追溯性 | 每次 parser attempt、fallback、质量分数、失败原因和 source locator 均可读取 |
| 结构保真 | 复杂 LaTeX/PDF fixture 保留 sections、figures、tables、equations、references 和 chunks |
| 幂等性 | 相同 actor scope、canonical identity、source checksum 重复 ingest 不产生重复实体、关系或 artifact |
| Catalog 可信度 | 无 evidence 的关系/score/SOTA claim 不得 `verified`；candidate/conflicting 不进入 leaderboard |
| 协议可比性 | split、unit、direction、dataset version 或 evaluation protocol 不兼容的 score 不横向比较 |
| 隔离 | 不同 tenant/user 不能读取或修改对方的 paper、source、document、catalog、artifact 和 event |
| 接口边界 | API/CLI 只调用 application service，不直接依赖 parser、repository 或具体 infrastructure adapter |
| 变更范围 | `frontend` 无文件变更，`backend/research` 不依赖 legacy `backend/boards/paper_radar` |

## 4. 用户与权限范围

### 4.1 用户角色

| 角色 | 主要任务 | 关键权限 |
| --- | --- | --- |
| 研究人员 | 提交和阅读论文、查看证据、代码观察和 benchmark 候选 | 在自己的 actor scope 内 parse、查询、refresh、导出 |
| Research Engineer | 调查解析质量、修正 source、检查关系和协议兼容性 | 访问被授权 scope，查看 parser attempts、diagnostics 和 candidate |
| 运营人员 | 批量 ingest、重试失败、监控 artifact 和 Catalog | 仅在明确授权的 tenant/project scope 内执行批处理 |
| 集成客户端 | 通过 API/SDK 消费结构化论文和 Catalog | 只能使用公开的 JSON contract，不接触 prompt、secret 或未授权原文 |

### 4.2 Actor scope

所有 application request 都必须解析出不可伪造的 `actor_scope`。v1 的持久化隔离维度固定为 `tenant_id`、`user_id` 和派生的 `memory_namespace`；`project_id`、`workspace_id` 与 service-account 权限属于后续授权层扩展，不在本变更中作为可写入的 Catalog key。请求体中的 scope 只能作为校验输入，不能覆盖认证上下文。

scope 是 identity merge、幂等键、artifact path、查询过滤和 event 写入的一部分。跨 tenant 的相同 DOI 或 URL 只表示外部事实相同，不表示数据可以合并或互读。

## 5. 核心业务场景

### 场景 A：从 arXiv 解析论文

研究人员提交 arXiv URL 或 id。系统解析 arXiv metadata，尝试获取 LaTeX source 或 PDF，创建 source snapshot，解析文档和 chunks，抽取 evidence 与 Catalog candidate，返回 `run_id`、`paper_id`、状态、quality report 和 artifact refs。若 source 下载受限，仍可返回结构化 metadata，但状态必须为 `metadata_only` 或 `degraded`。

### 场景 B：用 DOI/出版社来源补充同一论文

用户提交 DOI 或 publisher URL。系统首先解析 DOI/Crossref metadata，再按照 canonical URL 和可解释的标题/作者/年份指纹与现有 identity 匹配。冲突字段保留来源和诊断，不能覆盖已有值。若 publisher 全文受到 robots、登录、大小或超时策略限制，则只新增 source snapshot 和 metadata observation。

### 场景 C：复杂论文的结构化阅读

用户提交 local PDF 或 LaTeX archive。系统使用对应 parser，持久化 sections、figures、tables、equations、references、source locator 和 chunk manifest。PDF cascade 必须保留所有尝试，即使最终使用降级后端。质量不足时返回 `degraded`，不能以空 document 标记 `parsed`。

### 场景 D：从表格发现 benchmark 结果

系统从正文、表格、caption 和脚注生成 score candidate。每个 candidate 记录 paper、dataset、benchmark、metric、split、unit、direction、evaluation protocol、数值和 evidence refs。确定性 gate 检查实体完整性和协议兼容性；缺字段或有冲突的 candidate 不进入 verified leaderboard。

### 场景 E：检查代码仓库可复现性信号

论文包含一个或多个 GitHub URL。系统获取仓库 metadata 和允许范围内的 README/文件清单，记录 branch、commit/release、安装说明、依赖文件、examples、training、inference、checkpoint、license 等 observation。系统不执行第三方代码、不自动安装依赖，也不把 README 中的承诺直接当作“复现成功”。

### 场景 F：重复 ingest 与 refresh

相同来源重复提交时，系统依据 actor scope、canonical identity、source key 和 checksum 幂等返回既有结果。`refresh` 是真实的重新获取、重新解析和重新构建 Catalog candidate 的 application operation；它不能只复制一条“成功”记录，也不能删除历史 snapshot 和旧 leaderboard observation。

## 6. 范围

### 6.1 必须交付

- Source resolver、source snapshot、content checksum 和 provenance。
- `ResearchPaperIdentity`、identity resolution/merge、版本和冲突诊断。
- `ParsePaperRequest`、`ParsePaperResult`、`ParsePaperUseCase`。
- LaTeX、PDF、HTML/OpenReview、publisher 和 local artifact 的分层解析与降级。
- `ResearchDocument`、sections、figures、tables、equations、references、chunks、evidence pack、parser attempts、quality report 的持久化。
- `ResearchPaperCatalogEntry`、`ResearchPaperRelation`、Catalog query/repository ports。
- Paper 与 task、method、dataset、benchmark、metric、score、code repository 的 typed 关系。
- 复用已有 `ResearchBenchmark`、`ResearchDataset`、`ResearchMetric`、`ResearchScore`、`ResearchBaseline`、`ResearchSOTAClaim`、`ResearchMethod` 和 `MethodGraph` 的稳定领域语义；若现有模型缺少本 PRD 所需的 provenance、scope、version 或 verification 字段，必须做向后兼容的 contract migration，不能把缺口藏进 `metadata`。
- GitHub repository enrichment 与可复现性 observations。
- benchmark candidate、conflicting、verified gate，协议兼容性和 leaderboard filtering。
- application facade、HTTP API、CLI、JSON/OpenAPI contract、统一错误 envelope。
- tenant/user isolation、幂等 ingest、durable run/event transcript 和 filesystem artifact/catalog store。
- fixture、unit、contract、architecture、integration 和端到端验收测试。

### 6.2 明确不包含

- 不修改 `frontend`，不添加前端专用兼容字段以掩盖后端模型缺失。
- 不重新实现已有 parser cascade、RAG retrieval、arXiv connector、GitHub basic connector、Paper Card 或 Reader；新 application use case 只复用它们提供的能力，通过 ports 注入。现有组件不是完整的 v1 闭环：source resolver、跨来源 identity、durable Catalog store、统一 `ParsePaperUseCase` 和新的 provenance/quality contract 仍需建设。
- 不执行第三方仓库代码，不自动安装未知依赖，不建设代码复现平台。
- 不直接抓取或依赖 Papers with Code 实时数据库、排行榜或 API。
- 不允许 LLM 决定 workflow routing、parser fallback、quality pass/fail、leaderboard ranking、publication、memory write 或 actor scope。
- 不把所有 Catalog 关系塞进 `ResearchPaper.metadata`、`ResearchPaperCard` 字符串字段或不可查询的 JSON blob。
- 普通 business run 不直接更新 active skill package 或 memory；repair experience 按现有 Harness/memory workflow 处理。
- v1 不承诺异步分布式调度；application call 有界同步，保留后续接入 scheduler 的扩展点。

## 7. 架构原则与模块边界

### 7.1 运行路径

```text
HTTP API / CLI / SDK
        |
        v
interfaces/services (request mapping, actor context, response envelope)
        |
        v
application (ParsePaperUseCase, CatalogQuery, Refresh, Compare)
        |
        v
domain (identity, document, relation, evidence, score, validation gates)
        |
        v
ports (source, parser, artifact, catalog, event, GitHub, clock)
        |
        v
infrastructure adapters (arXiv/OpenReview/DOI/publisher/local/GitHub/filesystem)
```

既有的业务运行路径仍遵循 `source collection -> evidence -> agent analysis -> report -> quality gate -> artifacts/storage`。本 PRD 增加论文结构化和 Catalog 投影，但不把 parser 或 store 直接暴露给接口层。

### 7.2 模块职责

| 模块 | 允许职责 | 禁止职责 |
| --- | --- | --- |
| `backend/research/domain` | 值对象、实体、状态、确定性规范化、identity merge、relation/score gate | HTTP、文件路径拼接、网络请求、LLM prompt |
| `backend/research/application` | 用例编排、事务边界、幂等、phase transition、权限 gate、错误映射 | 直接依赖具体 HTTP client、filesystem SDK 或 parser 实现 |
| `backend/research/ports` | source/parser/artifact/catalog/event/GitHub 的抽象接口 | 业务决策和绕过 application 的快捷实现 |
| `backend/research/document` | document model、locator、chunk/evidence projection、parser result normalization | source fetch、leaderboard ranking |
| `backend/research/benchmark` | score/claim candidate、protocol compatibility、verification 和 leaderboard filtering | 以 LLM 结果替代 deterministic gate |
| `infrastructure` | 具体 fetch、parser adapter、GitHub/HTML/PDF/LaTeX、filesystem store、retry policy | 私自改变业务状态或 actor scope |
| `interfaces/services` | DTO mapping、actor context、调用 application、统一 response/error | 直接调用 parser、repository 或 infrastructure |
| API router / CLI | 参数解析、序列化、退出码、分页/过滤参数 | 业务编排、identity merge、score verification |

本表描述的是 v1 的目标边界，不等同于当前代码已经全部满足。兼容性审查以 `HEAD 43e0f6896a` 为基线；审查结论和迁移动作见第 27 节。实现时保留现有 analyze/reader/RAG 路径，在其旁边增加独立的 Parse/Catalog application facade，避免用新 contract 破坏既有调用者。

### 7.3 Harness 与 LLM 边界

Harness 是流程控制者，遵循有界 `PLAN -> EXECUTE -> VERIFY` 状态机，记录每次 phase transition、retry、degrade、conflict、quarantine 和 publication event。LLM 只能生成候选的 method、taxonomy、benchmark claim、code alignment 或实体链接；它不能决定：

- 是否走哪个 source/parser/fallback 路由；
- quality report 是否通过、paper 是否 `parsed`；
- score 是否 verified、谁是 SOTA、leaderboard 排名；
- 是否写入 memory、发布 Catalog 或改变 actor scope；
- 是否授权工具、读取 secret、执行代码或跳过 evidence gate。

确定性函数/service 负责 identity resolution、normalization、schema 校验、lineage、metric compatibility、relation validation、leaderboard filtering 和所有状态转移。

## 8. 领域模型

以下模型是 v1 的目标 typed entity/value object contract，不能退化为 `ResearchPaper.metadata` 中的字符串集合。字段名称是 JSON contract 的逻辑名称；具体 Python 类型和存储实现由 change tasks 决定。第 27 节会标出哪些字段可以直接复用当前模型、哪些字段必须通过 migration 新增；未标为“已有”的字段不能在实现计划或发布说明中写成现成功能。

### 8.1 `ResearchSourceSnapshot`

记录某次获取到的来源事实，创建后不可原地修改，refresh 通过新 snapshot 表示。

| 字段 | 说明 |
| --- | --- |
| `snapshot_id` | source snapshot 唯一标识 |
| `paper_id` | 关联 canonical paper |
| `source_type` | `arxiv`、`openreview`、`doi`、`crossref`、`publisher`、`local`、`github`、`manual` |
| `canonical_url` | 规范化 URL；local source 可使用受控 artifact URI |
| `external_id` | arXiv/DOI/OpenReview/repository 等外部 id |
| `content_type` | `latex`、`pdf`、`html`、`json`、`metadata`、`repository_snapshot` 等 |
| `source_hash` / `checksum` | 内容或 metadata snapshot 的完整性校验值 |
| `fetched_at` | 获取时间；与论文发布时间区分 |
| `access_status` | canonical coarse status：`available`、`metadata_only`、`denied`、`failed` |
| `diagnostic.reason_code` | 细分原因，如 `rate_limited`、`not_found`、`unsupported_format`、`timeout`、`robots_disallowed`、`size_exceeded`；不能把细分原因伪装成新的 canonical status |
| `lineage` | 上游来源、resolver、parent snapshot、request/run 信息 |
| `artifact_refs` | 原始内容和派生 artifact 的引用 |
| `metadata` | 非核心、受 schema 约束的来源观察 |
| `actor_scope` | 目标 contract 中的规范化 `tenant_id`、`user_id`、`memory_namespace`；当前部分旧模型仍把 scope 放在 `metadata`/`lineage`，迁移后必须提升为可过滤的 typed scope |

### 8.2 `ResearchPaperIdentity`

统一表示论文身份，不等同于某一个来源快照。现有基线已经有基础 identity/fingerprint 类型，但 canonical version、source snapshot refs、conflict diagnostics 和 typed actor scope 的完整生命周期仍属于本 change 的目标 contract。

至少包含：`paper_id`、`canonical_title`、`authors`、`publication_year`、`canonical_url`、`arxiv_id`、`doi`、`openreview_id`、`versions`、`external_links`、`source_snapshot_refs`、`title_author_year_fingerprint`、`metadata_conflicts` 和 `actor_scope`。

identity merge 规则：

1. 同 actor scope 内，优先依据相同 external id（DOI、arXiv、OpenReview）合并。
2. external id 缺失时，依据 canonical URL 合并。
3. 仍无法匹配时，才使用规范化标题、作者集合和年份的可解释指纹；指纹匹配必须记录规则和相似度/缺失字段。
4. 版本号、发布日期或内容 checksum 不同时，保留独立 source snapshot；如果产品需要区分版本，使用 `paper_id + version_id` 查询，不能覆盖历史版本。
5. 标题、作者、年份、摘要等字段冲突必须记录 `conflict_diagnostics` 以及每个值的 provenance，不得静默选择“最后写入者”。
6. 不同 actor scope 永不合并，也不允许用查询结果推断对方 scope 的存在。

### 8.3 `ResearchDocument`

表示某个 source snapshot 解析得到的结构化论文文档，至少包含：

- `document_id`、`paper_id`、`source_snapshot_id`、`source_hash`；
- `title`、`abstract`、`authors`、`sections`、`figures`、`tables`、`equations`、`references`；
- 每个元素的稳定 id、顺序、父子关系、原始 locator、文本和 content hash；
- parser backend、parser version、normalization version、language 和 extraction metadata；
- source lineage、artifact refs、created_at、observed_at 和 actor scope。

locator 至少支持 source type 对应的 `page`、`section_path`、`figure_id`、`table_id`、`equation_id`、`line_start/line_end`、HTML anchor 或 LaTeX source file/offset。无法精确定位时必须显式标记 `locator_precision=coarse`。

### 8.4 `ParserAttempt`

每个 parser backend 的尝试都必须持久化，不论成功、失败还是被跳过：

`attempt_id`、`document_id`、`backend`、`input_format`、`started_at`、`finished_at`、`duration_ms`、`status`、`quality_score`、`selected`、`fallback_reason`、`error_code`、`diagnostics`、`artifact_refs` 和 `actor_scope`。当前 `CascadeDocumentParser` 已能产生基础 attempt/quality 信息，但 attempt 的 durable schema、document 关联和 actor scope 需要由 Parse application 持久化。

禁止吞掉异常或只保留最终 backend。诊断中不得包含 secret、prompt、访问 token 或未授权的原始代码内容。

### 8.5 `ResearchEvidencePack`

证据包把结构化 claim 连接回来源：

`evidence_id`、`paper_id`、`claim_type`、`claim_text`、`source_snapshot_id`、`document_id`、`element_ref`、`locator`、`quote_or_span`、`claim_refs`、`confidence`、`lineage`、`created_at`、`actor_scope`。

证据可以来自标题/摘要、正文段落、表格单元格、caption、脚注、代码链接、metadata 或 GitHub observation。没有 evidence ref 的关系、score、SOTA claim 和 method graph edge 一律不能进入 `verified`。现有 evidence/domain builder 可复用其基础结构，但本 change 要补齐 source snapshot、document/element locator、checksum 和 durable pack ref。

### 8.6 `ChunkManifest`

chunk 是 RAG、阅读和问答的可复用投影，不是 document 的替代品。每项至少包含：`chunk_id`、`paper_id`、`document_id`、`source_hash`、`chunk_type`、`section_path`、`parent_element_ref`、`content_hash`、`content_ref`、`source_locators`、`semantic_key`、`parse_source`、`stale_of` 和 `actor_scope`。

source hash 变化时，旧 chunk 保留为历史，新的 manifest 通过 `stale_of` 或版本关系标记，不能让同一个 chunk id 指向不同内容。现有 chunk pipeline 主要服务 arXiv/RAG 重建；v1 必须在 Parse application 中把 manifest 作为带 scope、source snapshot 和 artifact ref 的持久化投影，而不是把一次重建当作完整历史。

### 8.7 `ResearchPaperCatalogEntry`

Catalog entry 是一个 paper 的聚合查询投影，至少包含：`entry_id`、`paper_id`、`identity_ref`、`status`、`relation_refs`、`source_snapshot_refs`、`evidence_coverage`、`created_at`、`observed_at`、`last_refresh_run_id`、`metadata` 和 `actor_scope`。

`ResearchPaperCard` 只能作为展示 projection。Catalog 的事实必须来自 typed entities 和 typed relations；卡片字段丢失的信息不能反向作为 Catalog 事实。

### 8.8 `ResearchPaperRelation`

关系字段：`relation_id`、`paper_id`、`relation_type`、`target_id`/`target_ref`、`status`、`confidence`、`source_snapshot_refs`、`evidence_refs`、`created_at`、`observed_at`、`observed_by`、`metadata`、`actor_scope`。当前关系模型对 refs 的约束偏向“所有状态都必须有 refs”，v1 需要迁移为 candidate-first 语义：候选可以暂缺 evidence，但必须保留缺失诊断；只有 verified 才强制 source/evidence refs。

v1 至少支持：

- `paper -> task`
- `paper -> method`
- `paper -> dataset`
- `paper -> benchmark`
- `paper -> metric`
- `paper -> score`
- `paper -> code_repository`

relation status 至少包括 `candidate`、`verified`、`rejected`、`conflicting`。candidate 不代表产品认定事实；conflicting 不得被查询层默认为 verified。

### 8.9 `CodeRepositoryProfile`

支持一个 paper 对多个 repository：

`repository_url`、`canonical_repo_id`、`owner`、`name`、`default_branch`、`observed_branch`、`commit_sha`、`release`、`observed_at`、`stars`、`forks`、`watchers`、`license`、`readme_ref`、`requirements_ref`、`install_signal`、`examples_signal`、`training_signal`、`inference_signal`、`checkpoint_signal`、`observations`、`source_snapshot_refs` 和 `actor_scope`。

这些字段表示 observation/evidence，不表示代码已经安装、运行或复现论文结果。缺少 README、依赖或 checkpoint 是“未观察到信号”，不能直接判定项目不可复现。

## 9. Source、snapshot 与身份解析

### 9.1 输入类型

| `source_type` | 典型输入 | 主要事实 |
| --- | --- | --- |
| `arxiv` | arXiv URL/id | metadata、PDF、可选 LaTeX source、版本 |
| `openreview` | forum/note URL/id | note metadata、HTML、评论/版本观察（按授权） |
| `doi`/`crossref` | DOI URL 或 DOI 字符串 | DOI metadata、publisher link、发表信息 |
| `publisher` | publisher URL | 页面 metadata、HTML/PDF（受访问策略约束） |
| `local` | 受控 local path 或 contentRef | local PDF/LaTeX/archive，需 path/size 校验 |
| `github` | repository URL | repository profile 和 code observation |
| `manual` | 已授权的结构化输入 | 人工确认或外部导入的 provenance |

### 9.2 Source resolver 行为

1. 规范化 URL、external id 和 content reference。
2. 检查 actor scope、robots、访问策略、超时、重试、最大响应大小和 content type。
3. 先获取可用 metadata，再决定是否请求全文或 repository snapshot。
4. 每次获取生成不可变 `ResearchSourceSnapshot`，并记录 lineage 和 checksum。
5. 访问拒绝、限流、缺失、unsupported format 和网络错误都返回明确 `access_status`/diagnostic。
6. 全文不可访问时，允许后续 Catalog 使用 metadata candidate，但状态只能是 `metadata_only`，不能伪装为 `parsed`。
7. 复用现有 infrastructure policy；`backend/research` 不复制一套 robots/rate-limit/retry 规则。

canonical status 的映射固定为：权限/robots 或明确拒绝使用 `denied`；仅有元数据使用 `metadata_only`；可重试的限流、超时和临时网络故障使用 `failed` 并在 diagnostics 标记 `retryable=true`；格式不支持、资源不存在或永久错误使用 `failed` 并标记对应 `reason_code`。这样 API/CLI 可以同时稳定地按 status 过滤，又不会丢失运维诊断粒度。

### 9.3 Snapshot 生命周期

- snapshot 是事实快照，refresh 创建新 snapshot。
- 同一 checksum 的重复 snapshot 可以被幂等复用，但必须能关联新的 run 请求。
- 内容或 metadata checksum 变化时创建新 snapshot，旧 snapshot 保留历史并标记 superseded/observed history。
- parser、document、chunk、evidence 和 Catalog relation 都要写入使用的 snapshot ref。
- snapshot artifact 缺失或 checksum 不一致时，读取返回 `store_corrupt`/`artifact_missing` 诊断，不静默重新生成历史事实。

### 9.4 与现有 source connector 的兼容

当前代码已有 arXiv metadata/source provider、fetch policy、robots/rate-limit/retry 和 GitHub 基础 client。它们可作为 infrastructure adapter 的输入，但不能直接充当 v1 的 source resolver contract：现有 arXiv provider 不覆盖 OpenReview、DOI/Crossref、publisher 和 local artifact，也不会替代跨来源 identity merge。新增 resolver 必须把各 adapter 的异常映射为本节定义的 canonical `access_status` 加 `diagnostic.reason_code`，并由 application 统一创建 snapshot；adapter 不得自行写 Catalog 或改变 paper status。

## 10. 论文解析与质量策略

### 10.1 Application use case

新增：

- `ParsePaperRequest`
- `ParsePaperResult`
- `ParsePaperUseCase`

它与已有完整分析流程分离，但输出可以被后续分析、阅读、RAG 和 Harness run 消费。application 负责顺序、权限、幂等和持久化；parser 只负责把输入转成 parser result，不直接写 Catalog 或改变 workflow 状态。当前代码没有统一的 `ParsePaperUseCase`；已有 `BatchIngestService`/chunk pipeline 是 arXiv 特化的 RAG 入库路径，不能直接当作本节 use case。新 use case 应通过 ports 编排 source resolver、LaTeX/PDF/HTML parser、document/evidence/catalog repositories 和 event sink。

### 10.2 请求处理流程

```text
received
  -> resolving
  -> identity resolution / merge
  -> source snapshot persistence
  -> metadata_only 或 parsing
  -> parser attempts / fallback
  -> document persistence
  -> chunk manifest projection
  -> evidence pack persistence
  -> Catalog candidate projection
  -> deterministic gates
  -> catalog_partial 或 catalog_ready
```

每个箭头都要产生 durable event；异常通过受控 retry、degrade 或 halt 处理。application call 必须有最大执行时长、最大 source size、最大 parser attempts 和 retry budget。

### 10.3 Parser 路由

| 输入 | 首选 parser | fallback/结果 |
| --- | --- | --- |
| LaTeX source/archive | `LatexSourceParser` | 失败后尝试可用 PDF；仍失败则 `degraded`/`metadata_only` |
| PDF URL/artifact | `CascadeDocumentParser` | 保留每个 backend attempt；低质量则 `degraded` |
| HTML | `HtmlDocumentParser`（新增确定性 adapter） | document adapter 或 metadata-only |
| OpenReview | OpenReview HTML/document adapter（新增 source adapter） | metadata-only；按授权处理 revision |
| publisher HTML/PDF | publisher/document adapter（新增 source adapter） | robots/登录/大小受限时 metadata-only |
| local PDF | 同一 `CascadeDocumentParser` | local path/size/format 校验失败时明确失败 |
| local LaTeX | `LatexSourceParser` | 可选 PDF fallback |
| 不支持的二进制 | 无 | `failed`，`unsupported_format` |

### 10.4 Quality report

质量报告至少包含：

- parser backend、attempt 列表和选中原因；
- section/figure/table/equation/reference/chunk 数量；
- locator 覆盖率和 source hash；
- metadata、abstract、正文和表格的缺失项；
- quality score、质量阈值、degraded 标记；
- fallback、拒绝或不支持原因；
- 可重试性、用户行动建议和诊断 id。

质量策略：

1. 低质量 document 只能标记 `degraded`，不能创建空的 `parsed`。
2. 只得到 metadata 时使用 `metadata_only`，并明确说明没有全文结构。
3. parser exception 必须可见；不得在 catch 后返回默认空列表。
4. 质量 gate 是 deterministic service，LLM 输出只能作为 candidate 或补充 evidence。
5. Catalog 允许在有 metadata 的情况下进入 `catalog_partial`，但只有所有必需关系和 gate 通过时才能 `catalog_ready`。

## 11. Paper-with-Code Catalog

### 11.1 Catalog 构建

Catalog projection 从以下事实产生：

- paper identity 和 metadata；
- document sections/tables/captions；
- evidence pack；
- 现有 method/dataset/benchmark/metric/score/baseline/SOTA domain entities（复用其稳定字段，补齐本 change 所需的 typed refs/scope/protocol）；
- GitHub repository observations；
- 人工确认或外部导入的 provenance。

所有自动抽取关系默认 `candidate`。candidate 可以在证据尚未补齐时保留，但必须带 `evidence_missing` 或其他缺口诊断；只有 schema、identity、lineage、evidence、actor scope 和 domain compatibility gate 通过后，关系才可变为 `verified`。gate 失败时使用 `rejected` 或 `conflicting`，并保留原 candidate 和 diagnostics。

### 11.2 关系查询语义

- 单篇论文查询返回所有关系，默认按 status 分组而不是隐藏 candidate/conflicting。
- `verified` 查询只能返回 source/evidence refs 完整且在当前 actor scope 内的关系；candidate、rejected、conflicting 必须可查询并保留其诊断。
- relation target 必须存在或有明确 external reference；悬空 target 不能 verified。
- 同一 paper、relation type、target、source snapshot 和 observation time 的重复关系幂等。
- 不同 source 对同一关系给出不同 target/value 时，保留多个 observations，并创建 conflict diagnostic。

## 12. Benchmark、score 与排行榜可信度

### 12.1 Score 字段

`ResearchScore` 至少包含（目标 v1 contract）：

`score_id`、`paper_id`、`benchmark_id`、`dataset_id`、`metric_id`、`value`、`baseline_ref`、`status`、`split`、`unit`、`direction`、`evaluation_protocol`、`dataset_version`、`source_snapshot_refs`、`evidence_refs`、`observed_at` 和 `actor_scope`。

### 12.2 Candidate-first

论文正文、表格、caption、脚注和 metadata 中出现的 benchmark 结果先生成 `candidate`。候选至少要保留原始显示值、单位、表头/列名、表格 locator、抽取规则和 normalization diagnostics。LLM 可提出实体映射或 claim，但不能直接生成 verified score。

### 12.3 Verified gate

`verified` 需要同时满足：

1. `paper`、`dataset`、`benchmark` 和 `metric` 都有稳定实体或经人工确认的 external reference。
2. 存在至少一个有效 `evidence_ref`，可定位到正文、表格、caption 或授权 metadata。
3. `split`、`unit`、`direction`、`dataset_version` 和 `evaluation_protocol` 完整。
4. 数值可解析、单位可规范化，且不存在同一来源的 unresolved conflict。
5. actor scope、source lineage、schema 和 relation integrity gate 通过。
6. verified 来源是 deterministic gate 或明确的人工确认，不能由模型置信度单独触发。

缺少任一项保持 `candidate`，并记录缺失字段；同一实体组合出现不可解释的不同值时标记 `conflicting`。`candidate` 和 `conflicting` 永远不得进入 verified leaderboard。已有 score gate 的基础 evidence 校验可以复用，但 source snapshot refs、dataset version、协议字段和 scope 传播需要按本 contract 补齐。

### 12.4 比较兼容性

以下条件任一不兼容，就不能横向比较或合并排名：

- `higher_is_better` 与 `lower_is_better` 方向不同；
- dataset 或 benchmark version 不同；
- split 不同（例如 `test` 与 `validation`）；
- unit 不同且没有确定性转换；
- evaluation protocol、预处理、样本范围或任务定义不一致；
- metric 名称相同但定义、聚合方式或方向不同。

兼容性判断结果要返回具体 `incompatibility_reason`，而不是简单过滤掉结果。

### 12.5 Leaderboard

leaderboard 只展示 verified 且协议兼容的 score，并保留 `observed_at` 快照时间。默认排序依据 metric direction：higher-is-better 降序，lower-is-better 升序。不同 dataset version、split、unit 或 protocol 必须分组展示，不能混成一个排名。

查询结果应包含 `included_scores`、`excluded_scores` 以及每个排除原因。candidate、rejected、conflicting、scope forbidden、缺 evidence 和不兼容 score 都应可诊断。refresh 不覆盖历史结果，历史快照可按时间查询。

### 12.6 SOTA claim

`ResearchSOTAClaim` 只有在关联到 `score`、`benchmark`、`dataset`、`metric`、兼容的 protocol 和 evidence 时才有机会 `verified`。只包含“we achieve state of the art”文字、没有可核对数值或协议的 claim 必须保持 `candidate`；缺少 benchmark/dataset/metric 的不完整 claim 也必须作为 candidate 保留，不能在抽取阶段直接丢弃。SOTA 的认定不能由论文自称或 LLM 判断单独完成。

## 13. GitHub Repository Enrichment

### 13.1 观察范围

允许读取的内容由现有 source/robots/size/授权 policy 决定，至少支持：

- repository metadata、default branch、selected branch、commit SHA、release/tag 和 observed_at；
- README、license、依赖声明或安装说明的受控 artifact ref；
- examples、training、inference、checkpoint/model download 的路径或关键词观察；
- 论文正文中的代码 URL 与 repository canonical id 的对应关系。

### 13.2 安全与语义

- 可存在多个 repository；不能把第一个 URL 当作唯一代码来源。
- 记录 branch/commit/release，避免“当前 main”覆盖论文发表时的历史上下文。
- observations 是 evidence，不代表安装成功、训练成功、推理成功或结果复现。
- 不执行 shell、workflow、container、notebook 或 repository test。
- 不自动安装未知依赖，不读取 secrets，不返回未授权的原始代码内容。
- 访问失败、限流、私有仓库或受限路径要保留 diagnostics 和 source snapshot 状态。

当前 `GithubResearchRepositoryAdapter` 已能读取基础 repository profile/observation（例如 stars、forks、default branch 和 commit/release 的部分信息），但尚未提供 README、安装、examples、training、inference、checkpoint 的 typed observations，也没有把这些观察统一绑定到 paper 的 `ResearchSourceSnapshot`。v1 的 enrichment 应扩展现有 adapter 和 GitHub connector，在受控读取范围内生成 observation/evidence artifact；不能把已有基础 profile 当作完整的可复现性判断。

## 14. API 需求

### 14.1 通用规则

- HTTP router 只负责认证上下文、参数校验、application 调用、状态码和序列化。
- router 不得直接调用 parser、store、GitHub client 或具体 infrastructure adapter。
- 所有 endpoint 返回 `run_id`（若操作产生 durable run），以及 `status`、`diagnostics`、`provenance` 和 `artifact_refs`（按权限过滤）。
- 分页、排序和过滤必须是显式参数；默认不跨 actor scope 查询。
- 不向公开 API 返回 prompt、secret、token、内部绝对路径、未脱敏异常堆栈或未授权原始代码。

### 14.2 Parse request

`POST /api/v1/research/papers/parse`

请求支持：

- `source`：URL、external id 或受控 source descriptor；
- `sourceType`：可选，缺省时由 resolver 确定并记录推断；
- `contentRef`：已上传或已授权的 local artifact ref；
- `runId`：调用方提供的关联 run id（若允许）；
- `options`：parser preference、refresh、includeCode、includeCatalog、quality profile 等；
- `metadata`：用户提供的非权威提示，必须标记为 caller-provided；
- actor scope 由认证上下文提供，不接受客户端覆盖。

响应至少包含：

`runId`、`paperId`、`status`、`paper`、`identity`、`sourceSnapshots`、`document`（可为 ref）、`parserAttempts`、`qualityReport`、`evidencePackRef`、`chunkManifestRef`、`catalogEntry`/`catalogStatus`、`artifactRefs`、`diagnostics`、`provenance`、`idempotent`。

### 14.3 查询与 refresh endpoints

| 方法 | 路径 | 语义 |
| --- | --- | --- |
| `GET` | `/api/v1/research/papers/{paper_id}/sources` | 当前 scope 的 source snapshots、访问状态、checksum、lineage |
| `GET` | `/api/v1/research/papers/{paper_id}/document` | document、结构元素、locators、parser attempts 和 quality |
| `GET` | `/api/v1/research/papers/{paper_id}/catalog` | typed relations、status、confidence、evidence/provenance |
| `GET` | `/api/v1/research/papers/{paper_id}/code` | 多仓库 profile、branch/commit/release 和 observations |
| `GET` | `/api/v1/research/papers/{paper_id}/benchmarks` | score、claim、candidate/verified/conflicting 和兼容性诊断 |
| `GET` | `/api/v1/research/catalog/papers` | 按 query/task/method/dataset/status/scope 分页搜索 |
| `GET` | `/api/v1/research/catalog/leaderboards` | 只按兼容协议聚合 verified score；返回排除原因 |
| `POST` | `/api/v1/research/catalog/refresh` | 对一个或多个 paper 真实重取、重解析、重建 Catalog |

`leaderboards` 至少支持 `benchmarkId`、`metricId`、`datasetId`、`datasetVersion`、`split` 和 `evaluationProtocol` 过滤。refresh 请求必须有权限和 retry budget，并返回新 `run_id` 及历史 snapshot refs。

以上 parse/Catalog endpoints 是 v1 新增 contract；当前 research router 主要提供 `analyze`、`analysis`、`reader`、`ask`、`rag-ask` 和 run trace。新路由必须接入 `ResearchApplicationService` 的新 facade 方法，保持旧路由响应兼容，不把现有 `analyze` handler 改写成 parse handler。

### 14.4 错误 envelope

所有 endpoint 使用统一结构：

`code`、`message`、`details`、`retryable`、`userActionRequired`、`runId`、`paperId`、`provenance`、`diagnosticRefs`。

错误码至少包括：

`invalid_request`、`source_not_found`、`source_denied`、`source_rate_limited`、`source_timeout`、`unsupported_format`、`metadata_only`、`identity_conflict`、`parser_failed`、`parser_quality_rejected`、`catalog_not_found`、`catalog_relation_conflict`、`metric_incompatible`、`scope_forbidden`、`artifact_missing`、`store_corrupt`、`research_runtime_unavailable`。

错误码要区分用户可修复、可重试和系统故障，不能用 `500` 包装所有 source denial 或质量降级。

## 15. CLI 需求

新增命令：

```text
paper parse <source>
paper ingest <source>...
paper refresh <paper_id>
paper catalog show <paper_id>
paper catalog search [query]
paper benchmark compare
paper code inspect <paper_id>
```

所有命令支持 `--json`，并使用与 API 相同的 `status`、错误、provenance、diagnostics、run id 和 artifact ref 字段。批量 ingest 需要逐项返回结果，单项失败不得隐藏其他项的成功或降级状态。

常用参数包括：`--tenant`/`--project`（只能与认证 scope 校验）、`--refresh`、`--source-type`、`--quality-profile`、`--include-code`、`--include-catalog`、`--status`、`--benchmark`、`--dataset`、`--metric`、`--split`、`--protocol`、`--limit`、`--cursor` 和 `--json`。CLI 只调用 application facade，不直接 import parser 或 store 实现。

退出码应区分：参数错误、scope 禁止、source 不可用、metadata-only/degraded、解析失败、Catalog gate 失败、存储错误和成功；`--json` 输出仍要包含完整错误 envelope。

这些是 v1 目标命令。当前 CLI 已有的 `paper ingest`/`paper ask` 仍服务既有 arXiv/RAG 流程；迁移时应新增 parse/catalog 子命令并把旧 ingest 逐步改为 application facade，不能让新命令直接实例化 `BatchIngestService`、chunk store 或 GitHub client。

## 16. 状态机与 durable event

### 16.1 统一状态

论文 run/aggregate 的状态固定为：

`received`、`resolving`、`metadata_only`、`parsing`、`parsed`、`degraded`、`catalog_partial`、`catalog_ready`、`failed`。

### 16.2 合法路径

- 正常全文路径：`received -> resolving -> parsing -> parsed -> catalog_partial -> catalog_ready`。
- metadata 路径：`received -> resolving -> metadata_only -> catalog_partial`。
- 解析降级路径：`parsing -> degraded -> catalog_partial`。
- 可重试 source/parser 错误：当前状态记录失败诊断，按 retry budget 回到允许的 phase；耗尽后 `failed`。
- 不支持、scope forbidden、artifact corrupt 或不可恢复错误：进入 `failed`，不伪造 `parsed`。

状态转移必须由 application/Harness 控制，domain service 校验合法性。LLM 输出不能改变状态。

### 16.3 Event schema

每个 phase transition、retry、degrade、conflict、quarantine、verification 和 publication event 至少包含：

`event_id`、`run_id`、`event_type`、`from_status`、`to_status`、`occurred_at`、`paper_id`、`source_snapshot_id`、`actor_scope`、`attempt_id`、`diagnostics`、`artifact_refs`、`causation_id` 和 `correlation_id`。

event log append-only，可用于 replay/review。event 写入失败是 durable runtime error，不得静默忽略。

## 17. 幂等、持久化与 artifact

### 17.1 幂等键

默认幂等键由以下字段规范化后组成：

`actor_scope + canonical identity key + source type + external id/canonical URL + source checksum`。

同一 key 重复 ingest 应返回既有 paper/run/artifact 结果或明确的 in-progress run，而不是复制实体。不同 checksum 或明确 refresh 生成新 snapshot 和新派生 artifact，但不删除历史。

### 17.2 默认 filesystem store

v1 使用 durable filesystem artifact/catalog store，具体布局由 infrastructure 实现决定，但必须满足以下条件。当前已有 `filesystem_run_store`、artifact store 和 local chunk store 只能作为底层原语，不能视为已经存在的 Catalog persistence；本 change 仍需新增 typed Catalog/document/source/evidence store 及 schema migration：

- JSON/JSONL 或等效结构化格式可检查、可备份、可恢复；
- paper、identity、snapshot、document、chunk、evidence、relation、score、catalog 和 run/event 有稳定 refs；
- artifact 记录 checksum、content type、schema version、created_at、source lineage 和 actor scope；
- event/transcript append-only，历史 snapshot 不被新 refresh 覆盖；
- 读取时校验 checksum、scope 和 schema version；损坏返回 `store_corrupt`；
- repository port 与 filesystem adapter 分离，后续可替换数据库而不改 application/domain。

### 17.3 事务与恢复

application 必须先持久化 source/run intent，再写派生 artifact 和状态 event。中途失败后可以通过 durable run 恢复、重试或明确标记失败，不留下“catalog_ready 但没有 document/evidence”的不可解释状态。跨 artifact 的最终一致性要由 event 和 idempotency key 保证。

## 18. 安全、隐私与隔离

- actor scope 从认证上下文解析；客户端不能伪造 tenant/user/project。
- 所有读写、merge、refresh、artifact download、event query 都执行 scope gate。
- source fetch 遵守 robots、rate-limit、timeout、size、content-type、retry 和许可策略。
- local path 必须限制在允许 root，拒绝路径穿越、符号链接逃逸和超大文件。
- 不执行第三方代码、仓库 workflow、notebook 或未知安装脚本。
- secrets、token、prompt、原始未授权代码、内部绝对路径和未脱敏堆栈不得进入公开 API、artifact export 或 diagnostics。
- GitHub/private/publisher 访问失败只暴露可行动的 sanitized reason。
- artifact ref 是 capability-like reference，下载前再次验证 actor scope 和授权。
- 不因解析内容中的 prompt injection 改变 workflow、工具授权、quality gate、publication 或 memory write。

## 19. 可观测性与诊断

至少记录并可按 `run_id`/`paper_id` 查询：

- source fetch 成功、metadata-only、denied、rate-limited、retry 和 timeout；
- identity match、merge、version separation 和 field conflict；
- parser backend、attempt duration、fallback、quality score、degraded 和 rejected；
- document element/chunk/evidence coverage；
- candidate、verified、rejected、conflicting relation/score/claim；
- metric/dataset/split/protocol 不兼容与 leaderboard exclusion；
- GitHub repository enrichment 和 observation 缺失；
- duplicate ingest、scope forbidden、artifact missing、checksum mismatch 和 event write failure；
- Harness phase transition、retry/replan/halt（按现有 durable transcript contract）。

诊断信息要区分 `cause`、`impact`、`retryable`、`user_action` 和 `provenance`。错误报告可以详细，但必须在接口边界做脱敏。

## 20. 非功能需求

| 类别 | 要求 |
| --- | --- |
| 性能 | v1 为有界同步调用；配置最大 source size、parser attempts、单次 run 时长和 retry budget |
| 可靠性 | source、parser、artifact、Catalog 和 event 失败均有显式状态与可恢复诊断 |
| 可追溯性 | 每个派生结果能回到 source snapshot、document locator、checksum 和 run |
| 一致性 | identity、relation、score、artifact 和 event 的写入使用稳定 idempotency key |
| 可测试性 | domain gate 可纯函数测试；ports 可用 fake；application 可用 in-memory store；不依赖网络才能运行核心测试 |
| 可替换性 | parser、source、GitHub、catalog store 通过 ports 替换，application 不绑定具体实现 |
| 安全 | actor isolation、路径/大小/robots policy、敏感信息脱敏和禁止代码执行 |
| 可演进性 | schema version、artifact refs、事件 replay 和未来异步 scheduler 扩展点 |
| 兼容性 | 保留 framework Graph/Harness contracts；不引入 legacy `paper_radar` 依赖 |
| 前端 | 本变更不得修改 `frontend` |
| 外部服务 | 不依赖 Papers with Code 实时服务；外部 source adapter 可失败且必须可诊断 |

## 21. 测试与验收标准

### 21.1 Source 与 identity

- arXiv、DOI 和 publisher 指向同一论文时归并为一个 canonical identity。
- 同一论文不同版本保留独立 snapshot，历史 checksum 和 provenance 可查询。
- 标题/作者/年份冲突产生 diagnostics，不静默覆盖。
- 受限 publisher 返回 `metadata_only`/`denied`，不产生虚假 `parsed`。
- 不同 actor scope 的相同 external id 不合并，且不能互查。
- 重复 ingest 不重复创建 paper、identity、snapshot、document、relation、evidence、chunk 或 artifact。
- 同一 checksum 的重复请求可以复用已有 snapshot，但必须新增 run 关联；refresh 不能删除历史 snapshot。

### 21.2 Parser 与 document

- 复杂 LaTeX fixture 保留章节、图、表、公式、引用、source locators 和 source hash。
- PDF cascade 记录所有 attempts、选中 backend、fallback reason 和 quality report。
- 低质量或 unsupported format 进入 `degraded`/`metadata_only`/`failed`，不返回空 `parsed`。
- HTML/OpenReview/publisher adapter 能保留可用 metadata、正文 locator 和访问限制诊断。
- chunk manifest 的 content hash、parent ref 和 stale version 正确；evidence 能定位正文、表格、figure/caption。
- 受限全文、unsupported format 和 parser denial 都保留 parser/source diagnostics，不以空 document 伪装成 `parsed`。

### 21.3 Catalog 与 benchmark

- Catalog 使用 typed entities/relations，不把关系塞进 metadata/card 字符串。
- 自动抽取 relation、score、SOTA claim 默认 candidate。
- candidate relation 可以暂时没有 evidence refs，但必须保留 source context（若可得）和 `evidence_missing` 诊断；只有 verified relation 强制 evidence refs。
- 无 evidence refs 的 score、SOTA claim 和 method graph edge 一律不能 verified。
- candidate/conflicting/rejected score 不进入 leaderboard，排除原因可查询。
- higher/lower direction、dataset version、split、unit 和 protocol 不兼容时不能横向比较。
- leaderboard 只展示 verified 且兼容的历史快照；排序符合 metric direction。
- SOTA claim 缺少 score、benchmark、dataset、metric 或 evidence 时保持 candidate。
- 缺少 benchmark/dataset/metric 的 SOTA 文本不会被抽取器静默丢弃，能够在 candidate 查询中定位其缺口。

### 21.4 Code enrichment

- 同一论文的多个 repository 都能保存并查询。
- branch、commit、release、observed_at 和 README/install/examples/training/inference/checkpoint signals 可追溯。
- 只记录 observation/evidence，不执行第三方代码、不自动安装依赖、不宣称复现成功。

### 21.5 Interface 与架构

- API/CLI 通过 application service 工作，不 import/调用具体 parser、store 或 infrastructure adapter。
- API 和 CLI 使用相同 status、error、provenance、run 和 artifact 字段。
- `catalog refresh` 会产生真实新 run/snapshot 或明确失败，不返回静态成功。
- 旧 arXiv-specific batch ingest 不能删除历史 source snapshot、document 或 relation；迁移后的 ingest 必须通过同一 application facade。
- durable event 能解释 phase transition、retry、degrade、conflict 和 verification。
- `frontend` 无文件变更。
- `backend/research` 不依赖 legacy `backend/boards/paper_radar`、旧 `interfaces` 或具体 `infrastructure` 路径。

## 22. 交付阶段

### 阶段 1：契约阶段

- 创建并维护 OpenSpec change。
- 冻结 DTO、status、error、provenance、actor scope、artifact ref 和 event schema。
- 准备 LaTeX/PDF/HTML/OpenReview/publisher/multi-source/restricted/duplicate fixture。
- 完成 `openspec validate research-paper-catalog-backend-v1 --strict`。

### 阶段 2：解析阶段

- 完成 source resolver、identity merge、source snapshot、`ParsePaperUseCase`。
- 接通 parser ports 和现有 LaTeX/PDF/HTML adapter。
- 持久化 parser attempts、quality report、document、chunks、evidence、artifact 和 events。
- 完成 metadata-only、degraded、unsupported、retry 和 idempotency 测试。

### 阶段 3：Catalog 阶段

- 完成 Catalog entry/relation aggregate 和 query repository。
- 接入已有 benchmark/dataset/metric/score/method domain entities。
- 完成 GitHub enrichment、多仓库、snapshot 和 observation schema。
- 完成 candidate/verified/conflicting gates、协议兼容性和 leaderboard history。

### 阶段 4：接口阶段

- 完成 application facade、HTTP endpoints、CLI、OpenAPI/JSON contract。
- 完成统一错误 envelope、分页/过滤、actor isolation 和 API/CLI 一致性。
- 验证 API/CLI 不绕过 application service。

### 阶段 5：发布阶段

- 运行端到端回归、故障降级、重复 ingest、scope isolation 和 artifact recovery。
- 检查 durable transcript/event replay、文档同步和 schema version。
- 运行全部本地检查并进行 strict OpenSpec validation。
- 保证 `frontend` 无文件变更后再发布后端 change。

## 23. 验证命令

```powershell
python -m scripts.dev compile
python -m scripts.dev test
python -m scripts.dev smoke
openspec validate research-paper-catalog-backend-v1 --strict
```

`smoke` 是代码变更的必过门槛，应覆盖 compile、Harness/Research/API/service smoke、`tests/architecture` 和 source validation。文档变更至少执行 Markdown/结构检查、OpenSpec strict validation，并在涉及代码时追加上述完整检查。

## 24. 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| publisher 访问受限 | 无全文、结构化结果不完整 | metadata-only、明确 access status、保留 snapshot 和可重试诊断 |
| PDF 解析质量不稳定 | 表格/公式/locators 缺失 | cascade attempts、quality gate、degraded 状态和人工复查入口 |
| 同名论文或元数据冲突 | identity 错合并、事实覆盖 | external id 优先、解释性指纹、版本独立、冲突 provenance |
| benchmark 表格语义复杂 | leaderboard 错排 | candidate-first、协议完整性 gate、兼容性分组、排除原因可见 |
| GitHub 内容变化 | 复现信号过时 | branch/commit/release snapshot、observed_at、历史保留 |
| LLM 产生无证据结论 | 错误关系进入 Catalog | LLM 只产 candidate，deterministic evidence/lineage gate |
| artifact 损坏或路径漂移 | 结果不可追溯 | checksum、immutable refs、store_corrupt 诊断和 event recovery |
| scope 泄漏 | 租户数据暴露 | application 统一 scope gate、artifact 二次校验、跨 scope 禁止 merge |
| 业务逻辑泄漏到接口 | API/CLI 行为分叉 | 单一 application facade、architecture tests、ports 依赖规则 |

## 25. 默认决策与后续扩展

v1 默认决策如下：

- 使用有界同步 application call，返回 durable `run_id`；后续可接入异步 scheduler。
- 使用 durable filesystem artifact/catalog store；repository port 保留数据库替换空间。
- parser、identity、normalization、relation、metric compatibility 和 leaderboard filter 使用 deterministic service。
- LLM 只生成 candidate，不决定 workflow、quality、verification、ranking、publication 或 memory write。
- benchmark 采用 candidate-first；verified leaderboard 只接受 evidence 完整且协议兼容的结果。
- source refresh 创建新 snapshot，保留历史，不覆盖旧事实。
- actor scope 是所有 identity、artifact、query、event 和幂等行为的强制边界。
- `frontend` 保持不变；先通过 API、CLI、fixture 和 artifact 验证后端闭环。
- 不执行第三方代码，不自动安装未知依赖，不依赖 Papers with Code 实时服务。

后续版本可以在不破坏 v1 contract 的前提下增加异步调度、人工 review UI、更多 publisher adapter、数据库 catalog store、受控复现 sandbox 和跨项目公开 Catalog，但这些能力不属于本 PRD。

## 26. 术语表

| 术语 | 定义 |
| --- | --- |
| Source | 用户提交或系统发现的外部论文/仓库入口 |
| Snapshot | 某次获取的不可变来源事实及其 checksum/lineage |
| Identity | 跨 source/version 归并后的 canonical paper 身份 |
| Document | 对某个 snapshot 的结构化解析结果 |
| Evidence | 可回溯到 source locator 的 claim 支撑 |
| Catalog | paper 与 task/method/dataset/benchmark/metric/score/code 的 typed graph/projection |
| Candidate | 已抽取但尚未通过确定性验证的内容 |
| Verified | 通过 schema、evidence、lineage、scope 和兼容性 gate 的内容 |
| Conflicting | 同一语义目标存在未解决来源或协议冲突的内容 |
| Observation | 对代码仓库或外部来源的事实观察，不等于复现成功 |
| Provenance | 描述内容来自哪个 source、artifact、parser、run 和 actor 的链路 |
| Durable run/event | 可以恢复、回放和审计的运行记录与状态转移日志 |

## 27. 与现有代码基线的兼容性审查（2026-08-30）

### 27.1 审查口径

本节以提交 `43e0f6896a`（`fix(research): enforce deterministic benchmark leaderboards`）作为可复现的代码基线。审查结论区分三种状态：

- **可复用**：基线中已有、可以通过 port 或 adapter 接入 v1 的能力；不代表已经满足 v1 的持久化、scope 或 provenance 要求。
- **需扩展**：已有相邻实现，但字段、生命周期、错误语义或调用边界不足以满足本 PRD。
- **新增**：基线没有统一实现，必须在本 change 中设计和交付。

当前工作树中若存在未提交的 Research 草稿，只能视为实现候选或迁移输入，不能替代基线证据，也不能在发布说明中写成“已完成”。

### 27.2 能力映射

| 现有代码路径 | 基线已验证能力 | v1 复用方式 | 必须补齐的缺口/迁移动作 |
| --- | --- | --- | --- |
| `backend/research/document/cascade_parser.py` | 已有 PDF parser cascade、fallback、`ParserAttempt` 基础记录和 quality probe | 作为 PDF parser adapter，由 Parse application 注入 | 统一 `ParserAttempt` durable schema、attempt artifact、locator 覆盖率、质量阈值和 actor scope；低质量必须可降级而不是返回空 `parsed` |
| `backend/research/document/latex_compiler.py`、`arxiv_parser.py`、`source_format.py` | 已有 LaTeX/arXiv 解析和格式探测 | 作为 LaTeX/arXiv adapter 与 parser fixture 基础 | 增加统一 format router、HTML/OpenReview/publisher adapter、source hash/lineage 传递；不要把 arXiv 特化接口暴露给 API |
| `backend/research/document/models.py`、`domain/document.py` | 已有 sections、figures、tables、equations、references、基础 lineage 与 document model | 保留结构元素和稳定 id 的既有语义 | 增加 `document_id`、snapshot 绑定、element locator、parser/version metadata、quality report、artifact refs 和 typed actor scope；当前模型不能直接当作完整 v1 document contract |
| `backend/research/document/chunker.py`、`chunk_manifest.py`、`chunk_paper_pipeline.py` | 已有稳定 chunk id、manifest 检查和 arXiv/RAG chunk pipeline | 作为 chunk projection 和 RAG 兼容输入 | Parse application 要持久化 manifest、source hash、content ref、stale history 和 scope；现有 batch pipeline 是 arXiv-specific 重建路径，不能替代多来源 Parse 或删除历史 snapshot |
| `backend/research/domain/evidence.py`、`services/evidence_builder.py` | 已有 claim/evidence pack 基础结构和部分 document evidence 构建 | 复用 evidence 基础实体与 builder 逻辑 | 增加 snapshot/document/element locator、quote/span、artifact ref、checksum、scope 和 durable pack repository；无 evidence 的 candidate 要保留缺口诊断 |
| `infrastructure/research/source_provider.py`、`infrastructure/external/sources/arxiv.py` | 已有 arXiv metadata/source provider，以及 robots、限流、大小和 retry policy | 作为 `arxiv` source adapter，并复用 fetch policy | 新增 OpenReview、DOI/Crossref、publisher、local resolver；由统一 resolver 生成 snapshot、canonical status 和 lineage。adapter 不得直接写 Catalog 或状态 |
| `backend/research/domain/paper.py`、`backend/research/domain/catalog.py` | 已有基础 `ResearchPaper`、paper source record、identity/source snapshot/relation typed model | 复用 identity/relation 的稳定命名和 fingerprint 语义 | 补齐版本生命周期、跨来源 merge、冲突 diagnostics、snapshot history、scope key 和可解释的 canonical URL/external id 规则 |
| `backend/research/application/catalog.py` | 已有 `ResearchPaperCatalogService`、候选抽取、关系查询和 deterministic leaderboard 比较的 application 级基础 | 抽取其纯业务决策，作为新 facade 的内部服务 | 当前主要是内存/服务级编排，缺少 durable Catalog/document/source/evidence store、统一 Parse 输入、完整 actor scope port 和 SOTA candidate 保留策略；不能把 service 当作持久化层 |
| `backend/research/benchmark/models.py`、`benchmark/gates.py` | 已有 benchmark/dataset/metric/score/baseline/SOTA 基础类型、evidence gate 和部分兼容性判断 | 复用实体语义、方向排序和 compatibility key | score 需要 typed snapshot refs、dataset version、split/unit/protocol/scope；candidate/conflicting 不能进入 leaderboard；不完整 SOTA 必须留在 candidate，而不是抽取时丢弃 |
| `backend/research/method_graph/models.py`、`method_graph/gates.py` | 已有 `ResearchMethod`、`MethodGraph` 和 edge/gate 基础 | 将 paper-to-method 关系映射到 typed method graph，并复用其 gate 语义 | method graph edge 也必须绑定 source/evidence refs、identity 和 actor scope；不能因为 graph 已存在就跳过 Catalog relation 的 candidate/verified 生命周期 |
| `backend/research/domain/code_repository.py`、`infrastructure/research/github_repository.py` | 已有 GitHub 基础 profile/observation、repository URL、部分 branch/commit/release 和指标读取 | 扩展为 GitHub source adapter 和 code relation target | 增加 README/license/install/examples/training/inference/checkpoint 的受控 observations、source snapshot/evidence refs、历史 observed_at 和 scope；基础 profile 不等于可运行或复现成功 |
| `infrastructure/external/sources/github.py` | 已有 GitHub API connector 与访问错误处理 | 复用 HTTP/client policy，不执行仓库代码 | 增加允许读取的文件/README artifact 边界、响应大小与脱敏规则；禁止 workflow、notebook、安装脚本和 secret 读取 |
| `interfaces/services/research_service.py` | 已有 analyze、reader、ask、RAG 和 run trace 的 application facade，以及旧流程 actor/error mapping | 保留旧方法，在同一 service 增加 Parse/Catalog facade 方法 | 不能让新接口直接访问 parser/store；新增方法必须接收规范化 actor scope、返回统一 run/status/diagnostic/provenance，并与旧分析流程解耦 |
| `interfaces/api/routers/research.py`、`interfaces/api/routers/__init__.py` | 已有 research analyze/analysis/reader/ask/rag-ask/trace 路由 | 保持旧路由兼容，新增 PRD 第 14 节 endpoints | parse、sources、document、catalog、code、benchmarks、search、leaderboards、refresh 全部经 application service；不能把旧 `analyze` handler 改名伪装成 parse |
| `interfaces/cli/commands/paper.py` | 已有 arXiv/RAG `paper ingest` 和 `paper ask` | 保持旧命令输出兼容，新增 parse/catalog/benchmark/code 命令 | 所有新命令和迁移后的 ingest 都经 application facade；补 `--json`、scope、过滤、退出码和逐项失败诊断，不能直接实例化 batch/chunk store |
| `infrastructure/research/filesystem_run_store.py`、artifact/chunk stores | 已有 durable run、artifact 和 local chunk 存储原语 | 复用锁、原子写入、checksum 和 artifact ref 约定 | 新增 typed Catalog/source/document/evidence/relation/score store、schema version、scope 查询、历史 snapshot 与 event append-only；旧 run/chunk store 不是 Catalog repository |
| `tests/architecture/test_no_legacy_paper_radar.py` 及现有边界测试 | 已有 legacy `paper_radar` 禁止依赖和部分 interface/infrastructure 边界检查 | 扩展为 Parse/Catalog caller inventory 和 frontend 变更检查 | 增加 API/CLI 不绕过 application、backend/research 不反向依赖 interfaces/infrastructure、scope 传播、durable store 和新 contract fixtures 的测试 |

### 27.3 兼容性结论

本 PRD 与现有代码是**增量扩展兼容**关系，不是“把几个 DTO 接上即可”的文档同步：

1. parser、arXiv fetch policy、document element、chunk/evidence 基础结构和 benchmark 方向排序可以复用。
2. source resolver、跨来源 identity、完整 document/evidence provenance、durable Catalog repository、统一 Parse use case、GitHub reproducibility observation 和新 interfaces 属于新增或明显扩展范围。
3. 既有 analyze/reader/RAG/Harness runtime 必须保持运行；Research Catalog 不能通过修改 `ResearchPaperCard` 或 `ResearchPaper.metadata` 绕过 typed domain。
4. `frontend` 不在迁移边界内；API/CLI/artifact contract 先独立验证，再由后续前端消费。

### 27.4 必须显式处理的 contract 冲突

| 冲突 | 基线行为 | v1 决策 |
| --- | --- | --- |
| relation evidence 约束 | 当前 `ResearchPaperRelation` 校验倾向要求所有状态都有 `source_snapshot_refs` 和 `evidence_refs` | 改为 candidate/rejected/conflicting 可保留不完整 refs，并记录 `evidence_missing`；仅 verified 强制完整 source/evidence refs。需要 schema migration 和回归测试 |
| source access status | 当前 snapshot literal 以 `available`、`metadata_only`、`denied`、`failed` 为主 | 保持四个 canonical status；`rate_limited`、`not_found`、`unsupported_format`、`timeout`、`robots_disallowed` 等下沉到 `diagnostic.reason_code` |
| actor scope | 旧 application service 有部分 actor 绑定，但不是所有 Catalog/domain/store 都是 typed scope | 将规范化 `tenant_id`、`user_id`、`memory_namespace` 贯穿 request、identity、snapshot、artifact、repository、query、event 和 idempotency key；客户端 scope 只能校验，不能覆盖认证上下文 |
| SOTA claim 完整性 | 当前基础 SOTA 模型/抽取逻辑可能要求 benchmark/dataset/metric 才创建 | 不完整文本仍创建 candidate，标出缺失依赖；verified gate 再要求 score、benchmark、dataset、metric、protocol 和 evidence |
| batch ingest 历史 | 旧 arXiv batch/chunk 流程面向重建，可能清理 stale chunks | 新 Parse/refresh 以 immutable snapshot 和 `stale_of` 保留历史；不得因重复 ingest 删除旧 document/evidence/relation |
| GitHub 复现语义 | 基础 adapter 只有仓库 metadata/指标观察 | 新增 signals 仍只能是 observation/evidence；没有代码执行、依赖安装或“复现成功”推断 |

### 27.5 推荐迁移顺序

1. **Contract migration**：先冻结 actor scope、canonical access status、document locator、relation candidate 规则、score/SOTA refs 和 schema version；为现有模型加向后兼容读取与明确诊断。
2. **Source/Parse path**：新增 resolver ports、multi-source adapters、统一 `ParsePaperRequest/Result/UseCase`，把已有 LaTeX/PDF cascade 接入并持久化 attempts/quality。
3. **Durable persistence**：实现 source/document/evidence/catalog/relation/score/event repositories，先写 intent/run，再写派生 artifact；用 checksum、scope 和 schema 校验恢复。
4. **Catalog/gates**：接入 method/dataset/benchmark/metric/code typed relations，补 candidate-first、SOTA candidate 保留、协议兼容性和历史 leaderboard。
5. **Interfaces**：在 `ResearchApplicationService` 和 composition 中接线，再添加 HTTP/CLI/OpenAPI contract；用 architecture tests 禁止直连 parser/store。
6. **Regression/release**：运行 fixture、scope isolation、metadata-only、fallback、重复 ingest、store corruption、leaderboard exclusion、API/CLI parity 和 `frontend` no-change 检查，最后再做 strict OpenSpec validation。

## 28. 实施级产品契约

前面的章节定义产品方向、领域模型和架构边界。本节进一步冻结实现时不能由开发者自行猜测的行为。它是后续 `tasks.md`、DTO、repository、API、CLI 和测试的共同依据；本节描述的是 v1 目标契约，不代表当前工作树已经全部实现。

### 28.1 产品结果定义

一次论文处理只有在下列事实都可以被查询和解释时，才算完成一个可交付结果：

1. 有一个属于当前 actor scope 的 `run_id`，并能查看请求、阶段、耗时、重试和最终状态。
2. 至少有一个不可变 `ResearchSourceSnapshot`，记录输入规范化结果、访问状态、checksum、来源类型和 lineage。
3. snapshot 能归属于一个 canonical paper identity，或者明确记录为什么无法归并。
4. 若有全文，能查询 `ResearchDocument` 及 sections、figures、tables、equations、references 和 source locators；若无全文，结果必须是 `metadata_only` 或 `degraded`，不能用空文档冒充解析成功。
5. document 的派生 chunks、evidence 和 Catalog relation 都能反查到 source snapshot、artifact 和产生它们的 run/event。
6. 自动抽取的 task、method、dataset、benchmark、metric、score、SOTA 和 code relation 默认是 `candidate`；verified 只能由 deterministic gate 或明确人工确认产生。
7. 任何失败、冲突、降级、未授权、限流、checksum 不一致或存储错误，都有稳定的 `reason_code` 和可行动的诊断。

产品不以“返回了 HTTP 200”作为成功定义，而以状态、产物完整性、provenance 和 gate 结果作为成功定义。

### 28.2 用户任务与完成标准

| 用户任务 | 用户输入 | 用户可见结果 | 完成标准 |
| --- | --- | --- | --- |
| 解析一篇论文 | URL、external id 或受控 artifact | paper、document、quality、Catalog summary | 可以定位正文和解析诊断 |
| 补充来源 | DOI、publisher 或 OpenReview URL | 新 snapshot、字段冲突和合并理由 | 不覆盖历史值 |
| 了解论文方法 | paper id、查询过滤 | method/task/dataset relations | 每条关系有 candidate/verified 状态 |
| 判断 benchmark 结果 | benchmark/metric/split/protocol | score groups、included/excluded | 不兼容结果不混排 |
| 检查代码 | paper id 或 repository URL | 多仓库 profile 和 observations | 不把观察误报为可运行 |
| 重试或刷新 | paper id、source、refresh options | 新 run 和新 snapshot | 旧版本仍可读，失败可解释 |
| 批量导入 | 多个 source descriptors | 逐项结果和汇总计数 | 单项失败不吞掉其他项 |

### 28.3 v1 业务不变量

以下不变量必须由 domain/application/repository 层共同保证，不能只依靠 API 参数校验：

- 一个 `document_id` 只能绑定一个 `source_snapshot_id` 和一个 source hash。
- 一个 `source_snapshot_id` 创建后不可原地修改；refresh 只能追加新 snapshot。
- 同一 scope 内，相同 canonical identity、source checksum 和 parser profile 的重复 ingest 不创建第二组事实实体。
- 不同 scope 的相同 DOI、arXiv id 或 URL 不自动合并，也不能通过 Catalog query 互相读取。
- `verified` relation/score/claim 必须有完整 source refs、evidence refs、lineage、target identity 和兼容性 gate 结果。
- `candidate`、`rejected`、`conflicting` 永远不能进入默认 verified leaderboard。
- index、缓存和向量库是可重建 projection，不是论文事实的唯一来源。
- event/transcript 是 append-only；任何状态变化都必须有 causation/correlation 链路。
- LLM 输出只能进入 candidate/evidence proposal 流程，不能直接改变状态、权限、路由或 publication。

## 29. 多层状态机与状态所有权

当前 PRD 中的状态同时涉及 run、source、document 和 Catalog。实现必须把这些状态拆成独立对象，避免一个字符串在不同接口中含义不一致。

### 29.1 状态对象

| 状态对象 | 初始状态 | 允许状态 | 所有者 | 终态 |
| --- | --- | --- | --- | --- |
| `ParseRun` | `received` | `received`、`resolving`、`parsing`、`completed`、`degraded`、`failed`、`cancelled` | application/Harness | `completed`、`failed`、`cancelled` |
| `SourceSnapshot` | `pending` | `pending`、`available`、`metadata_only`、`denied`、`failed` | source resolver | snapshot finalized 后不可变 |
| `ResearchDocument` | `pending` | `pending`、`parsed`、`degraded`、`quarantined` | parser quality gate | `parsed`、`degraded`、`quarantined` |
| `CatalogEntry` | `not_started` | `not_started`、`catalog_partial`、`catalog_ready`、`catalog_failed` | Catalog application service | `catalog_ready`、`catalog_failed` |
| `Relation/Score/Claim` | `candidate` | `candidate`、`verified`、`rejected`、`conflicting` | deterministic gate/authorized reviewer | 可追加新 observation，不覆盖旧状态 |

`ParseRun.status` 是本次执行的状态，`SourceSnapshot.access_status` 是某次来源获取的状态，`ResearchDocument.status` 是文档质量状态，`CatalogEntry.status` 是投影完整性状态。API 可以返回一个聚合 status，但必须同时返回各对象的细分状态。

### 29.2 Run 状态与聚合状态映射

| ParseRun 状态 | Source 状态 | Document 状态 | Catalog 状态 | 对外聚合 status |
| --- | --- | --- | --- | --- |
| `received`/`resolving` | `pending` | `pending` | `not_started` | `received` 或 `resolving` |
| `completed` | `metadata_only` | `quarantined`/不存在 | `catalog_partial` | `metadata_only` |
| `completed` | `available` | `parsed` | `not_started` | `parsed` |
| `degraded` | `available`/`metadata_only` | `degraded` | `catalog_partial` | `degraded` |
| `completed` | `available` | `parsed`/`degraded` | `catalog_partial` | `catalog_partial` |
| `completed` | `available` | `parsed` | `catalog_ready` | `catalog_ready` |
| `failed`/`cancelled` | 任意 | 任意 | 任意 | `failed` 或 `cancelled` |

聚合状态优先级固定为：`failed/cancelled` > `metadata_only` > `degraded` > `catalog_partial` > `catalog_ready` > `parsed`。但是，旧的已成功 snapshot 不会因为新的 refresh run 失败而被改写；聚合查询必须同时暴露 `latest_run_status` 和 `last_known_good_snapshot`。

### 29.3 合法转移与禁止转移

```text
received -> resolving
resolving -> parsing | metadata_only | failed
parsing -> completed | degraded | metadata_only | failed
completed -> catalog_partial | catalog_ready
degraded -> catalog_partial | failed
metadata_only -> catalog_partial | failed
catalog_partial -> catalog_ready | catalog_partial
任何非终态 -> cancelled | failed
```

禁止直接 `received -> catalog_ready`、`metadata_only -> parsed`、`failed -> catalog_ready`，以及在没有新的 run 的情况下把 `catalog_ready` 回写成失败。`catalog_partial -> catalog_partial` 只允许用于追加 candidate、补 evidence 或重跑 gate，并且必须有新的 event 和 attempt id。

### 29.4 Retry、cancel 和恢复语义

- retry 是同一业务 run 下的新 `attempt_id`，不是删除旧 attempt；每次 retry 都记录原因、等待时间和预算消耗。
- source refresh 是新的 `run_id` 和新的 snapshot；仅重建 Catalog projection 可以使用新的 projection run，但不得伪装成 source refresh。
- `cancelled` 只允许在尚未提交不可逆外部副作用前产生；已进入 parser/provider 的请求必须等待受控终止并写终止 receipt。
- 没有 terminal event 的 run 视为 `incomplete`，由 recovery scanner 标记为 `failed` 或重新排队；不能根据文件是否存在推断成功。
- 重启恢复必须保留已提交的 artifact 和 event，跳过已确认完成的阶段，并从最后一个可重放的 commit marker 继续。

## 30. Source Adapter Contract Matrix

### 30.1 各来源行为

| source type | 接受输入 | canonical identity | metadata authority | 全文策略 | 版本/修订规则 | 默认可重试 |
| --- | --- | --- | --- | --- | --- | --- |
| `arxiv` | id、abs/pdf/source URL | bare arXiv id | arXiv metadata | LaTeX 优先，PDF fallback | `vN` 单独 snapshot | timeout、429、临时 5xx |
| `doi`/`crossref` | DOI 字符串、`doi.org` URL | normalized DOI | Crossref，再与 publisher 比较 | metadata 后解析 publisher | online-first、edition 独立 observation | timeout、429、5xx |
| `openreview` | forum/note URL/id | forum/note id | note revision metadata | note HTML/PDF | revision、withdrawn 独立 snapshot | timeout、429、credential temporary failure |
| `publisher` | allowlisted HTTPS URL | final canonical URL | structured metadata/Crossref | HTML 优先，授权 PDF fallback | edition、correction、retraction 独立 snapshot | timeout、429、暂时 5xx |
| `local` | authorized `content_ref` 或 allowlisted path | content checksum | caller metadata 为 non-authoritative | PDF、LaTeX、archive | checksum 变化即新版本 | transient local IO |
| `github` | repository URL，或带 paper context 的 repo ref | owner/repository + commit | GitHub API metadata | 受控 observation，不读取完整源码 | branch/tag/commit/release 独立 observation | timeout、429 |
| `manual` | 已授权结构化 payload | caller-provided external key | 明确标注人工来源 | 不自动获取全文 | revision 由人工提供 | 由调用方决定 |

GitHub URL 不能在没有 paper context 的情况下自动创建论文 identity。它只能创建 repository observation；只有 caller 明确提供 `paper_id`、论文 URL 或人工确认关系时，才可建立 `paper_code_repository` relation。

### 30.2 URL、ID 和重定向规范化

- 仅允许 `https`，本地文件只允许通过 `content_ref` 或 allowlisted root 访问；默认拒绝 `file://`、`data:`、`javascript:`、`ftp:` 和未知 scheme。
- URL host、scheme 规范化为小写，移除默认端口和 fragment；保留会改变版本或资源的 query 参数，并对敏感 query 做脱敏 hash。
- redirect 每跳都重新执行 scheme、host、DNS 和 private-network 检查；禁止 loopback、link-local、RFC1918、云 metadata IP 和本机管理端口。
- DOI 去除 `doi:`、`https://doi.org/` 前缀和尾部标点，比较时大小写不敏感，但原始输入保留在受控诊断 artifact。
- arXiv bare id 与版本 id 分离：`1706.03762` 是 canonical identity，`1706.03762v2` 是 version observation。
- OpenReview 的 forum id、note id、revision id 分别保存，withdrawn/retracted 状态不可静默删除。
- local archive 必须限制压缩层数、文件数、单文件大小、解压后总大小、符号链接和路径穿越。

### 30.3 Access status 与 reason code

| access status | 适用条件 | 典型 reason code | 是否可继续 Catalog |
| --- | --- | --- | --- |
| `available` | 获取到允许使用的内容 | `fetched` | 全部流程 |
| `metadata_only` | 只有可验证 metadata | `full_text_unavailable`、`publisher_login_required` | 仅 metadata candidate |
| `denied` | robots、权限或策略明确拒绝 | `robots_disallowed`、`unauthorized`、`private_source` | 可保留已有事实，不新增全文事实 |
| `failed` | 暂时或永久获取失败 | `timeout`、`rate_limited`、`not_found`、`size_exceeded` | 按 retry/已有 metadata 决定 |

`reason_code` 不能被提升为新的 canonical status。`retryable`、`user_action_required`、`retry_after_seconds` 和 `source_policy` 必须单独保存。

### 30.4 Source snapshot 最小字段

```text
snapshot_id, paper_id?, source_type, canonical_url?, external_id?,
content_type, source_hash?, checksum, access_status, reason_code?,
fetched_at, observed_at, parent_snapshot_id?, version_id?,
artifact_refs, request_fingerprint, resolver_version,
lineage, actor_scope, diagnostics
```

fetch 失败也必须保存 snapshot intent 和 fetch attempt；不能因为没有内容就不留来源事实。

## 31. Identity Match、Merge 与冲突决策

### 31.1 匹配优先级

| 级别 | 匹配依据 | 默认决策 | 是否需要人工确认 |
| --- | --- | --- | --- |
| A | 同 scope、同 external id 且版本兼容 | merge 到同一 identity，追加 snapshot | 否 |
| B | 同 scope、canonical URL 完全一致 | merge，记录 URL 规则 | 通常否 |
| C | 标题/作者/年份 fingerprint 唯一命中 | 创建 match observation，允许 merge | 可配置；默认保守确认 |
| D | 多个 identity 命中或字段严重冲突 | quarantine/identity conflict | 是 |
| E | 只有 caller metadata 或模糊标题 | 创建独立 candidate identity | 是 |

external id 相同不是无条件 merge：版本、撤稿/更正、不同 edition 或 checksum 语义不兼容时，必须保留独立 snapshot/version，并在 identity 中记录关联而不是覆盖。

### 31.2 Title/author/year fingerprint

指纹计算至少包括：Unicode NFKC、大小写折叠、LaTeX 宏清理、标点和空白折叠、标题副标题分隔规范化、作者姓氏集合、发表年份容差。指纹必须保存 `fingerprint_version`、输入字段 hash 和命中的规则。

- 作者顺序变化但集合一致可以提高相似度，不能单独证明是同一论文。
- 年份缺失时不能用当前年份补齐；年份差异超过配置容差时不得自动 merge。
- 标题相似但作者集合明显不同的论文必须保持独立 identity。
- 多个候选 identity 同时命中时不选择“最近写入”的 winner；应进入 `identity_conflict` 并保留候选列表。

### 31.3 Merge 结果与字段 provenance

canonical identity 的每个字段都要保存：`value`、`source_snapshot_ref`、`authority`、`selected_by`、`selected_at` 和 `conflict_refs`。merge 不删除低权威来源，只改变 canonical projection 的 selected value。

跨 tenant 的同一外部论文可以共享不可识别的 global fingerprint（若未来启用），但本地 paper、artifact、event、relation 和权限边界必须完全独立；v1 默认不建立跨 tenant 可查询索引。

## 32. ParsePaper 执行时序、提交点与崩溃恢复

### 32.1 标准执行时序

```text
create run intent
  -> validate actor scope and idempotency
  -> resolve source descriptor
  -> persist immutable source snapshot
  -> resolve/merge canonical identity
  -> persist paper + identity mapping
  -> select parser plan
  -> execute parser attempts
  -> persist document + quality report
  -> publish document/chunk/evidence artifacts
  -> persist chunk manifest and evidence pack
  -> project Catalog candidates
  -> run deterministic gates
  -> append terminal event
  -> persist final result
```

每个箭头都是一个可观测 commit boundary。一个阶段只有在其产物、checksum 和对应 event 都成功后，才可以向下一个阶段转移。

### 32.2 Commit marker 与产物状态

每个 run/artifact aggregate 至少有 `pending`、`committed`、`orphaned` 三种内部写入状态：

- `pending`：已创建 intent，但内容、checksum 或 event 尚未完成；对普通查询不可见。
- `committed`：内容、索引和 event 均已写入并通过一致性检查，可被 application 查询。
- `orphaned`：内容写入但父 aggregate 或 terminal event 缺失；只能被 recovery/operator 查询，不能进入 Catalog 或 leaderboard。

commit marker 必须包含 `run_id`、阶段名、产物 refs、content checksums、schema versions、event ids、created_at 和 actor scope。索引文件只能引用 `committed` marker。

### 32.3 部分写入补偿

| 故障点 | 已完成内容 | 必须做的补偿 | 对外结果 |
| --- | --- | --- | --- |
| snapshot 写成功，identity 写失败 | snapshot committed | 保留 snapshot，写 identity failure event，不生成 relation | `identity_conflict`/`failed` |
| document 写成功，artifact publish 失败 | document pending 或 orphaned | 标记 orphan，禁止 Catalog 引用，等待重试或 quarantine | `degraded`/`failed` |
| artifact publish 成功，repository 写失败 | artifact 已存在 | 通过 commit marker 恢复 repository projection；不能重复发布 | `in_progress` 或 `failed` |
| chunk 失败，document 成功 | document committed | 保留 document，记录 chunk diagnostic，允许后续重建 | `degraded`/`catalog_partial` |
| evidence 失败，score candidate 已产生 | candidate 未验证 | candidate 保留并标 `evidence_missing`，禁止 verified | `catalog_partial` |
| Catalog 写成功，terminal event 失败 | relation projection 已写 | recovery 读取 commit marker，补写 event；补写失败则 quarantine | 不得返回 `catalog_ready` |
| terminal event 成功，final result 写失败 | event 已完整 | 由 event replay 重建 result；不重新执行 source/parser | 可恢复为原状态 |

禁止用“重新从头跑一遍”作为所有崩溃的默认补偿，因为这会产生重复 fetch、重复 artifact、重复 relation 或覆盖历史 provenance。

### 32.4 Recovery scanner

启动或 operator 触发 recovery 时：

1. 扫描 `runs/<run_id>/intent.json`，寻找没有 terminal event 的 run。
2. 根据最新 commit marker 和 append-only events 确定最后可重放阶段。
3. 校验每个已提交 artifact 的 checksum、scope 和 schema version。
4. 对可恢复阶段补写 projection/event；对不完整或损坏产物标记 `orphaned`/`quarantined`。
5. 只有 terminal event、final result 和 Catalog projection 三者一致时，才允许恢复为 `catalog_ready`。
6. recovery 本身创建新的 `recovery_run_id` 或 event correlation，不修改原始事件内容。

### 32.5 并发和相同幂等键

第一个拿到 idempotency lease 的请求是 owner；后续请求按以下规则处理：

- owner 尚未完成：返回 `in_progress`、owner run id、last committed phase 和 retry-after 建议，不再次调用外部 source/parser。
- owner 已完成且 request fingerprint 相同：返回原 run/result，并标记 `idempotent=true`。
- request fingerprint 不同但显式复用同一 `run_id`：返回 `409 idempotency_conflict`。
- lease 超时：recovery 先判断是否有可恢复 commit marker，不能直接抢占并重跑；只有确认 owner 已失效后才允许新 attempt。

## 33. Parser Quality Profile 与降级判定

### 33.1 质量档位

v1 定义三个可配置但版本化的 profile：

| profile | 适用场景 | 最低要求 | 失败后的结果 |
| --- | --- | --- | --- |
| `metadata` | 仅建立论文身份和基础 Catalog | title、至少一个作者或 external id、source snapshot | `metadata_only` |
| `reading` | 阅读、RAG、章节浏览 | title/abstract、正文字符数、section、locator 基础覆盖 | `degraded` 或 `failed` |
| `catalog` | benchmark/Catalog 投影 | `reading` 全部要求，加 table/caption/score evidence 和 identity refs | `catalog_partial`，不能 verified |

profile 的实际阈值必须写入 quality report，不允许只保存 profile 名称。默认阈值来源于 parser settings，可通过环境和 source type 覆盖，但每次 run 保存最终快照。

### 33.2 推荐默认阈值

| 指标 | `metadata` | `reading` | `catalog` |
| --- | ---: | ---: | ---: |
| title presence | 必须 | 必须 | 必须 |
| abstract | 可选 | 建议，缺失需诊断 | 建议，缺失需诊断 |
| body chars | 0 | >= 3,000 | >= 3,000 |
| sections | 0 | >= 3 | >= 3 |
| non-empty section ratio | 0 | >= 0.80 | >= 0.80 |
| replacement char ratio | 不适用 | <= 0.02 | <= 0.02 |
| locator coverage | metadata locator | >= 0.80 | >= 0.90 |
| tables with rows | 不适用 | 若检测到表格则 >= 0.50 | 若有 benchmark table 则 1.00 |
| references | 可选 | 可选 | 有引用时必须可定位 |
| evidence for score | 不适用 | 可选 | 每个 verified score 必须有 |

这些阈值不是“论文必须包含表格或公式”的要求；没有表格的论文可以通过 `reading`，但不能把缺失的 benchmark 结构伪造出来。

### 33.3 Quality score

quality score 使用版本化确定性公式：

```text
quality_score = 0.25 * structure_score
              + 0.25 * text_score
              + 0.20 * locator_score
              + 0.15 * element_score
              + 0.15 * integrity_score
```

每个子分数范围为 `[0, 1]`，缺失维度按 profile 语义计算而不是自动算满分。报告必须同时保存各子分数、权重、公式版本和未满足阈值；总分不能替代硬阈值检查。

### 33.4 Parser cascade 规则

- parser 优先级由 `parser_profile` 固定，例如 `mineru -> marker -> pymupdf`；不能由 LLM 动态改变。
- 每个 backend 最多一次主 attempt；允许的 retry 由 provider policy 单独计数，不能无限重试同一 parser。
- 任何 backend 完成后都先执行 quality probe，再决定是否选中或 fallback。
- 首个 backend 质量拒绝时，必须保留其 document summary 或 failure diagnostics，不能只记录“使用了第二个 parser”。
- 所有结构化 backend 不可用时，可以使用 PyMuPDF terminal fallback，但结果必须是 `degraded`，且 `attempts` 中有 `unavailable`/`fallback`。
- Docker provider 不可用时不允许退回 host subprocess；只有显式配置的安全 in-process parser 才能作为 fallback。

### 33.5 LaTeX/archive 安全边界

LaTeX archive 解包必须限制：最大压缩层数、最大文件数、单文件大小、解压后总大小、路径深度、符号链接和硬链接。禁止执行 `\input` 指向 allowlist 之外的路径，禁止把 `.sty`、shell escape 或编译命令当作可信代码执行。

解析失败必须区分：`archive_invalid`、`archive_size_exceeded`、`path_escape`、`compile_timeout`、`missing_entrypoint` 和 `unsupported_tex_feature`。

## 34. Score Normalization、Protocol Signature 与 Ranking

### 34.1 原始值与规范化值

每个 score 同时保留：

- `raw_display_value`：论文表格或正文原样显示，例如 `89.2%`、`0.892`、`84.3 +/- 0.3`；
- `normalized_value`：可比较的确定性数值；
- `unit`、`unit_conversion`、`rounding_mode` 和 `normalization_version`；
- `uncertainty`、`sample_count`、`seed_count`（若论文提供）；
- 表头、行名、列名、caption、脚注和 source locator；
- `best_marker`/`baseline_marker` 等展示信息。

规范化规则：

- 百分比必须保存原始 `%`，只有在 metric contract 明确时才转换为 `[0,1]`；
- `89.2%` 与 `0.892` 不得在没有 metric unit contract 时自动合并；
- `84.3 +/- 0.3` 的中心值和不确定性分开存储，不能把 `84.6` 当成 score；
- `N/A`、`-`、区间和文字“best”只能保持 candidate/observation，不生成数值 score；
- 加粗或颜色只表示 presentation marker，不表示 verified 或 SOTA。

### 34.2 Protocol fingerprint

`protocol_fingerprint` 至少由以下规范化字段计算：

```text
benchmark_id | dataset_id | dataset_version | split |
metric_id | metric_definition_version | direction | unit |
preprocessing | sample_scope | aggregation | evaluation_code_ref
```

同名 metric 如果 macro/micro、top-1/top-5、single/multi-crop、zero-shot/fine-tuned 或 aggregation 不同，必须生成不同 fingerprint。缺失字段使用 `unknown` 并阻止 verified comparison，而不是填默认值。

### 34.3 Multiple observations、seed 和 checkpoint

同一论文和协议下的多个 seed、checkpoint、run 或 report 是独立 observations：

- 原始 observation 全部保留；
- 若论文明确给出 aggregate，则另建 aggregate score 并关联 constituent refs；
- 没有明确选择规则时不能默默取最大值；
- leaderboard 默认只显示有明确 protocol 和 selection policy 的 verified score；
- checkpoint 名称、发布日期和 observed_at 必须与 score 关联，避免最新 checkpoint 覆盖发表时结果。

### 34.4 排名规则

leaderboard group 使用 `protocol_fingerprint` 分组。组内排名使用 dense rank：相同 normalized value 共享 rank，下一名按不同值数量递增。若产品只需要稳定展示顺序，响应仍必须同时返回 `rank` 和 `tie_group`，不让客户端自行猜测。

同分时不使用 source authority 破坏并列排名；`observed_at` 和 stable `score_id` 只用于组内展示顺序和可重复排序。

### 34.5 Baseline、SOTA 和榜首

- baseline 是 score 的比较对象，不自动成为 leaderboard entry。
- SOTA claim 是论文或来源的 claim，不等于当前榜首；需要关联 score、protocol 和 evidence 才能 verified。
- 当前榜首由某个 leaderboard snapshot 的 verified scores 计算，不回写或修改历史 `ResearchSOTAClaim`。
- 人工确认必须记录 reviewer actor、确认时间、confirmation evidence、撤销时间（如有）和 decision reason。

## 35. GitHub Observation Policy 与生命周期

### 35.1 Observation schema

每个 repository signal 使用以下结构，而不是裸布尔值：

```json
{
  "signal": "install",
  "status": "observed",
  "detection_rule": "requirements-file@v1",
  "matched_refs": ["artifact://..."],
  "observed_at": "2026-08-31T00:00:00Z",
  "commit_sha": "...",
  "branch": "main",
  "source_snapshot_id": "snapshot://..."
}
```

`status` 允许 `observed`、`not_observed`、`unavailable`、`denied` 和 `unsupported`。`not_observed` 只表示在允许的范围内没发现，不表示仓库一定不存在该能力。

### 35.2 读取 allowlist 和预算

v1 默认最多读取 64 个 metadata 文件、单文件 256 KiB、总响应 4 MiB、目录深度 3。允许路径包括 README、LICENSE、依赖声明和 examples/training/inference/checkpoint 的目录项；`.github/workflows`、`.env`、secrets、二进制模型、notebook output 和任意脚本内容默认拒绝。

每个 observation 保存实际读取 path、response size、content hash、redaction version 和 GitHub API request id。公开 API 默认只返回 signal 状态、规则版本和 artifact ref，不返回完整 README 或源代码。

### 35.3 Refresh/TTL

- repository profile 的 `observed_at` 与论文 snapshot 时间分开；不能把当前 GitHub main 当成论文发表时状态。
- branch 删除、commit 不存在、release 被撤回、私有仓库和 API 429 都保留历史 observation，并创建新的 unavailable/denied snapshot。
- refresh 默认追加 observation；不会删除旧 commit 或把旧 signal 改成当前值。
- TTL 只影响是否建议 refresh，不影响历史数据可查询性。

### 35.4 复现语义

以下字段在 v1 中禁止出现或不能被自动设置为 true：`runnable`、`reproduced`、`training_succeeded`、`inference_succeeded`。如果未来增加这些字段，必须由独立、受控、人工授权的 execution workflow 产生，而不是由 README/requirements 观察推断。

## 36. Filesystem Store Schema、迁移与保留

### 36.1 逻辑记录

每条 filesystem record 至少有：`schema_version`、`record_type`、`record_id`、`scope`、`parent_refs`、`content_hash`、`created_at`、`observed_at`、`lineage` 和 `status`。scope key 默认使用稳定 hash，human-readable tenant/user 名称不能直接进入目录名或 artifact ref。

### 36.2 写入和锁

1. 生成 record 和 checksum，在同目录写入临时文件。
2. 写入后执行 fsync，再使用 atomic rename；Windows 下要处理目标存在、文件句柄和重试。
3. 更新 index 前先写 commit marker；index 只能引用已提交 record。
4. 同一个 paper/snapshot/run aggregate 使用同一 lock key；不同 paper 可以并行。
5. append-only JSONL 事件使用文件锁和单调 sequence；检测到 sequence gap 时读操作进入诊断模式。

### 36.3 Schema migration

- 读取器至少支持当前写入版本和一个回滚版本；不支持版本返回 `schema_version_unsupported`。
- migration 必须是可重复执行的 deterministic transform，并写 migration event、source version、target version 和 checksum。
- migration 不覆盖原始 snapshot；旧 record 通过 `superseded_by` 指向新 record。
- 未知字段默认拒绝静默丢弃；向后兼容字段必须在 schema 中显式声明。
- migration 失败时保留旧版本可读，新版本 quarantined；不能把半迁移 record 发布到 Catalog。

### 36.4 Orphan、corruption 和 retention

- orphan sweep 只能处理没有 committed marker、没有 active run 引用且超过 retention grace period 的 artifact。
- checksum mismatch、JSON decode failure、scope mismatch 或 parent ref 缺失时进入 read-only/quarantine，不自动重建历史事实。
- 默认保留所有 source snapshot、document、evidence、score 和 event；只允许 operator 按 policy 创建 tombstone。
- tombstone 不删除 event lineage；查询返回 `redacted/tombstoned` 状态，禁止通过旧 ref 重新下载内容。

### 36.5 Backup/export/import

backup 必须包含 records、artifacts、indexes、schema files、migration manifest 和 checksum manifest。restore 后先执行 offline integrity scan，再开放 query。导出按 scope 和 redaction policy 过滤，可选择只导出 metadata/provenance，不默认携带完整 PDF、README 或代码原文。

## 37. HTTP JSON Contract 示例与接口细节

### 37.1 Parsed response

```json
{
  "success": true,
  "data": {
    "paper_id": "paper_01",
    "identity": {
      "canonical_title": "Attention Is All You Need",
      "arxiv_id": "1706.03762",
      "versions": ["v1", "v2"]
    },
    "document": {
      "document_ref": "artifact://document/doc_01",
      "status": "parsed",
      "sections_count": 12,
      "figures_count": 8,
      "tables_count": 5,
      "equations_count": 19,
      "references_count": 41
    },
    "catalog": {"status": "catalog_partial", "candidate_count": 7, "verified_count": 0}
  },
  "error": null,
  "request_id": "req_01",
  "run_id": "run_01",
  "status": "catalog_partial",
  "provenance": {
    "source_snapshot_refs": ["snapshot://snap_01"],
    "artifact_refs": ["artifact://document/doc_01", "artifact://evidence/pack_01"],
    "observed_at": "2026-08-31T00:00:00Z"
  },
  "diagnostics": [{"code": "score_evidence_missing", "severity": "info"}],
  "schema_version": "research.paper.v1"
}
```

### 37.2 Metadata-only response

```json
{
  "success": true,
  "data": {
    "paper_id": "paper_02",
    "identity": {"doi": "10.1000/example"},
    "document": null,
    "catalog": {"status": "catalog_partial", "candidate_count": 2, "verified_count": 0}
  },
  "error": null,
  "request_id": "req_02",
  "run_id": "run_02",
  "status": "metadata_only",
  "provenance": {"source_snapshot_refs": ["snapshot://snap_02"], "artifact_refs": []},
  "diagnostics": [{"code": "publisher_login_required", "retryable": false}],
  "schema_version": "research.paper.v1"
}
```

### 37.3 Catalog response with mixed relation states

```json
{
  "success": true,
  "data": {
    "paper_id": "paper_01",
    "relations": [
      {"relation_id": "rel_1", "type": "paper_method", "status": "verified", "target_id": "method_transformer", "evidence_refs": ["evidence://e1"]},
      {"relation_id": "rel_2", "type": "paper_benchmark", "status": "candidate", "target_id": "benchmark_wmt14", "diagnostics": ["protocol_missing"]},
      {"relation_id": "rel_3", "type": "paper_score", "status": "conflicting", "target_id": "score_3", "diagnostics": ["multiple_values_same_protocol"]}
    ],
    "counts": {"verified": 1, "candidate": 1, "conflicting": 1, "rejected": 0}
  },
  "error": null,
  "request_id": "req_03",
  "status": "catalog_partial",
  "schema_version": "research.catalog.v1"
}
```

### 37.4 Leaderboard response with exclusions

```json
{
  "success": true,
  "data": {
    "groups": [
      {
        "group_key": "benchmark_wmt14:dataset_en-de:v1:bleu:test:protocol_a",
        "direction": "higher_is_better",
        "included_scores": [
          {"score_id": "score_verified_1", "rank": 1, "value": 29.8, "unit": "BLEU"}
        ],
        "excluded_scores": [
          {"score_id": "score_candidate_1", "reason_codes": ["candidate_status"]},
          {"score_id": "score_incompatible_1", "reason_codes": ["split_mismatch"]}
        ]
      }
    ],
    "snapshot_observed_at": "2026-08-31T00:00:00Z"
  },
  "error": null,
  "request_id": "req_04",
  "status": "catalog_ready",
  "schema_version": "research.leaderboard.v1"
}
```

### 37.5 Parse request options

`options` 只允许以下键：`parser_backend`、`quality_profile`、`refresh`、`include_code`、`include_catalog`、`include_chunks`、`include_evidence`、`max_attempts` 和 `timeout_seconds`。未知键返回 `400 invalid_request`；数值必须在 settings 的上限内。

`source`、`source_url`、`content_ref` 的规则：

- `source` 是统一 descriptor，可包含 URL/id/type；
- `source_url` 只是兼容字段，不能与 `source` 产生不同值；
- `content_ref` 可以和 source 同时提供，用于声明“source metadata + 已上传正文”；
- content ref 的内容优先用于 parsing，但 source snapshot 仍记录 source metadata 和内容 lineage；
- caller metadata 永远不能覆盖 source adapter 返回的权威 metadata。

### 37.6 HTTP status 和错误表

| error code | HTTP | retryable | user action |
| --- | ---: | ---: | --- |
| `invalid_request` | 400 | 否 | 修正字段 |
| `source_not_found` | 404 | 否 | 检查 URL/id |
| `source_denied` | 403 | 否 | 请求授权或换来源 |
| `scope_forbidden` | 403 | 否 | 使用授权 scope |
| `idempotency_conflict` | 409 | 否 | 使用新 key 或查询原 run |
| `identity_conflict` | 409 | 否 | 人工确认或补来源 |
| `source_rate_limited` | 429 | 是 | 按 retry-after 重试 |
| `source_timeout` | 504 | 是 | 稍后重试 |
| `unsupported_format` | 415 | 否 | 提供支持格式 |
| `artifact_too_large` | 413 | 否 | 缩小输入 |
| `parser_quality_rejected` | 422 | 否 | 更换 source/parser 或人工复核 |
| `metric_incompatible` | 422 | 否 | 指定兼容 protocol |
| `artifact_missing` | 404 | 否 | 重新 refresh |
| `store_corrupt` | 503 | 否 | operator restore/quarantine |
| `research_runtime_unavailable` | 503 | 是或否，按 capability | 配置 runtime |

`metadata_only`、`degraded`、`catalog_partial` 不是错误 code；它们使用成功 envelope 返回业务状态和 diagnostics。`failed` 只有在本次 run 没有可交付结果或最终持久化失败时使用。

### 37.7 分页、排序和 artifact 展开

- `limit` 默认 50，最大 200；超限返回 `400 invalid_request`。
- `cursor` 是不透明 token，绑定 query fingerprint、scope fingerprint、schema version 和 sort key；变化后返回 `invalid_cursor`。
- 默认 sort 是 `observed_at desc, stable_id asc`；任何其他排序字段必须在白名单中。
- `include_diagnostics=false` 默认只返回摘要；详细 diagnostics 需要角色权限。
- `artifact_refs` 默认只返回 metadata/ref/checksum；原文展开使用独立授权 endpoint，并再次执行 scope、size、redaction 和 expiry 校验。

## 38. Authorization、Artifact Access 与审计

### 38.1 操作权限

| permission | 操作 |
| --- | --- |
| `research.paper.parse` | 单篇 parse |
| `research.paper.ingest` | 批量 ingest |
| `research.paper.refresh` | source/document/catalog refresh |
| `research.catalog.read` | Catalog、relation、score 查询 |
| `research.catalog.verify` | 人工确认 relation/score/SOTA |
| `research.catalog.export` | 导出 Catalog/artifact |
| `research.diagnostics.read` | 查看详细 diagnostics/trace |
| `research.artifact.read` | 展开受控 artifact |
| `research.event.replay` | replay/recovery/operator 读取 |

未认证或 scope 不可见的 paper 默认返回 `404`，避免资源枚举；已认证但无写权限的 refresh/verify 返回 `403`，并写 audit event。

### 38.2 Artifact access policy

- artifact ref 不是永久公开 URL，必须在读取时解析 scope、permission、expiry 和 redaction policy。
- 默认返回 artifact metadata，不返回完整 PDF、README、代码或 prompt。
- 原文片段、quote 和导出内容受最大字符数和版权策略限制；超限返回 truncated 诊断而不是静默扩大响应。
- range download 只有明确授权的 internal/operator client 可用；每个 range 请求重新校验 scope。
- revocation/deletion 使用 tombstone 和 audit event；旧 ref 不可绕过 tombstone 读取。

### 38.3 Audit event

每次 parse、refresh、manual verify、export、artifact read、scope denial、quarantine 和 restore 至少记录：

`audit_id`、`actor_id`、`permission`、`action`、`resource_type`、`resource_id`、`scope_ref`、`decision`、`reason_code`、`request_id`、`run_id`、`correlation_id` 和 `occurred_at`。

audit event 不包含 secret、prompt、完整 source body 或未脱敏 token；它和业务 event 分开存储，但必须能通过 correlation id 关联。

## 39. Runtime Profiles 与外部依赖

### 39.1 环境矩阵

| profile | 必需依赖 | 可运行功能 | 不应发生的连接 |
| --- | --- | --- | --- |
| `unit_contract` | `.venv`、filesystem、SQLite | domain/application/contract/architecture tests | arXiv、LLM、Postgres、Redis、Qdrant、Docker |
| `local_parse` | `PyMuPDF`，可选本地 LaTeX/HTML fixture | local artifact parse、quality、Catalog candidate | 第三方网络，除非显式 source |
| `docker_pdf` | Docker Desktop、镜像、GPU/模型（按 backend） | MinerU/Marker/Nougat structured PDF | Redis/Postgres/Qdrant 默认不需要 |
| `postgres_durable` | PostgreSQL + migrations | durable event/storage integration | 不应隐式启用 Redis |
| `qdrant_rag` | Qdrant + embedding provider | vector chunk retrieval | 不应隐式改变 Catalog truth |
| `redis_worker` | dedicated Redis URL | queue/scheduler/cache integration | 不应成为 parse v1 的隐式依赖 |
| `live_e2e` | source network、LLM key、可选 Postgres/Qdrant | real arXiv/GitHub/publisher/RAG E2E | 未声明 host/private network |

### 39.2 依赖选择规则

- 固定 `compile/test/smoke` 必须在没有 Docker、Postgres、Redis、Qdrant 和外网时可运行；真实 live 测试使用显式 marker 和 env opt-in。
- `NEWS_DATABASE_DSN` 非空才选择 PostgreSQL；为空时使用 SQLite/filesystem fallback。配置存在不等于必须连接，只有选中的 adapter 才能建立连接。
- `NEWS_RESEARCH_RAG_BACKEND=local` 时不初始化 Qdrant client；`qdrant` 模式不可用时 fail closed，不偷偷改为 local 并声称同等结果。
- LLM cache 默认 disabled；启用 Redis cache 时使用独立 cache URL/ACL，不复用 durable event Redis。
- Docker-backed parser 的 provider capability 在 composition 阶段 probe；不可用时返回 typed `research_runtime_unavailable` 或 parser degraded，不执行 host subprocess。

### 39.3 运行预算

单次同步 parse 必须受以下预算限制：最大 wall-clock、source metadata/package bytes、archive unpack bytes/files、parser attempts、单 backend timeout、artifact bytes、chunk count 和 LLM worker calls。预算快照写入 run intent 和 final diagnostics；预算耗尽返回明确 `budget_exhausted`，不无限重试。

## 40. Test Matrix 与 Definition of Done

### 40.1 需求到测试追踪矩阵

| 需求域 | fixture/test | 测试层级 | 确定性 oracle | 外部依赖 |
| --- | --- | --- | --- | --- |
| source normalization | `source_descriptor_variants` | unit/contract | canonical URL/id 一致 | 无 |
| identity merge | `multi_source_same_paper` | application/integration | 一个 identity，多 snapshot，多 provenance | fake adapters |
| version separation | `arxiv_v1_v2` | domain/integration | 不覆盖旧 checksum | filesystem |
| metadata-only | `publisher_denied` | application/API | status + denial reason | fake adapter |
| SSRF/path safety | `redirect_private_ip`, `zip_path_escape` | security | 请求被拒绝且无 artifact | fake network/files |
| parser fallback | `pdf_cascade_quality` | unit/application | all attempts + selected backend | fake parser |
| parser corruption | `empty/garbled/no_locator` | quality | degraded/quarantine，不是 parsed | local fixture |
| document structure | `latex_complex` | integration | elements/locators/hash 完整 | local filesystem |
| chunk/evidence | `document_projection` | application | parent refs、stale_of、evidence closure | fake stores |
| idempotency | `duplicate_concurrent_ingest` | integration | no duplicate facts/artifacts | filesystem locks |
| recovery | `failure_at_each_commit_point` | integration | replay 后无虚假 catalog_ready | filesystem |
| Catalog relations | `catalog_mixed_statuses` | domain/API | typed relations + status counts | no |
| score normalization | `percent_decimal_uncertainty` | unit | raw/normalized/uncertainty 分离 | no |
| benchmark gate | `candidate_conflicting_verified` | unit/application | only verified compatible in leaderboard | no |
| SOTA completeness | `incomplete_sota_claim` | unit | candidate retained, missing refs diagnostics | no |
| GitHub signals | `github_multiple_repositories` | adapter/application | observations + commit/source refs | fake GitHub |
| API contract | `parse_response_snapshots` | API contract | JSON fields/status/error stable | TestClient |
| CLI parity | `cli_api_same_request` | interface | semantic fields equal | local |
| actor isolation | `two_tenant_same_doi` | security/integration | 404/403、不能 merge/互读 | filesystem |
| artifact access | `artifact_scope_revoked` | security | second scope check/tombstone | filesystem |
| architecture | import graph checks | architecture | no direct parser/store bypass | no |
| runtime profiles | `offline/live` | smoke/live | offline no external connect；live explicit | optional |

### 40.2 负例必须覆盖

- 相同 idempotency key 并发、source checksum 变化、refresh 与 ingest 竞态；
- title 相同但作者不同、多 identity 命中、DOI typo、arXiv version、OpenReview revision/withdrawn；
- redirect 到 loopback/private/link-local/metadata IP、伪造 MIME、超大 response、zip bomb、符号链接逃逸；
- event append 在每个 commit point 失败、artifact checksum mismatch、schema version unsupported、manifest 丢失和 orphan sweep；
- parser 有文本无 locator、乱码、空文档、表格无行、score 无单位或 protocol；
- percent/decimal、同 metric 不同定义、多个 seed/checkpoint、同分和人工确认撤销；
- GitHub private/429/missing README/branch deleted/commit unavailable；
- API/CLI snapshot 漂移、未知 options、cursor 失效、scope 伪造和敏感信息泄漏。

### 40.3 Definition of Done

本变更只有同时满足以下条件才可标记完成：

1. `tasks.md` 中所有 contract、parse、Catalog、interfaces 和 verification 项目都有实现和测试证据。
2. `ParsePaperUseCase` 是唯一论文 ingest application contract，API/CLI 不绕过 application service。
3. source、identity、document、attempt、quality、chunk、evidence、relation、score、code observation、run/event 均可持久化、查询和回溯。
4. candidate-first、evidence/lineage/scope/protocol gates 和 leaderboard exclusion 已有 deterministic tests。
5. refresh、retry、recovery、duplicate、scope isolation、corruption 和 quarantine 具有可重放验证。
6. offline profile 在无外部服务时通过核心 contract、architecture 和 smoke；live profile 具备显式前置检查与失败诊断。
7. `frontend` 无文件变更，`backend/research` 无 legacy `paper_radar`、旧 `interfaces` 或具体 `infrastructure` 依赖。
8. OpenAPI、CLI help、JSON schema、artifact schema、migration manifest 和 fixture 字段一致。
9. 使用项目 `.venv` 运行 compile、test、smoke 和 strict OpenSpec validation，并记录耗时、结果、跳过项和残余风险。
10. 未验证的 candidate、conflicting score、LLM 生成内容、GitHub observation 和 source metadata 不会被公开 API 误报为 verified fact。

## 41. 输入 Descriptor、字段所有权与规范化细则

本节把第 9、10 和 37 节的原则收敛为可直接实现和测试的输入契约。HTTP、CLI、SDK 和 future scheduler 都必须先映射为同一个 `ParsePaperRequest`；不得分别维护不一致的 URL、source type 或 actor scope 解释。

### 41.1 Canonical source descriptor

`source` 是论文来源的主描述符。v1 接受字符串形式，SDK/内部调用可先使用对象形式，最终必须规范化成以下逻辑字段：

| 字段 | 是否必填 | 规则 | 归属 |
| --- | --- | --- | --- |
| `source` | 是 | 非空；URL、外部 id 或受控 local descriptor | 调用方提供，resolver 规范化 |
| `source_type` | 否 | 只能是 `arxiv`、`openreview`、`doi`、`crossref`、`publisher`、`local`、`github`、`manual`、`other` | 调用方可提示，resolver 记录最终判断 |
| `source_url` | 否 | 仅兼容字段；与 `source` 同时存在时规范化后必须等价 | 调用方提供，application 校验 |
| `content_ref` | 否 | 已授权正文 artifact 或受控 local 文件；不可作为公网任意下载 URL | 调用方提供，artifact/local adapter 授权 |
| `run_id` | 否 | 安全的 opaque id；同 scope 内不可映射到不同 request fingerprint | 调用方提供或 application 生成 |
| `options` | 否 | 仅接受第 37.5 节 allowlist；未知键为 `invalid_request` | application 校验 |
| `metadata` | 否 | 提示性字段，不得覆盖 adapter 的权威事实 | 调用方提供，必须标记 lineage |

规范化顺序固定如下：

1. 去除首尾空白，拒绝空值、控制字符、用户名密码嵌入 URL 和不合法端口。
2. 对 HTTPS URL 做 scheme/host 小写化、默认端口消除、fragment 移除和稳定 query 规范化；不得移除承载 OpenReview note id 的 query。
3. 对 DOI、arXiv、OpenReview 先抽取标准 external id，再保留原输入为 lineage。`arxiv:2606.00001v2`、`https://arxiv.org/abs/2606.00001v2` 和受支持的 PDF URL 必须解析出同一个版本 id。
4. 对 local path 和 `file://` URI 解析真实路径后检查 allowed root、符号链接和大小；持久化记录不得泄露绝对路径。
5. 对 `content_ref` 执行独立 scope、expiry、checksum、content type 和最大大小校验。它用于正文时，source descriptor 仍作为 metadata/source lineage 保留。
6. source adapter 返回的 canonical URL、external id、content type、checksum 和 access result 是权威观察；caller metadata 同名字段只可作为 `caller_hint` 保存，不能静默覆盖。

以下组合必须返回稳定错误，而不是猜测用户意图：

| 输入组合 | 结果 |
| --- | --- |
| `source` 与 `source_url` 规范化后不同 | `400 invalid_request`，返回字段名但不回显敏感 query |
| 远程 `http://` 来源 | `400 invalid_request` 或 `source_denied`，v1 不降级为明文 fetch |
| `github` 且没有 paper context | `422 github_paper_context_required` |
| `content_ref` 指向 scope 外、过期或 tombstoned artifact | `404 artifact_missing`，不泄露存在性 |
| local path 在 allowed root 外或符号链接逃逸 | `403 source_denied`，不回显真实路径 |
| 同时给出 source metadata 与正文 contentRef | 合法；contentRef 作为 parsing body，source 仍生成独立 snapshot 和 lineage |

### 41.2 Caller metadata 的可信度分层

`metadata` 不等于论文事实。每个进入持久化的字段必须有以下之一的 `value_origin`：

| `value_origin` | 含义 | 是否能作为 identity/verified 依据 |
| --- | --- | --- |
| `source_adapter` | arXiv、DOI、OpenReview、publisher 或 GitHub adapter 的受控观察 | 可以，仍需 provenance gate |
| `document_parser` | 已保存 document 中带 locator 的确定性提取 | 可以，仍需 evidence/protocol gate |
| `manual_review` | 授权人工确认，带 reviewer 和 evidence | 可以，按 review policy |
| `caller_hint` | 用户提交的 title、authors、code URL 等提示 | 不可以单独作为 verified 依据 |
| `llm_candidate` | LLM 生成的实体映射、taxonomy 或 claim | 不可以单独作为 verified 依据 |
| `migration` | 历史数据 deterministic transform | 仅在原事实来源与 checksum 可追溯时可用 |

同一个逻辑字段出现多个值时，identity 和 document projection 必须保留全部 `FieldObservation`，至少包含：`field_name`、`normalized_value`、`raw_value_ref`、`value_origin`、`source_snapshot_ref`、`observed_at`、`confidence`、`conflict_group_id`。对外默认展示 canonical 值和冲突摘要；具备 `research.diagnostics.read` 权限的用户可查看各候选值和 provenance。

### 41.3 Content type、大小和正文选择

source adapter 必须区分 HTTP 声明类型、magic bytes、文件扩展名和实际 parser 输入格式：

| 情况 | 处理 |
| --- | --- |
| header 与 magic bytes 一致 | 使用受支持的格式路由 |
| header 错误但 magic bytes 可识别且 policy 允许 | 记录 `content_type_mismatch`，按 magic bytes 路由 |
| HTML 冒充 PDF、PDF 冒充 LaTeX 或无法识别二进制 | 不得交给任意 parser 猜测；返回 `unsupported_format` 或 `metadata_only` |
| 响应超过 source budget | 停止读取，保留 metadata snapshot，返回 `artifact_too_large`/`metadata_only` |
| `content_ref` 与 remote source checksum 不同 | 两者生成独立 observation；不得覆盖 remote snapshot |
| remote source 重定向到不同 host | 对每一跳执行 HTTPS、public-address、robots、size 和 allowlist 校验，并记录 redirect lineage |

当同一 request 同时拥有 LaTeX、PDF 和 HTML 时，正文选择必须写入 `selected_content_ref`、`selection_rule_version` 和所有候选 snapshot refs。默认优先级为：安全且完整的 LaTeX source、质量合格的 PDF、可定位的 HTML、metadata-only。这个顺序不是质量成功的保证，最终 document status 仍由第 33 节的 deterministic quality profile 决定。

## 42. 事实、证据与人工复核的闭包规则

Catalog 的核心不是“能抽取到多少关系”，而是任一对外可见事实都能回答四个问题：它来自哪里、指向正文的哪一处、谁/什么规则决定其状态、该决定在何时基于哪个版本成立。本节定义最小闭包。

### 42.1 Evidence locator contract

任意 `evidence_ref` 指向的可验证对象至少要能解析出以下字段：

| 字段 | 说明 |
| --- | --- |
| `evidence_id` | 稳定 id，不能随展示文本变化 |
| `source_snapshot_ref` | 产生该证据的不可变 source observation |
| `document_id` 或 `repository_observation_ref` | 论文正文或 GitHub observation 的父对象 |
| `element_ref` | section、table、figure、equation、reference、metadata field 或 repository path |
| `locator` | page/bbox、LaTeX file+line、HTML anchor、表格 cell、GitHub path+commit 等可定位信息 |
| `content_hash` | 所定位内容或规范化片段的 checksum |
| `quote_or_span` | 受版权和输出策略限制的短引用或字符范围；不要求公开全文 |
| `extraction_rule` | deterministic parser/rule 或候选 worker 的版本 |
| `observed_at` | 该证据被观察或解析的时间 |
| `actor_scope` | 读取该证据时必须再次执行的隔离边界 |

evidence 失效不是删除历史。source refresh 后，旧 evidence 保留其旧 snapshot，新的 evidence 通过 `supersedes`/`stale_of` 关联。若 artifact checksum 不再匹配或 parent ref 丢失，evidence 进入 `quarantined`，所有依赖它的 verified relation/score/claim 必须在查询时降为不可验证，且 leaderboard 从当前快照排除。

### 42.2 各类事实的最低闭包

| 事实类型 | Candidate 最低要求 | Verified 额外要求 | 禁止的自动推断 |
| --- | --- | --- | --- |
| `paper_task` | paper、标准化 task 文本、source context | task taxonomy identity、evidence、scope/lineage gate | 只根据 title keyword 确认 task |
| `paper_method` | method 名称或候选描述、document/source context | method identity、evidence、method graph edge gate | 将 LLM 命名直接写成 verified method |
| `paper_dataset` | dataset 原文名、source context | dataset identity/version、evidence | 同名数据集自动视为同版本 |
| `paper_benchmark` | benchmark 名称或表格上下文 | benchmark/dataset/split/evidence | 把数据集名自动等同 benchmark |
| `paper_metric` | metric 原文名、表头/正文 context | metric definition/direction/unit/evidence | `accuracy` 自动等同任意 Accuracy 定义 |
| `paper_score` | raw display value、表格或正文 context | 第 34 节 protocol fingerprint、数值/单位、evidence、compatibility gate | `best`、粗体或最大值自动变为 SOTA |
| `paper_code_repository` | 规范化 repo URL 或 repository observation | canonical repo id、paper alignment evidence、scope gate | README 相似或同 owner 自动证明代码对应论文 |
| `sota_claim` | 原文 claim 和 source context | score、benchmark、dataset、metric、protocol、evidence 和 verified decision | 论文自称 SOTA 自动成为榜首 |

被拒绝的 candidate 必须保留 `rejection_reason_code`；相互冲突的候选必须保留 `conflict_set_id` 和各 observation，不得只保留最近一条。查询 API 的 `counts` 必须分别计数 `candidate`、`verified`、`rejected`、`conflicting` 和 `quarantined`，避免客户端把“未列出”误解为“不存在”。

### 42.3 人工 verify、reject、revoke 工作流

人工操作是受控事实决策，不是修改任意 metadata。v1 的 application contract 必须为 future HTTP/CLI verify 操作保留如下命令语义，即使初始界面尚未开放：

```text
CatalogReviewCommand
  target_type: relation | score | sota_claim | method_graph_edge
  target_id: stable target id
  decision: verify | reject | mark_conflicting | revoke_verification
  expected_revision: optimistic concurrency revision
  evidence_refs: non-empty for verify
  reason_code: controlled taxonomy value
  note_ref: optional redacted operator note artifact
  actor_scope: authentication-derived only
```

决策规则：

1. `verify` 必须具有 `research.catalog.verify` 权限、非空 evidence refs、当前 scope 可见的父对象和通过 schema/protocol gate 的目标。
2. `reject` 和 `mark_conflicting` 必须保留候选及原 evidence，只追加 decision event；不能删除不利证据。
3. `revoke_verification` 生成新 revision，记录撤销人、撤销时间、原因和替代 evidence（若有）；历史 leaderboard snapshot 不重写，但新的 snapshot 不再纳入该 score。
4. `expected_revision` 不匹配返回 `409 catalog_relation_conflict`，避免两位 reviewer 静默覆盖决策。
5. 用户提交的自由文本 note 只能进入受控、可脱敏 artifact；它不构成 evidence，除非同时附有可解析的 evidence ref。

每个 decision 产生独立 audit event 和业务 event，字段至少为：`review_id`、`target_id`、`decision`、`previous_status`、`new_status`、`reviewer_actor_id`、`permission`、`evidence_refs`、`reason_code`、`occurred_at`、`run_id`/`correlation_id` 和 `actor_scope`。LLM 只能建议 review queue priority，不能写入 decision。

### 42.4 Freshness、历史与查询时降级

`observed_at`、`published_at`、`fetched_at`、`parsed_at`、`verified_at` 和 `leaderboard_snapshot_at` 不能互相替代：

| 时间字段 | 语义 |
| --- | --- |
| `published_at` | 论文/版本的外部发表时间 |
| `fetched_at` | source adapter 获取该 snapshot 的时间 |
| `observed_at` | GitHub、网页或其他 observation 被观察的时间 |
| `parsed_at` | document parser 完成该 document 的时间 |
| `verified_at` | deterministic/manual gate 作出 verified 决定的时间 |
| `leaderboard_snapshot_at` | 某次固定筛选和排名产物生成的时间 |

当用户查询“当前” Catalog 时，服务返回最新满足 scope、integrity 和 verification 条件的 revision；当用户以 snapshot/revision 参数查询时，服务返回当时事实和当前 integrity 状态。历史记录损坏时不能伪造历史 payload，应返回可读取的 metadata、`quarantined` 状态和 `store_corrupt` diagnostic。

## 43. 接口行为、诊断分级与批量语义

### 43.1 HTTP envelope 的字段语义

所有 v1 endpoint 的成功和失败响应使用同一顶层骨架。字段不存在和字段值为 `null` 必须有稳定语义：

| 字段 | 成功响应 | 失败响应 | 说明 |
| --- | --- | --- | --- |
| `success` | `true`，包括 `metadata_only`/`degraded`/`catalog_partial` | `false` | 只表示 application call 是否交付业务结果 |
| `status` | 论文/Catalog 业务状态 | `failed` 或适用状态 | 不是 HTTP status 的别名 |
| `data` | 已授权的 typed projection | `null` 或最小可安全交付 projection | 不应回显未授权内容 |
| `error` | `null` | 稳定 error envelope | `message` 不含 stack trace/secret/path |
| `run_id` | 产生或复用 durable run 时必填 | 若在收到 request 后已分配则必填 | client 用于查询/retry，而不是作为权限凭据 |
| `provenance` | source/artifact/evidence 的受控摘要 | 仅可安全披露的 refs/diagnostics | 不默认展开原文 |
| `diagnostics` | 默认摘要 | 默认摘要 | 详细条目需权限和 `include_diagnostics=true` |

`metadata_only`、`degraded` 和 `catalog_partial` 均是成功 envelope，因为用户仍可获得可追溯的部分结果。`failed` 仅表示本次 call 没有可交付结果、需要重试，或最终持久化失败。`200`、`202`、`409`、`422` 等 HTTP code 由接口层按第 37.6 节映射，不得改变 application 的 `status` 语义。

### 43.2 Diagnostic taxonomy

每条 diagnostic 使用以下最小结构：

```json
{
  "code": "source_rate_limited",
  "severity": "warning",
  "phase": "resolving",
  "cause": "remote_policy",
  "impact": "full_text_unavailable",
  "retryable": true,
  "retry_after_seconds": 60,
  "user_action": "retry_later",
  "provenance_refs": ["snapshot://..."],
  "safe_details": {"source_type": "publisher"}
}
```

`severity` 只允许 `info`、`warning`、`error`、`critical`；`user_action` 只允许 `none`、`retry_later`、`supply_alternate_source`、`request_access`、`review_identity`、`review_protocol`、`operator_recovery`。原始异常文本、token、cookie、repository source body、内部绝对路径和 prompt 永远不能进入 `safe_details`。

相同 `code` 在不同 phase 可以有不同 impact，但不得改变其安全语义。例如 `source_denied` 只能说明访问被 policy/authorization 拒绝，不能暴露 publisher 的账号、订阅或 robots 具体规则；`artifact_missing` 对无权限 caller 仍表现为 `404`。

### 43.3 Batch ingest

`paper ingest <source>...` 和对应批量 API 不是一个大事务。每个 source 有自己的 `run_id`、request fingerprint、artifact refs 和结果条目；一个来源失败不得回滚其他来源已提交的 snapshot/document/catalog。

批量结果至少包含：

```json
{
  "request_id": "batch_01",
  "items": [
    {"ordinal": 0, "source": "...", "run_id": "...", "success": true, "status": "catalog_partial"},
    {"ordinal": 1, "source": "...", "run_id": "...", "success": false, "error": {"code": "source_denied"}}
  ],
  "summary": {"total": 2, "succeeded": 1, "degraded": 1, "failed": 1}
}
```

CLI 的退出码以最高严重度为准，但 `--json` 必须完整返回所有 item。建议固定映射：`0` 为全部成功或可交付降级、`2` 为参数错误、`3` 为 scope/permission、`4` 为 source 暂时不可用、`5` 为解析/质量失败、`6` 为 Catalog gate 失败、`7` 为持久化或 recovery 故障。该映射不得让自动化系统把 `metadata_only` 误判为已解析全文。

### 43.4 Pagination、过滤与稳定顺序

Catalog 搜索、source snapshot、relation、score 和 leaderboard 都必须使用同一分页纪律：

1. `limit` 在 `[1, 200]`，默认 `50`；超过范围为 `invalid_request`。
2. cursor 编码 query fingerprint、actor scope fingerprint、schema version、last sort key 和 direction；任何一个不匹配都返回 `invalid_cursor`。
3. 默认稳定顺序为 `observed_at desc, stable_id asc`。leaderboard 先按 rank，再按 `observed_at desc, score_id asc`；稳定排序不改变并列名次。
4. 过滤参数在 application service 解析，白名单之外的字段不得透传到 repository query。
5. scope gate 发生在查询、cursor 解码和 artifact 展开三个阶段，不能只在第一个列表查询时执行。

## 44. 发布、运行配置与运维操作

### 44.1 默认离线运行承诺

本 PRD 的基础闭环必须在 `unit_contract`/`local_parse` profile 下运行，不需要 Docker、PostgreSQL、Redis、Qdrant、LLM key 或公网访问。默认 durable filesystem store 和本地 fixture 足以验证 source normalization、identity、document、quality、Catalog candidate、score gate、actor isolation、artifact checksum 与 event replay。

| 运行目标 | Docker | PostgreSQL | Redis | Qdrant | 网络 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `compile`/`test`/`smoke` | 不需要 | 不需要 | 不需要 | 不需要 | 不需要 | CI 与本地默认门禁 |
| local PDF/LaTeX fixture parse | 可选 | 不需要 | 不需要 | 不需要 | 不需要 | 使用安全 in-process parser/fallback |
| MinerU/Marker 等容器 parser | 需要 | 不需要 | 不需要 | 不需要 | 镜像下载时需要 | 仅 `docker_pdf` profile 显式启用 |
| PostgreSQL durability integration | 不需要 | 需要 | 不需要 | 不需要 | 不需要 | 未来 adapter 验证，不能替代 filesystem contract |
| vector RAG retrieval | 不需要 | 不需要 | 不需要 | 需要 | embedding provider 视配置而定 | 不改变 Catalog truth 状态 |
| async worker/cache | 不需要 | 不需要 | 需要时显式提供 | 不需要 | 按任务 | v1 parse 不隐式依赖 |
| real source E2E | 不需要 | 可选 | 不需要 | 可选 | 需要 | marker/env opt-in，遵循 SSRF/robots policy |

配置缺失的预期是 typed capability error 或 `metadata_only`/`degraded`，绝不应悄悄连接默认 localhost Redis、PostgreSQL 或 Qdrant。Docker parser 未配置时不允许回退到 host shell/subprocess 执行未知命令。

### 44.2 Operator recovery playbook

operator 只通过 application/operator contract 执行下列动作；不得手工编辑 JSON、删除 artifact 或伪造 final event：

| 情况 | 检查 | 允许动作 | 禁止动作 |
| --- | --- | --- | --- |
| owner 尚在运行 | intent、lease、最新 phase event | 返回 `in_progress` 和 retry-after | 抢占 lease、重复 fetch/parser |
| terminal event 存在、final result 缺失 | transcript sequence、artifact marker、scope/checksum | event replay 重建 final projection，记录 recovery correlation | 从 source 重新跑以“修复”final |
| document 已写、artifact marker 缺失 | document/artifact checksum、parent refs | 标记 orphan/quarantine，等待受控重建或人工恢复 | 让 Catalog 引用该 document |
| artifact checksum mismatch | marker 与 payload 的 checksum/scope | `quarantine`、只读诊断、从合法 backup restore | 自动改写历史 checksum |
| schema 不支持 | schema manifest、migration path | 执行版本化 deterministic migration 或返回 unsupported | 丢弃未知字段后继续运行 |
| 已过 retention 的 orphan | active run 引用、grace period、tombstone policy | operator 生成 tombstone/audit | 物理删除 event lineage |

recovery 每次都产生新的 `recovery_run_id`，但原始 events 不可修改。恢复结果应包含 `recovered`、`quarantined` 或 `manual_action_required`，以及 reason code、受影响的 refs、检查时间和 operator identity。只有 final result、terminal event、Catalog projection 和相关 artifact markers 均一致时，恢复操作才能报告 `catalog_ready`。

### 44.3 发布门禁与回滚

发布按 feature flag/capability 分层：

1. 先发布 domain/application contract 和 filesystem adapter，但不让 public API 默认启用 live remote fetch。
2. 在 fixture 和 authorized staging sources 上启用 parse/catalog candidate；验证 event、artifact、scope、idempotency 和 recovery。
3. 单独启用 GitHub observation；确认读取 allowlist、bytes budget 和 redaction 不泄露脚本或 secret。
4. 最后启用对外 API/CLI；verified leaderboard 只有在 deterministic gate 与 review audit 已可用时展示。

回滚只能关闭新 capability 或切回兼容读取器，不能删除 source snapshot、event、artifact marker、candidate 或历史 leaderboard snapshot。若写入 schema 已升级，旧读取器至少能识别并安全拒绝新版本；无法读取时返回 `schema_version_unsupported`，不能把数据当空 Catalog。

## 45. 场景级验收用例

本节把第 40 节的测试矩阵补充为业务可读的 Given/When/Then oracle。每条用例都必须有非网络 fixture 或 fake adapter 版本；live E2E 只能作为补充。

| 编号 | Given | When | Then |
| --- | --- | --- | --- |
| `SRC-01` | 相同论文的 arXiv id、DOI 和 publisher URL，三者 metadata 一致 | 依次 parse | 一个 scope 内只有一个 canonical identity，至少三个 immutable snapshots，identity 的字段 provenance 能列出各 snapshot |
| `SRC-02` | publisher 被 robots/login 拒绝，但 DOI metadata 可读取 | parse publisher | 返回成功 envelope 的 `metadata_only`，document 为 `null`，diagnostic 有 sanitized reason，Catalog 仅可有 candidate |
| `SRC-03` | redirect 指向 loopback/private/link-local 地址 | parse remote source | transport 不发送正文请求，不产生 artifact，返回 source denial/failure diagnostic |
| `ID-01` | 标题相同、年份相近、作者明显不同的两篇论文 | ingest | 不因 title 单独 merge；保留可解释的 identity ambiguity diagnostic |
| `ID-02` | 同一 arXiv paper 的 v1 与 v2 source package | refresh/ingest | identity 关联两个 version/snapshot，旧 source hash/document/chunks 仍可查询 |
| `PARSE-01` | 含 section、figure、table、equation、reference 的 LaTeX fixture | parse | document 含上述 typed elements、locator、source hash 和 parser attempts；artifact 可经 scope/checksum 读取 |
| `PARSE-02` | PDF 第一个 cascade backend 质量失败，第二个合格 | parse | attempt list 保留两个 backend、失败原因和 selected backend；最终状态由 quality profile 决定 |
| `PARSE-03` | 正文不足 3000 字符、locator 覆盖率低 | `quality_profile=reading` | 不返回普通 `parsed`；返回 `degraded` 和每个硬失败的 observed/expected |
| `CAT-01` | 表格中有百分比 score 但缺 split/protocol | catalog refresh | score 保存为 candidate，缺口 diagnostic 可查询，leaderboard `excluded_scores` 含原因 |
| `CAT-02` | 两个 verified score metric 名同但 micro/macro 定义不同 | leaderboard query | 生成不同 protocol fingerprint，不横向 dense rank |
| `CAT-03` | verified SOTA 在 evidence artifact checksum 损坏后不可读取 | leaderboard query | score/claim 保留历史但当前快照排除，返回 integrity diagnostic；不重新宣称 SOTA |
| `CODE-01` | repo 含 README、requirements、examples 目录、training/inference 目录 | code inspect | 返回 typed observed signals、branch/commit/observed_at、path hash/ref；没有 `runnable`/`reproduced` true 字段 |
| `CODE-02` | repo 仅有 `train.py`/`inference.py` 脚本正文 | code inspect | 默认不读取脚本内容；只能根据允许目录或 metadata 产生 `not_observed`/`unsupported`，不泄露脚本文本 |
| `IDEMP-01` | 同 scope、同 run id、同 request fingerprint 的两个并发请求 | 同时 parse | 一个 owner 执行；另一个收到 `in_progress`，owner 完成后重试获得 `idempotent=true` 原结果 |
| `IDEMP-02` | 同 run id、不同 request fingerprint | parse | 返回 `409 idempotency_conflict`，不触发 source/parser |
| `REC-01` | terminal phase event 已写、final result 写入前进程中断 | operator recovery | 只从 event/artifact marker replay final result，不重新 fetch/parser，产生新的 recovery correlation |
| `REC-02` | run 只有 intent/resolving event，未有 terminal evidence | operator recovery | 标为 `quarantined`/`manual_action_required`；相同 run id 后续请求不自动重跑 |
| `SCOPE-01` | tenant A 与 tenant B 提交同一 DOI | parse/query | 可各自保留事实，但 identity/store/artifact/event 不可跨 scope 读取或 merge |
| `API-01` | 未认证或无 scope 的 paper id | GET document/catalog/artifact | 返回 `404` 或授权策略规定的 `403`，不暴露是否存在、checksum 或 source URL |
| `CLI-01` | API 与 CLI 对同一 fixture/source/options 调用 | compare JSON output | `status`、run/paper id、provenance、artifact refs 和 diagnostics 的语义一致，差异只允许 CLI presentation/exit code |

除表中案例外，发布前必须保留第 40.2 节的所有负例测试。任何新增 source adapter、parser backend、metric normalizer 或 repository signal，都要在其 merge request 中新增至少一个成功 fixture、一个降级 fixture 和一个安全/权限负例。
