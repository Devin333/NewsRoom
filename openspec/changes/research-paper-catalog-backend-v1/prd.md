# PRD：Research Paper Intelligence Backend v1

## 产品定位

Research Paper Intelligence Backend 将来自 arXiv、OpenReview、DOI/Crossref、publisher、local artifact 和 GitHub 的论文输入，转换为可追溯的结构化论文文档、证据包以及 Paper-with-Code Catalog。Catalog 采用 Papers with Code 的信息组织方式，将 paper 与 task、method、dataset、benchmark、metric/result 和 code repository 关联，但不依赖 Papers with Code 的实时数据库或 API；事实来源由 Agora Hub 的 source adapter、snapshot 和 provenance 提供。

本 PRD 的文档落点为 `openspec/changes/research-paper-catalog-backend-v1/prd.md`。前端不在本变更范围内，先通过 API、CLI 和 durable artifact 验证后端闭环。

## 用户与核心场景

- 研究人员提交论文 URL、DOI、local PDF 或代码仓库。
- 系统解析标题、作者、摘要、章节、图、表、公式、引用和文本 chunks。
- 系统从正文、表格、代码链接和来源元数据建立任务、方法、数据集、benchmark、metric 和 repository 关系。
- 研究人员查看结构化资料、证据、代码可复现性观察和 benchmark 候选结果。
- 运营人员通过 CLI 批量 ingest、refresh、检查 parser 质量、诊断失败并导出 Catalog。

## 范围与约束

必须交付多来源 identity resolution、source snapshot/provenance、统一 `ParsePaper` application use case、LaTeX/PDF/HTML 分层解析与降级、`ResearchDocument`/chunks/evidence/parser attempts/quality report 持久化、typed Paper-with-Code Catalog、GitHub repository enrichment、benchmark candidate/verified gates、HTTP API、CLI、tenant/user isolation、幂等 ingest、错误诊断和 durable run/event trace。

明确不修改 `frontend`，不重写已有 parser cascade、RAG、arXiv/GitHub connector、Paper Card 或 Reader，不执行第三方代码，不抓取 Papers with Code 实时数据库，不让 LLM 决定路由、质量、排行、发布或 memory write，也不把 Catalog 关系塞入 `ResearchPaper.metadata` 或字符串卡片字段。

## 功能需求

### Source 与论文身份

输入类型为 `arxiv`、`openreview`、`doi`/`crossref`、`publisher`、`local`、`github`。每个输入生成 `ResearchSourceSnapshot`（source type、canonical URL、external id、content type、checksum、fetched_at、访问状态和 lineage）。`ResearchPaperIdentity` 记录 canonical paper id、外部 id、版本和链接。identity merge 只能依据 external id、canonical URL 和可解释的标题/作者/年份指纹；版本不同保留独立 snapshot。字段冲突必须记录 diagnostics 和 provenance。全文不可访问时只能返回 `metadata_only`。

### 解析与入库

新增 `ParsePaperRequest`、`ParsePaperResult`、`ParsePaperUseCase`，与完整分析流程分离。LaTeX 使用 `LatexSourceParser`，PDF 使用现有 `CascadeDocumentParser`，HTML/OpenReview/publisher 使用 document adapter，local PDF 复用 PDF cascade。输出包括 paper、snapshots、document、parser attempts、quality report、chunk manifest、evidence/artifact refs。状态为 `received`、`resolving`、`metadata_only`、`parsing`、`parsed`、`degraded`、`catalog_partial`、`catalog_ready`、`failed`。fallback、质量拒绝、unsupported、source denial 必须有显式诊断。checksum + canonical identity 保证幂等。

### Paper-with-Code Catalog

新增 `ResearchPaperCatalogEntry`、`ResearchPaperRelation`、Catalog query/repository ports。至少支持 paper 到 task、method、dataset、benchmark、metric、score、code_repository 的 typed relation。关系记录 status、confidence、source snapshot refs、evidence refs、created_at、observed_at。`ResearchPaperCard` 仅为展示 projection。多个代码仓库需记录 canonical repo id、branch、commit、release 和观测时间；README、license、install、examples、training、inference、checkpoint 只能作为 observation/evidence。

### Benchmark 可信度

正文、表格和 caption 的结果先生成 `candidate`。score 必须带 paper、dataset、benchmark、metric、split、unit、direction、evaluation protocol 和 source refs。协议、数据集版本或方向不兼容时不可比较；`candidate`/`conflicting` 不得进入 verified leaderboard。`verified` 只能由 deterministic gate 或人工确认产生。SOTA claim 缺少 score、benchmark、metric 或 evidence 时保持 candidate。leaderboard 只展示协议兼容的 verified 快照并保留历史。

### API 与 CLI

Application service 负责编排，router/CLI 不得直接调用 parser、store 或 infrastructure。HTTP endpoint：

- `POST /api/v1/research/papers/parse`
- `GET /api/v1/research/papers/{paper_id}/sources`
- `GET /api/v1/research/papers/{paper_id}/document`
- `GET /api/v1/research/papers/{paper_id}/catalog`
- `GET /api/v1/research/papers/{paper_id}/code`
- `GET /api/v1/research/papers/{paper_id}/benchmarks`
- `GET /api/v1/research/catalog/papers`
- `GET /api/v1/research/catalog/leaderboards`
- `POST /api/v1/research/catalog/refresh`

CLI：`paper parse`、`paper ingest`、`paper refresh`、`paper catalog show/search`、`paper benchmark compare`、`paper code inspect`。所有命令支持 `--json`，API/CLI 共享状态、错误、provenance 和 artifact ref 字段。

## 架构与验收

`backend/research` 只依赖 domain、application、ports 和 framework contracts；技术实现放在 `infrastructure`，接口通过 `interfaces/services` 进入 application。Harness 继续控制有界 `PLAN -> EXECUTE -> VERIFY`，LLM 只生成 candidate；schema、evidence、lineage、identity、metric compatibility 和 actor scope gates 由确定性服务完成。phase transition、retry、degrade、conflict、quarantine 和 publication 写入 durable event log。默认使用 durable filesystem artifact/catalog store。

验收覆盖：arXiv/DOI/publisher 归并、受限来源 metadata-only、复杂 LaTeX 结构保留、PDF cascade attempts 与低质量降级、重复 ingest 幂等、无 evidence 的 score/SOTA/method edge 不得 verified、candidate 不进 leaderboard、API/CLI 不绕过 application service、`frontend` 无文件变更且无 legacy `paper_radar` 依赖。

验证命令：

```powershell
python -m scripts.dev compile
python -m scripts.dev test
python -m scripts.dev smoke
openspec validate research-paper-catalog-backend-v1 --strict
```
