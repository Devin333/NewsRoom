import { apiGet } from "@/lib/api/client"
import type {
  ProjectClientRequest,
  ProjectDetailResult,
  ProjectItem,
  ProjectListParams,
  ProjectListResult,
  ProjectProductRoute,
  ProjectProductSection,
} from "@/types/projects"

type ApiEnvelope<T> = {
  success: boolean
  data?: T | null
  error?: {
    code: string
    message: string
    detail?: unknown
    details?: unknown
    retryable?: boolean
  } | null
}

export class ProjectsApiError extends Error {
  code: string
  detail?: unknown
  retryable?: boolean

  constructor(message: string, code = "projects_api_error", detail?: unknown, retryable?: boolean) {
    super(message)
    this.name = "ProjectsApiError"
    this.code = code
    this.detail = detail
    this.retryable = retryable
  }
}

export async function fetchProjects(params: ProjectListParams = {}, init?: RequestInit): Promise<ProjectListResult> {
  const envelope = await apiGet<ApiEnvelope<ProjectListResult>>(`/api/projects${queryString(params)}`, init)
  return unwrapEnvelope(envelope)
}

export async function fetchProjectDetail(slug: string, init?: RequestInit): Promise<ProjectItem> {
  const result = await fetchProjectDetailResult(slug, init)
  return result.project
}

export async function fetchProjectDetailResult(slug: string, init?: RequestInit): Promise<ProjectDetailResult> {
  const envelope = await apiGet<ApiEnvelope<ProjectDetailResult>>(`/api/projects/${encodeURIComponent(slug)}`, init)
  return unwrapEnvelope(envelope)
}

export const PROJECT_PRODUCT_SECTIONS: ProjectProductSection[] = [
  {
    id: "hot",
    title: "热门项目",
    description: "按趋势、Star velocity 和证据强度聚合的近期高热度项目。",
    href: "/projects/hot",
    params: { sort: "trending", period: "weekly", limit: 18 },
  },
  {
    id: "rising",
    title: "上升项目",
    description: "优先展示新增、Rising 和增长明显的项目。",
    href: "/projects/rising",
    params: { sort: "growth", period: "monthly", limit: 18 },
  },
  {
    id: "tools",
    title: "工具箱",
    description: "面向工程落地的 Agent、RAG、推理和评测工具。",
    href: "/projects/tools",
    params: { sort: "activity", source: "github", limit: 18 },
  },
  {
    id: "cases",
    title: "案例",
    description: "结合论文、新闻与社区引用，观察项目被采用和讨论的证据。",
    href: "/projects/cases",
    params: { sort: "quality", limit: 18 },
  },
  {
    id: "lab",
    title: "实验室",
    description: "偏新、实验性或快速迭代的项目观察入口。",
    href: "/projects/lab",
    params: { sort: "newest", period: "monthly", limit: 18 },
  },
  {
    id: "collections",
    title: "集合",
    description: "按主题、语言和成熟度组织真实 Project Radar 记录。",
    href: "/projects/collections",
    params: { sort: "trending", limit: 48 },
  },
  {
    id: "watchlist",
    title: "关注列表",
    description: "基于真实雷达信号生成的候选关注项目。",
    href: "/projects/watchlist",
    params: { sort: "quality", period: "monthly", limit: 24 },
  },
]

export function projectProductSection(route: ProjectProductRoute): ProjectProductSection {
  if (route === "home") {
    return {
      id: "home",
      title: "Projects",
      description: "Project Radar 的产品首页，汇总开源项目增长、工程采用和跨模块证据。",
      href: "/projects",
      params: { sort: "trending", limit: 24 },
    }
  }
  return PROJECT_PRODUCT_SECTIONS.find((section) => section.id === route) ?? PROJECT_PRODUCT_SECTIONS[0]
}

export async function fetchProjectProductSection(
  route: ProjectProductRoute,
  request: ProjectClientRequest = {}
): Promise<ProjectListResult> {
  const section = projectProductSection(route)
  return fetchProjects({ ...section.params, ...request.params }, request.init)
}

function unwrapEnvelope<T>(envelope: ApiEnvelope<T>): T {
  if (envelope.success && envelope.data) {
    return envelope.data
  }
  const error = envelope.error
  throw new ProjectsApiError(
    error?.message ?? "Projects API request failed",
    error?.code,
    error?.detail ?? error?.details,
    error?.retryable
  )
}

function queryString(params: ProjectListParams): string {
  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue
    searchParams.set(key, String(value))
  }
  const text = searchParams.toString()
  return text ? `?${text}` : ""
}
