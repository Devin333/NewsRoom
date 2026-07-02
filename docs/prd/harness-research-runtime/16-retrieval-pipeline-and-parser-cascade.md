# 阶段 16：检索层流水线重构与解析器级联 PRD

## 背景

阶段 10-15 已经建成了论文 RAG 的完整能力面：bounded 检索循环、结构化 chunking、evidence pack grounding、gold judge 质量回路和 faithfulness 校准。但 2026-07-02 的企业级审查（`docs/reviews/rag-enterprise-review-2026-07-02.md`）和检索层专项深查暴露出三类问题，它们共同构成本 PRD 的动机：

**第一，检索层工程形态已经到达不可维护的临界点。** `business/research/rag/retrieval/paper_retriever.py` 已增长到 3208 行、114 个私有方法，`retrieve()` 主函数近 200 行内联编排，`RetrievalPolicy` 平铺 30+ 个手调旋钮。五个召回来源（dense text、sparse lexical、field embedding、claim index、visual）各自返回不同类型，导致四个 `_merge_*` 和三个 `_*_hit_ranking` 适配方法；融合逻辑存在两个语义重叠的面（`_merge_*_hits` 的字典合并与 `_fuse_hybrid_candidate_channels` 的 RRF）。任何新能力（query rewrite、新召回通道、span 级 citation）都缺乏施工面。

**第二，存在一个生产级断线 bug。** `_sparse_lexical_candidates` 依赖 `_list_store_chunks`（`paper_retriever.py` 约 L2580-2597）的鸭子类型反射（探测 `list_chunks` 方法或 `_chunks` 字典）。生产 factory 装配的 `PaperChunkStoreAdapter`（Qdrant 后端，`business/research/document/chunk_storage.py`）两者皆无，反射兜底静默返回空列表。结果是：`paper_hybrid_rrf_rag_v1` 与 `paper_formula_rag_v1` 策略在生产环境中 sparse 通道恒为空，hybrid RRF 退化为纯 dense 多查询融合；而离线评测跑在 in-memory store 上 sparse 是活的，**评测报告中 hybrid 策略的提升数字无法在生产兑现**。

**第三，解析层缺少级联降级，且 bakeoff 指标存在幸存者偏差。** Parser bakeoff（20 篇金集）结果显示：MinerU 解析成功时检索质量最高（Hit@10 0.934 / Evidence@10 0.871），但解析成功率仅 12/20；Marker 全部解析成功（20/20）且指标均衡（Hit@10 0.844）；Nougat 19/20 但 Hit@10 与 Evidence@10 皆最低。当前 bakeoff 报告的 RAG 指标只在解析成功的论文上计算，分母不一致导致 MinerU 的领先幅度被高估。同时，主分支 `pdf_parser_backend.py` 目前只支持 `nougat | mineru` 两个 backend，`marker` 仅存在于 `ParseSource` 类型字面量（`models.py` L10），**Marker backend 实现尚未进入主分支**。单一 parser 无论选哪个都无法同时满足"成功率 100%"和"结构质量最优"，需要级联。

本 PRD 交付三件事：检索层重构为显式流水线、修复 sparse 生产断线、建立 MinerU 主 / Marker 兜底的解析器级联。三者都遵循"根源性修改，不做最小修补"的项目原则。

本 PRD 不改变 `framework/harness/rag` 的控制逻辑，不改变 `ResearchRetrievalGoal`、`RAGSessionSpec`、`RetrievalResult` 对外契约。所有变更位于 `business/research`（检索编排、解析级联）与 `infrastructure`（BM25 索引、Marker backend）。

---

## 设计原则

**行为快照先行，每步可回归**：重构开始前用当前代码在 golden set（`data/eval/golden_set.json`，67 条 / 20 篇 / 6 域）上产出全量基线报告并存档。此后每个重构步骤必须重跑评测：纯搬运步骤要求指标逐位一致，行为变更步骤要求指标不回退且在报告中说明 delta 来源。

**通道同构，融合唯一**：所有召回来源实现同一个通道协议、返回同一种排名结构。融合只发生在一处，算法（RRF / weighted）由配置选择。禁止在融合点之外再出现任何"顺手合并"。

**契约显式，禁止反射兜底**：Port 需要什么能力就在 Protocol 上声明什么方法。禁止 `getattr` 探测式适配，禁止静默返回空值的降级——降级必须写入 trace 并可观测。

**调优资产全部保留**：intent 规则、field 权重矩阵、parent 预算、position alpha 等数值是评测换来的资产，重构只改变它们的组织形态（代码常量 → 版本化配置文件），不改变数值。

**解析器级联降级不阻塞，产物可追溯**：主 parser 失败或产出不过质量检测时自动降级到兜底 parser，最终 fallback 保证任何 PDF 都有纯文本产出。每份文档在 chunk metadata 和 ingest manifest 中记录实际使用的 parser 与降级原因。

**评测口径公平**：所有对比性指标必须使用统一分母。解析失败的论文按检索指标 0 分计入惩罚性口径，与"成功子集口径"并列呈现。

---

## 一、检索层目标架构

### 流水线总览

```text
RetrievalRequest
   ↓
[1] QueryPlanner            意图分类（现有规则）→ 可序列化 RetrievalPlan
   ↓
[2] RecallChannels          五个同构通道并行召回 → list[RankedList]
   ↓
[3] Fusion                  唯一融合点（RRF k=60 或 weighted，配置选择）
   ↓
[4] RerankCascade           lightweight 字段启发 → CrossEncoder（阈值截断）→ 位置/意图偏置
   ↓
[5] ContextExpanders        parent / cross-ref / table / formula / supplemental，按 intent 声明式激活
   ↓
RetrievalResult（契约不变）+ RetrievalTrace（结构化、可入 harness transcript）
```

### 目标目录

```text
business/research/rag/retrieval/
├── pipeline.py          # RetrievalPipeline 骨架，编排 1-5 段，目标 < 200 行
├── planner.py           # QueryPlanner：吸收 paper_policy.py 的 intent 规则与 build_retrieval_route
├── plan.py              # RetrievalPlan / ChannelSpec / FusionSpec / RerankSpec / ExpanderSpec（可序列化 DTO）
├── channels/
│   ├── base.py          # RecallChannel Protocol + RankedList / RankedHit 统一结构
│   ├── dense_text.py    # 现 _search_text_candidates / _search_hybrid_text_candidates 的 dense 部分
│   ├── sparse_lexical.py# 现 _sparse_lexical_candidates，实现换 BM25 索引（见第三节）
│   ├── field_embedding.py
│   ├── claim_index.py
│   └── visual.py
├── fusion.py            # 现 _rrf_fuse_rankings + weighted 融合，唯一融合点
├── rerank.py            # RerankCascade：lightweight → CrossEncoder → 位置/意图偏置
├── expanders/
│   ├── base.py          # ContextExpander Protocol + 注册表
│   ├── parent.py        # 现 _fetch_parents / _parent_* 家族
│   ├── cross_ref.py     # 现 _fetch_refs
│   ├── table_context.py # 现 _fetch_table_context / _supplemental_table_hits / _interleave_structural_context
│   └── formula_context.py
├── trace.py             # RetrievalTrace：per-stage 输入/输出规模、耗时、启用开关、降级记录
└── paper_retriever.py   # 过渡期薄入口：委托 pipeline，全部迁移后删除
```

### 通道协议

```python
class RecallChannel(Protocol):
    name: str
    def recall(self, request: RetrievalRequest, plan: RetrievalPlan) -> RankedList: ...

@dataclass(frozen=True)
class RankedHit:
    chunk_id: str
    score: float
    channel: str
    metadata: dict[str, Any]   # 通道专有信息（field_name、claim_id、visual bucket 等）

RankedList = list[RankedHit]
```

统一为 `RankedHit` 后，现有 `_merge_field_hits`、`_merge_claim_hits`、`_field_hit_ranking`、`_claim_hit_ranking`、`_visual_hit_ranking` 等七个类型适配方法整体删除。chunk 本体在融合后按 id 批量取，通道内不再传递 `PaperChunk` 副本。

### 保留 / 重构 / 舍弃清单

| 处置 | 对象 | 说明 |
| --- | --- | --- |
| 保留 | `paper_policy.py` intent 规则、`build_retrieval_route` | 迁入 planner.py，规则与数值不变 |
| 保留 | field 权重矩阵、parent 预算、position alpha 等全部调优数值 | 迁入配置文件，数值不变 |
| 保留 | `_rrf_fuse_rankings`、CrossEncoderReranker、`framework/rag/retrieval` 工具集 | 原样复用 |
| 保留 | `RetrievalResult` child/parent/ref 三分契约 | 下游 answer generator 依赖，不变 |
| 重构 | 五个召回来源方法 → 五个通道类 | 纯搬运，评测逐位一致 |
| 重构 | 双融合面 → 唯一融合点 | 行为变更，需评测确认无回退 |
| 重构 | 五个 expander 方法 → 声明式注册的 expander 类 | 纯搬运 |
| 重构 | `retrieve()` 内 60+ 键 metrics 字典 → RetrievalTrace | 对接 harness transcript |
| 重构 | `RetrievalPolicy` 30+ 平铺字段 → 按 stage 分组的嵌套配置，落盘 `configs/retrieval/*.yaml` | 数值不变，调参不再改代码 |
| 舍弃 | `_list_store_chunks` 反射兜底（getattr 探测） | 换显式 Port 契约，见第三节 |
| 舍弃 | `_sparse_lexical_score` 全量扫描 token overlap 与 0.95 phrase magic number | 换 BM25 索引 |
| 舍弃 | `infrastructure/storage/hybrid_search.py` | 零调用方孤儿，直接删除 |
| 舍弃 | `retrieve()` 内联 `import time` 计时 | pipeline 骨架统一计时 |
| 舍弃 | 消融证明无效的 policy 旋钮 | 逐字段关闭跑 benchmark，指标无差异即删 |

### 配置化

`configs/retrieval/` 下每个命名策略一个 YAML 文件（`default.yaml`、`paper_hybrid_rrf_rag_v1.yaml` 等），结构按 stage 分组：

```yaml
name: paper_hybrid_rrf_rag_v1
version: 1
channels:
  dense_text:  { enabled: true,  multi_query: true, overfetch_multiplier: 5 }
  sparse_lexical: { enabled: true, limit_multiplier: 4 }
  field_embedding: { enabled: true, intent_search_fields: { figure_query: [caption, visual_description, body], ... } }
  claim_index: { enabled: true, intents: [citation_query] }
  visual: { enabled: true, fusion_weights: { text: 0.85, visual: 0.15 } }
fusion: { algorithm: rrf, rrf_k: 60 }
rerank:
  lightweight: { intents: [figure_query, table_query, numerical_result, comparison, formula_query] }
  cross_encoder: { intents: [...], score_threshold: 0.3 }
  position: { alpha: { figure_query: 0.0, concept_method: 0.2, ... }, sigma: 3.0 }
expanders:
  parent: { max_chunks: 3, max_tokens: 1800, intent_budgets: { table_query: [1, 700], ... } }
  table_context: { max_chunks: 4 }
  formula_context: { max_chunks: 2 }
```

加载器做 schema 校验（未知键报错），`NEWS_PAPER_RAG_POLICY` 环境变量语义不变。评测报告记录 `policy.name + policy.version + 配置文件 hash`，实现评测结果与策略版本的强绑定。

---

## 二、Sparse 通道生产断线修复（前置于重构）

### 根因

`ChunkStorePort`（`business/research/ports/chunk_store.py`）没有声明 `list_chunks`；`_list_store_chunks` 用反射探测，探测失败静默返回 `[]`。生产 `PaperChunkStoreAdapter` 恰好探测失败。

### 修复方案

1. **Port 契约显式化**：`ChunkStorePort` Protocol 增加 `list_chunks(paper_id: str) -> list[PaperChunk]`。
2. **生产实现补齐**：`PaperChunkStoreAdapter.list_chunks` 委托 `ChunkPayloadStorePort.list_paper_payloads`（`infrastructure/storage/vector/paper_chunk_store.py` 用 Qdrant scroll 实现；或经 `PaperChunkRepositoryAdapter` 从 Postgres 读，二选一，以 ingest 时的权威存储为准——推荐 Postgres，因 payload 完整且无向量传输开销）。
3. **删除反射**：`_list_store_chunks` 整体删除，调用点改为直接调 Port 方法。
4. **降级可观测**：任何通道产出为空时写入 `RetrievalTrace.degradations`，不再静默。
5. **BM25 升级**（可与修复同批或紧随其后）：ingest 阶段为每篇论文构建 BM25 倒排索引（`infrastructure/retrieval/bm25_index.py`，rank_bm25 内存构建 + 落盘），`SparseLexicalChannel` 查询该索引替代全量扫描。保留 caption/equation/table 字段 1.1 加权的思想，改为字段域加权 BM25F 风格实现。

### 验收

- 新增集成测试：用真实 `PaperChunkStoreAdapter`（Qdrant testcontainer 或本地实例）断言 hybrid 策略下 sparse ranking 非空、`sparse_recalled > 0`。
- golden set 上 `paper_hybrid_rrf_rag_v1` 的评测在"生产 adapter"与"eval in-memory store"两种装配下 sparse_recalled 均大于 0，且指标差异 < 2%（消除评测与生产的装配漂移）。

---

## 三、解析器级联：MinerU 主、Marker 兜底

### 决策依据

Bakeoff（20 篇金集）关键数据：

| Parser | 解析成功 | Hit@10（成功子集） | Evidence@10 | Locator@10 | 惩罚性 Hit@10（失败计 0） |
| --- | --- | --- | --- | --- | --- |
| MinerU | 12/20 | 0.934 | 0.871 | 0.931 | ≈ 0.560 |
| Marker | 20/20 | 0.844 | 0.799 | 0.908 | 0.844 |
| Nougat | 19/20 | 0.831 | 0.748 | 1.000 | ≈ 0.789 |

结论：MinerU 结构提取质量最高但成功率不可接受；Marker 是唯一保证"任何论文都能进系统"的选项；Nougat 除 locator 满分外无胜出位置，locator 能力可在其余两条路径上补齐，不入级联。**采用 MinerU 优先、Marker 兜底、PyMuPDF 纯文本保底的三级级联**，与阶段 11 PRD"分级预处理，失败降级不阻塞"原则一致。

### 前置任务 P16-0：MinerU 失败归因

最近提交 `f9f7aaae Pin MinerU pdftext dependency` 表明部分失败可能是依赖/环境问题而非能力问题。级联开工前先对 8 篇失败论文逐一归因，分类为 `environment | timeout | layout_capability | ocr_capability`，产出 `data/eval/results/mineru_failure_audit.md`。若修复环境后成功率 ≥ 18/20，级联仍然要做（兜底是架构要求），但 MinerU 权重预期显著上升。

### 前置任务 P16-1：Marker backend 进主分支

现状：`pdf_parser_backend.py` 仅支持 `nougat | mineru`；`ParseSource` 字面量已含 `"marker"` 但无实现。需要：

- 新增 `business/research/document/marker_pdf_parser.py`：`MarkerPdfDocumentParser.parse(paper_id, source_bytes) -> ResearchDocument`，复用 `docker_pdf_parser.py` 的容器执行骨架（`stage_pdf_for_docker` / `run_docker_command` / `source_locator`），输出对齐 `ResearchDocument` 章节/图表/公式结构，chunk metadata 记 `parse_source: marker`。
- `pdf_parser_backend.py` 的 `PdfParserBackendName` 扩为 `Literal["nougat", "mineru", "marker"]`，bakeoff CLI `--pdf-parser-backend` choices 同步。
- Marker 路径补 locator 提取（页码 + bbox），目标 Locator@10 ≥ 0.95，追平 Nougat 的唯一优势。

### 级联设计

新增 `business/research/document/cascade_parser.py`：

```python
@dataclass(frozen=True)
class ParserAttempt:
    backend: str                 # mineru | marker | pymupdf
    status: str                  # success | parse_error | timeout | quality_rejected
    reason: str | None
    elapsed_ms: float

@dataclass(frozen=True)
class CascadeParseOutcome:
    document: ResearchDocument
    used_backend: str
    attempts: list[ParserAttempt]

class CascadeDocumentParser:
    """DocumentParserPort 实现。按序尝试 backends，每级产物过 DocumentQualityProbe，
    全部失败时以 PyMuPDF 纯文本保底（保底产物标记 degraded=true）。"""
    def __init__(self, backends: Sequence[DocumentParserPort], probe: DocumentQualityProbe, fallback: DocumentParserPort): ...
    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument: ...
```

要点：

1. **实现 `DocumentParserPort`**，对 `ChunkPaperPipeline` 完全透明——pipeline 一行不改，仅 `paper_rag_factory.build_chunk_pipeline` 的装配处替换 parser。
2. **质量探针（deterministic gate，非 LLM）**：`DocumentQualityProbe` 检查产物结构完整性，任一硬指标不过即视为该级失败、进入下一级：
   - `sections_count >= 3`（论文至少有引言/正文/结论量级的结构）
   - `body_char_count >= 3000`
   - `non_empty_section_ratio >= 0.8`
   - 若 PDF 侧检测到表格（Surya layout 已有信号），则 `tables_with_rows / tables_detected >= 0.5`
   - 乱码率探测：非法 unicode / 替换字符占比 < 2%
   阈值集中在 `configs/parsing/quality_probe.yaml`，用 bakeoff 20 篇产物回放校准（成功产物全过、已知坏产物全拒）。
3. **超时与预算**：MinerU 级设 per-paper 超时（沿用 `_mineru_timeout_seconds`），超时即降级不重试；级联总耗时入 manifest。
4. **可追溯**：`CascadeParseOutcome.attempts` 全量写入 ingest manifest（`chunk_manifest.py` 扩展 `parser_cascade` 字段）；chunk metadata 的 `parse_source` 记实际 backend。批量 ingest 报告聚合各级使用率与降级原因分布。
5. **优先序可配置**：`NEWSROOM_PDF_PARSER_CASCADE=mineru,marker`（默认），保留单 backend 直连模式供 bakeoff 使用。
6. **arXiv LaTeX 路径不变**：级联只作用于 PDF 路径；LaTeX 源可用时仍走 `ArxivDocumentParser` 优先（阶段 11 既定优先级）。

### Bakeoff 报告公平性修正

`paper_parser_bakeoff_report.py` 的 `_rag_metrics` 旁增加惩罚性口径：`penalized_hit_at_10`、`penalized_mrr`、`penalized_evidence_coverage_at_10`（解析失败论文按 0 计入，分母统一为 requested）。报告同时呈现两种口径并标注定义。级联本身也作为一个"虚拟 backend"进入 bakeoff 矩阵，验收其惩罚性口径优于任何单一 parser。

---

## 四、交付分解与顺序

| 步骤 | 内容 | 类型 | 评测要求 |
| --- | --- | --- | --- |
| S0 | golden set 全量基线快照存档（retrieval + generation + system） | 安全网 | 产出基线报告，入 `data/eval/results/` |
| S1 | Sparse 断线修复：Port 契约 + PaperChunkStoreAdapter.list_chunks + 删反射 + 集成测试 | bug 修复 | 生产 adapter 下 sparse_recalled > 0；两种装配指标差 < 2% |
| S2 | P16-0 MinerU 失败归因 + P16-1 Marker backend 进主分支 | 解析层 | Marker 单 backend 复现 bakeoff ≈ 0.844；Locator ≥ 0.95 |
| S3 | CascadeDocumentParser + DocumentQualityProbe + manifest 追溯 + 惩罚性口径报告 | 解析层 | 级联 20/20 成功；penalized_hit@10 ≥ max(单 parser) |
| S4 | 通道类化（五通道 + RankedHit 统一）+ 删七个适配方法 | 纯搬运 | 指标逐位一致 |
| S5 | 融合收敛到唯一 RRF/weighted 点 | 行为变更 | 指标不回退，delta 有解释 |
| S6 | RerankCascade + Expander 类化 + 注册表 | 纯搬运 | 指标逐位一致 |
| S7 | Policy 配置化（YAML + schema 校验 + 版本 hash 入评测报告）+ 无效旋钮消融删除 | 配置迁移 | 数值不变项逐位一致；删除项附消融报告 |
| S8 | RetrievalTrace 结构化 + 降级可观测 + 删 hybrid_search.py 孤儿 | 收尾 | trace 可入 harness transcript |
| S9 | BM25 索引替换 sparse 全量扫描 | 性能/质量 | hybrid 策略 MRR/hit@10 相对 S1 后基线不回退，预期提升 |

依赖关系：S1 必须先于 S9（先接通再升级）；S2 先于 S3；S4-S8 严格串行，每步一个 commit，commit message 附评测对照结论。S1-S3 与 S4-S8 可并行推进。

---

## 五、测试计划

**新增测试：**

- `tests/business/research/rag/test_recall_channels.py`：五通道各自的召回正确性与 RankedHit 结构契约。
- `tests/business/research/rag/test_fusion.py`：RRF 与 weighted 融合的确定性（同输入同输出）、通道缺席时的行为。
- `tests/business/research/rag/test_retrieval_pipeline_parity.py`：S4/S6 搬运步骤的新旧实现对拍（同请求同结果）。
- `tests/business/research/integration/test_sparse_channel_production_adapter.py`：真实 Qdrant/Postgres adapter 下 sparse 通道非空（条件 skip 环境变量沿用 e2e 约定，但纳入 nightly 必跑）。
- `tests/business/research/document/test_cascade_parser.py`：一级成功不降级、一级失败降二级、探针拒绝降级、全失败走保底且标记 degraded、attempts 完整记录。
- `tests/business/research/document/test_quality_probe.py`：用 bakeoff 存档产物回放校准阈值。
- `tests/business/research/rag/test_retrieval_policy_config.py`：YAML 加载、schema 校验、未知键报错、与旧代码常量数值等价。

**回归：** 现有 `test_retriever.py`、`test_routing.py`、`test_retrieval_port.py`、benchmark suite 全量保持绿色；`RetrievalResult` 契约由 `test_retrieval_port.py` 守护不变。

---

## 六、验收标准

1. `paper_retriever.py` 主文件消失或降为 < 100 行薄入口；pipeline.py < 200 行；无任何 `getattr` 反射式 Port 探测。
2. 生产装配下 hybrid 策略 sparse_recalled > 0，评测与生产装配的指标漂移 < 2%。
3. golden set 全量指标相对 S0 基线：搬运步骤逐位一致，最终态（S9 后）hit@10 / MRR / evidence_coverage 不回退。
4. 级联 ingest 在 bakeoff 20 篇上解析成功率 20/20，penalized_hit@10 ≥ 0.844（不低于 Marker 单独使用），MinerU 使用占比与失败归因在报告中可见。
5. 每份 ingest 产物的 manifest 含 `parser_cascade.attempts`；每份评测报告含 policy name/version/config hash。
6. `infrastructure/storage/hybrid_search.py` 删除，仓库无引用残留。
7. 全部新增测试进入 CI；`test_sparse_channel_production_adapter.py` 进入 nightly。

---

## 七、风险与对策

| 风险 | 对策 |
| --- | --- |
| 重构引入行为漂移，评测无法逐位对齐 | S0 快照 + S4/S6 新旧对拍测试；漂移必须归因到具体 stage 才允许合入 |
| Qdrant scroll 读全量 chunk 延迟高 | list_chunks 走 Postgres payload 仓库；BM25 索引 ingest 期预建，查询期零扫描 |
| MinerU 容器级联拖慢批量 ingest | per-paper 超时即降级；ingest 本身异步批处理，延迟不在用户交互路径 |
| 质量探针阈值误杀好产物 / 放过坏产物 | 阈值用 bakeoff 存档产物回放校准；探针拒绝原因全量入 manifest，可人工复核后调阈值 |
| Marker backend 新实现的 locator 质量不达标 | S2 单独验收 Locator ≥ 0.95 后才允许进入 S3 级联 |
| policy 旋钮消融工作量大 | 只对怀疑无效的字段做消融（position/graph 权重为 0 的组合优先），其余原样迁移 |
| 配置文件与代码默认值双源漂移 | 代码内不保留数值默认，YAML 是唯一事实源；缺配置直接报错不兜底 |

---

## 八、OpenSpec change 拆分建议

1. `fix-sparse-channel-production-wiring`（S1）：Port 契约 + adapter 实现 + 删反射 + 集成测试。
2. `add-marker-parser-backend`（S2）：Marker backend + locator 补齐 + bakeoff 接入。
3. `add-parser-cascade-quality-probe`（S3）：级联 + 探针 + manifest 追溯 + 惩罚性口径。
4. `refactor-retrieval-pipeline-channels`（S4-S6）：通道化 + 融合收敛 + expander 注册表。
5. `retrieval-policy-config-and-trace`（S7-S8）：配置化 + trace + 孤儿删除。
6. `sparse-bm25-index`（S9）：BM25 索引与字段加权。

每个 change 独立可合入、独立可回滚，评测报告作为 change 的归档产物。
