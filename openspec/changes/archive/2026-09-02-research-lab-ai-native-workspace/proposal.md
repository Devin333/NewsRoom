# Research Lab AI-Native Workspace

## Why

/projects/lab 已有确定性 Lab session 能力，但目前的两个通用面板、原始 JSON 和缺少工作流反馈的控制区，不适合研究负责人、产品负责人和工程负责人反复完成“问题 -> 澄清 -> 方案 -> 审阅 -> 保存”的工作。用户难以看出真实数据来源、当前阶段、待完成问题、生成资格和保存的准确语义。

参考的 AI chatbot platform 证明了轻量表面、清晰的交互层级、代码或结构化数据 Tab 和真实反馈可以降低操作负担。但 Agora Hub 必须保持研究产品的可信、可审计和蓝色品牌语言，而不能复制外部品牌或把确定性 workflow 描述为拟人化 AI。

## What Changes

- 将 /projects/lab 改造成以 brief、workflow、clarification、context、solution 为中心的研究工作区。
- 将 /projects/lab/[sessionId] 对齐为持久化的审阅与保存页面。
- 使用 projects-lab-workflow-contract 的服务端 workflow 字段驱动所有阶段、下一动作和生成资格。
- 将方案拆为 Summary、Structured、Evidence 视图，保留原始结构化数据的可审计性。
- 为 LabGraph 补充文本摘要、节点解释入口和局部失败隔离。
- 复用现有 Projects loading/error/empty/degraded state，补齐 mutation feedback、i18n、keyboard、screen reader 和响应式行为。
- 在 Lab scope 使用既有 light/dark tokens，必要时新增有限的 semantic Lab tokens。

## Capabilities

### New Capabilities

- research-lab-ai-native-workspace：可信、响应式、可访问的 Projects Lab workspace 和 session detail 审阅体验。

### Modified Capabilities

- Projects Lab 页面从通用双栏表单改为有明确 workflow feedback、solution tabs 和真实数据状态的工作区。
- Lab graph 由只可视化的展示扩展为包含文本替代与节点解释的可访问研究上下文。

## Impact

- Affected frontend routes: frontend/src/app/projects/lab/page.tsx, frontend/src/app/projects/lab/[sessionId]/page.tsx.
- Affected frontend feature area: frontend/src/features/projects/components, Projects API types/client, Lab tests, i18n resources and visual tests.
- Affected backend only through the prerequisite contract change; this workspace change does not create a second domain workflow implementation.
- Reuses existing ProjectApplicationService and /api/v1/projects/lab endpoints; it does not reach directly into state repositories, artifacts or executors.

## Non-goals

- No new LLM provider, token streaming, hidden reasoning display, automatic planner, automatic quality decision, memory write, tool authorization or publishing.
- No fake projects/cases/source metadata, no new crawler/source policy behavior, no global theme rewrite.
- No changes outside Projects Lab and its session detail route without a separate approved change.

## Dependency

Implementation MUST begin after projects-lab-workflow-contract has passed strict validation and its API tests. The workspace MUST treat an unavailable or unknown contract value as a recoverable, non-actionable state.
