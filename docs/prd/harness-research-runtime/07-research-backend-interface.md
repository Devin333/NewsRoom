# 阶段 7：Research 后端接口

## 阶段目标

新增 Research 后端 service 和 API router，为后续 UI 提供干净入口。阶段 7 不做 UI，不复用旧 paper API，不做旧 payload 兼容。

## 新增目录和文件

```text
interfaces/services/research_service.py
interfaces/api/routers/research.py
tests/interfaces/services/test_research_service.py
tests/interfaces/api/test_research_api.py
tests/interfaces/api/test_research_contracts.py
```

如果项目已有 API router 注册表，需要注册新 router，但不要删除旧 paper router；删除旧接口在阶段 9。

## 接口范围

第一版只覆盖后端 Research 闭环：

```text
POST /api/research/papers/analyze
GET  /api/research/papers/{paper_id}/analysis
GET  /api/research/papers/{paper_id}/reader
POST /api/research/papers/{paper_id}/ask
GET  /api/research/runs/{run_id}/trace
```

可以根据现有 API 风格调整路径前缀，但必须是 Research 新接口，不使用旧 `/api/papers`。

## Service 边界

`ResearchApplicationService` 可以依赖：

```text
business/research/application
framework/harness public contracts
```

不允许：

```text
直接调用 infrastructure storage
直接调用旧 paper_service
直接调用 business/boards/paper_radar
直接操作 Harness 内部私有状态
```

## 请求响应模型

### Analyze request

字段建议：

```text
paperId
sourceUrl
pdfUrl
metadata
options
```

### Analyze response

字段建议：

```text
runId
paperId
status
analysisRef
readerPayloadRef
qualityRef
traceRef
```

### Reader response

字段建议：

```text
paper
document
analysis
evidence
navigation
quality
metadata
```

### Ask request

字段建议：

```text
question
locale
selection
options
```

### Ask response

字段建议：

```text
answer
evidenceRefs
confidence
traceRef
```

## 错误处理

必须标准化：

```text
paper_not_found
analysis_not_found
research_run_failed
quality_gate_failed
invalid_request
```

不要泄露内部 traceback 给 API 响应。

## 测试要求

必须覆盖：

- service 只调用 Research application。
- API router 不 import `business.boards.paper_radar`。
- analyze endpoint 返回 run id 和 refs。
- reader endpoint 返回新 reader payload。
- ask endpoint 返回 evidence refs。
- 错误响应稳定。
- 不访问旧 paper cache / old paper service。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/interfaces/services/test_research_service.py tests/interfaces/api/test_research_api.py tests/interfaces/api/test_research_contracts.py -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- Research 后端接口可测试。
- 不复用旧 paper API。
- 不做 UI。
- 旧 paper 接口暂不删，等待阶段 9。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/07-research-backend-interface.md。
要求：
1. 新增 interfaces/services/research_service.py 和 interfaces/api/routers/research.py。
2. 提供 analyze、analysis、reader、ask、trace 后端接口。
3. 接口只调用 Research application service，不复用旧 paper API 或旧 paper_radar。
4. 不做 UI。
5. 添加 service、API、contract 测试。
6. 运行 python -m scripts.dev compile、指定 Research interface 测试、openspec validate harness-research-runtime --strict。
7. 修改完成后提交。
全部回复和问题用中文。
```
