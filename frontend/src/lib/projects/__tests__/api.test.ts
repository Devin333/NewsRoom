import { beforeEach, describe, expect, it, vi } from "vitest"
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api/client"
import {
  addProjectCollectionItem,
  addProjectWatchlistItem,
  answerProjectLabQuestion,
  compareProjectTools,
  createProjectCollection,
  deleteProjectWatchlistItem,
  explainProjectCase,
  explainProjectLabNode,
  fetchProjectCaseDetail,
  fetchProjectCollectionDetail,
  fetchProjectDetail,
  fetchProjectLabSession,
  fetchProjectToolDetail,
  fetchProjectV1Detail,
  fetchProjects,
  fetchProjectsHot,
  fetchProjectsHome,
  generateProjectCollection,
  generateProjectLabSolution,
  mapProjectCaseToContext,
  patchProjectWatchlistItem,
  recommendProjectTools,
  recordProjectInteraction,
  refreshProjectWatchlistItem,
  saveProjectLabSession,
  startProjectLabSession,
  ProjectsApiError,
} from "@/lib/projects/api"

vi.mock("@/lib/api/client", () => ({
  apiDelete: vi.fn(),
  apiGet: vi.fn(),
  apiPatch: vi.fn(),
  apiPost: vi.fn(),
}))

describe("projects API client", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset()
    vi.mocked(apiPost).mockReset()
    vi.mocked(apiPatch).mockReset()
    vi.mocked(apiDelete).mockReset()
  })

  it("uses project BFF routes for list and detail", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        items: [],
        allItems: [],
        metrics: [],
        options: { categories: [], sources: [], languages: [], topics: [], maturity: [] },
        allFiltered: [],
        page: { page: 1, pageSize: 24, total: 0, hasNext: false },
        dataState: "empty",
        source: "none",
        notices: [],
      },
    })

    await fetchProjects({
      q: "agent",
      category: "agent",
      topic: "workflow",
      sort: "activity",
      source: "github",
      language: "python",
      maturity: "rising",
      period: "weekly",
      limit: 12,
    })
    expect(apiGet).toHaveBeenCalledWith(
      "/api/projects?q=agent&category=agent&topic=workflow&sort=activity&source=github&language=python&maturity=rising&period=weekly&limit=12",
      undefined
    )

    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        project: {
          id: "p1",
          slug: "openai-codex",
          name: "codex",
          fullName: "openai/codex",
          description: "Terminal coding agent",
          repoUrl: "https://github.com/openai/codex",
          scores: {},
          categoryRefs: [],
          categories: [],
          tags: [],
          topics: [],
          relationCounts: { papers: 0, news: 0, community: 0 },
        },
        dataState: "ready",
        source: "artifact",
        notices: [],
      },
    })

    const project = await fetchProjectDetail("openai/codex")
    expect(apiGet).toHaveBeenCalledWith("/api/projects/openai%2Fcodex", undefined)
    expect(project.repoUrl).toBe("https://github.com/openai/codex")
  })

  it("uses backend Projects API v1 for product routes and ok envelopes", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({
      ok: true,
      data: {
        hot: [],
        rising: [],
        tools: [],
        cases: [],
        collections: [],
        watchlist: [],
        recommendations: [],
        meta: { source: "none", data_state: "empty", notices: [] },
        metrics: [],
      },
    })

    const home = await fetchProjectsHome({ limit: 6 })
    expect(apiGet).toHaveBeenCalledWith("/api/v1/projects?limit=6", undefined)
    expect(home.meta.data_state).toBe("empty")

    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        items: [],
        page: { page: 1, page_size: 18, total: 0, has_next: false },
        meta: { source: "none", data_state: "empty", notices: [] },
        metrics: [],
      },
    })

    await fetchProjectsHot({ q: "agent", topic: "workflow", pageSize: 18, limit: 18 })
    expect(apiGet).toHaveBeenCalledWith("/api/v1/projects/hot?q=agent&tag=workflow&page_size=18&limit=18", undefined)
  })

  it("uses Projects API v1 detail routes", async () => {
    vi.mocked(apiGet)
      .mockResolvedValueOnce({
        ok: true,
        data: {
          project: apiProject("project-1"),
          sources: [],
          metrics: [],
          growth: [],
          capabilities: [],
          tool_profile: null,
          cases: [],
          collections: [],
          watch_status: null,
          recommended_actions: [],
          ranking: {},
          meta: readyMeta(),
        },
      })
      .mockResolvedValueOnce({
        success: true,
        data: apiTool("tool-1"),
      })
      .mockResolvedValueOnce({
        ok: true,
        data: apiCase("case-1"),
      })
      .mockResolvedValueOnce({
        success: true,
        data: apiCollection("agent-collections"),
      })

    const projectDetail = await fetchProjectV1Detail("org/project")
    expect(apiGet).toHaveBeenCalledWith("/api/v1/projects/org%2Fproject", undefined)
    expect(projectDetail.project.id).toBe("project-1")

    const tool = await fetchProjectToolDetail("tool/1")
    expect(apiGet).toHaveBeenCalledWith("/api/v1/projects/tools/tool%2F1", undefined)
    expect(tool.profile.project_id).toBe("tool-1")

    const projectCase = await fetchProjectCaseDetail("case/1")
    expect(apiGet).toHaveBeenCalledWith("/api/v1/projects/cases/case%2F1", undefined)
    expect(projectCase.title).toBe("Workflow case")

    const collection = await fetchProjectCollectionDetail("agent/collections")
    expect(apiGet).toHaveBeenCalledWith("/api/v1/projects/collections/agent%2Fcollections", undefined)
    expect(collection.slug).toBe("agent-collections")
  })

  it("uses Projects API v1 case explain and map routes", async () => {
    vi.mocked(apiPost)
      .mockResolvedValueOnce({
        success: true,
        data: {
          case_id: "case-1",
          style: "migration",
          summary: "Reusable workflow orchestration pattern.",
          key_points: ["Keep ingestion isolated"],
          component_explanations: [],
          pattern_explanations: [],
          migration_notes: ["Map queue boundaries first"],
          source_refs: ["source-1"],
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: {
          case_id: "case-1",
          fit_score: 0.82,
          reusable_components: [],
          migration_steps: ["Adopt scheduler"],
          cautions: ["Verify retry semantics"],
          source_refs: ["source-1"],
        },
      })

    const explanation = await explainProjectCase("case/1", {
      style: "migration",
      user_context: "Newsroom ingestion pipeline",
    })
    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/projects/cases/case%2F1/explain",
      { style: "migration", user_context: "Newsroom ingestion pipeline" },
      undefined
    )
    expect(explanation.summary).toContain("workflow")

    const mapped = await mapProjectCaseToContext("case/1", {
      user_context: "Newsroom ingestion pipeline",
      target_module: "collection",
      constraints: ["local deploy"],
    })
    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/projects/cases/case%2F1/map-to-context",
      {
        user_context: "Newsroom ingestion pipeline",
        target_module: "collection",
        constraints: ["local deploy"],
      },
      undefined
    )
    expect(mapped.fit_score).toBe(0.82)
  })

  it("uses Projects API v1 Lab get, explain, and save routes", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({
      ok: true,
      data: {
        session: labSession("session-1"),
      },
    })
    vi.mocked(apiPost)
      .mockResolvedValueOnce({
        success: true,
        data: {
          session_id: "session-1",
          node_id: "node-1",
          title: "Queue boundary",
          explanation: "This node separates collection from analysis.",
          related_nodes: [],
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: {
          session: {
            ...labSession("session-1"),
            status: "saved",
          },
        },
      })

    const session = await fetchProjectLabSession("session/1")
    expect(apiGet).toHaveBeenCalledWith("/api/v1/projects/lab/sessions/session%2F1", undefined)
    expect(session.session.current_stage).toBe("clarifying_requirements")

    const nodeExplanation = await explainProjectLabNode("session/1", { node_id: "node-1", style: "plain" })
    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/projects/lab/sessions/session%2F1/explain-node",
      { node_id: "node-1", style: "plain" },
      undefined
    )
    expect(nodeExplanation.title).toBe("Queue boundary")

    const saved = await saveProjectLabSession("session/1", { status: "saved", note: "Keep for sprint planning" })
    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/projects/lab/sessions/session%2F1/save",
      { status: "saved", note: "Keep for sprint planning" },
      undefined
    )
    expect(saved.session.status).toBe("saved")
  })

  it("normalizes unsupported Lab contract values and preserves readiness conflict details", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({
      ok: true,
      data: {
        session: {
          ...labSession("session-unknown"),
          current_stage: "future_stage",
          next_action: "future_action",
          can_generate_solution: true,
          unanswered_question_ids: [],
        },
      },
    })

    const session = await fetchProjectLabSession("session-unknown")
    expect(session.session.current_stage).toBe("unknown")
    expect(session.session.raw_current_stage).toBe("future_stage")
    expect(session.session.next_action).toBe("unknown")

    vi.mocked(apiPost).mockResolvedValueOnce({
      success: false,
      error: {
        code: "lab_session_not_ready",
        message: "Answer all required Lab questions before generating a solution.",
        details: { unanswered_question_ids: ["q-context"] },
        status: 409,
        user_action_required: true,
      },
    })

    await expect(generateProjectLabSolution("session-unknown")).rejects.toMatchObject({
      name: "ProjectsApiError",
      code: "lab_session_not_ready",
      status: 409,
      detail: { unanswered_question_ids: ["q-context"] },
      userActionRequired: true,
    } satisfies Partial<ProjectsApiError>)
  })

  it("uses Projects API v1 collection mutation routes", async () => {
    vi.mocked(apiPost)
      .mockResolvedValueOnce({
        success: true,
        data: {
          collection: apiCollection("newsroom-agents"),
          meta: readyMeta(),
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: {
          collection: { ...apiCollection("newsroom-agents"), item_count: 2 },
          meta: readyMeta(),
        },
      })
      .mockResolvedValueOnce({
        success: true,
        data: {
          collection: apiCollection("generated-rag"),
          meta: readyMeta(),
        },
      })

    const created = await createProjectCollection({
      title: "Newsroom Agents",
      description: "Production agent projects",
      tags: ["agent"],
      target_audience: ["editorial engineering"],
      learning_goals: ["Evaluate orchestration fit"],
    })
    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/projects/collections",
      {
        title: "Newsroom Agents",
        description: "Production agent projects",
        tags: ["agent"],
        target_audience: ["editorial engineering"],
        learning_goals: ["Evaluate orchestration fit"],
      },
      undefined
    )
    expect(created.collection.slug).toBe("newsroom-agents")

    const updated = await addProjectCollectionItem("collection/1", {
      item_type: "project",
      item_id: "project-1",
      title: "AgentKit",
      reason: "Representative orchestration project",
      order: 1,
      difficulty: "medium",
      recommended_action: "prototype",
    })
    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/projects/collections/collection%2F1/items",
      {
        item_type: "project",
        item_id: "project-1",
        title: "AgentKit",
        reason: "Representative orchestration project",
        order: 1,
        difficulty: "medium",
        recommended_action: "prototype",
      },
      undefined
    )
    expect(updated.collection.item_count).toBe(2)

    const generated = await generateProjectCollection({
      topic: "RAG operations",
      project_ids: ["project-1"],
      case_ids: ["case-1"],
      collection_type: "learning_path",
    })
    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/projects/collections/generate",
      {
        topic: "RAG operations",
        project_ids: ["project-1"],
        case_ids: ["case-1"],
        collection_type: "learning_path",
      },
      undefined
    )
    expect(generated.collection.slug).toBe("generated-rag")
  })

  it("covers Projects API v1 mutations", async () => {
    vi.mocked(apiPost)
      .mockResolvedValueOnce({ success: true, data: { ok: true } })
      .mockResolvedValueOnce({ success: true, data: { ok: true } })
      .mockResolvedValueOnce({ success: true, data: { session: labSession("session-1") } })
      .mockResolvedValueOnce({ success: true, data: { session: labSession("session-1") } })
      .mockResolvedValueOnce({ success: true, data: { session: labSession("session-1"), solution: {} } })
      .mockResolvedValue({ success: true, data: { ok: true } })
    vi.mocked(apiPatch).mockResolvedValue({ success: true, data: { item: { id: "watch-1" } } })
    vi.mocked(apiDelete).mockResolvedValue({ success: true, data: { deleted: true, item_id: "watch-1" } })

    await compareProjectTools({ project_ids: ["project-1"] })
    expect(apiPost).toHaveBeenCalledWith("/api/v1/projects/tools/compare", { project_ids: ["project-1"] }, undefined)

    await recommendProjectTools({ problem: "Need workflow", limit: 1 })
    expect(apiPost).toHaveBeenCalledWith("/api/v1/projects/tools/recommend", { problem: "Need workflow", limit: 1 }, undefined)

    await startProjectLabSession({ user_problem: "Need workflow" })
    expect(apiPost).toHaveBeenCalledWith("/api/v1/projects/lab/sessions", { user_problem: "Need workflow" }, undefined)

    await answerProjectLabQuestion("session/1", { question_id: "q1", answer: "API" })
    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/projects/lab/sessions/session%2F1/answer",
      { question_id: "q1", answer: "API" },
      undefined
    )

    await generateProjectLabSolution("session/1")
    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/projects/lab/sessions/session%2F1/generate-solution",
      undefined,
      undefined
    )

    await addProjectWatchlistItem({ project_id: "project-1", watch_reason: "Track releases" })
    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/projects/watchlist",
      { project_id: "project-1", watch_reason: "Track releases" },
      undefined
    )

    await patchProjectWatchlistItem("watch/1", { priority: "high" })
    expect(apiPatch).toHaveBeenCalledWith("/api/v1/projects/watchlist/watch%2F1", { priority: "high" }, undefined)

    await deleteProjectWatchlistItem("watch/1")
    expect(apiDelete).toHaveBeenCalledWith("/api/v1/projects/watchlist/watch%2F1", undefined)

    await recordProjectInteraction({ event_type: "view", target_type: "project", target_id: "project-1" })
    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/projects/interactions",
      { event_type: "view", target_type: "project", target_id: "project-1" },
      undefined
    )
  })

  it("uses Projects API v1 watchlist refresh route", async () => {
    vi.mocked(apiPost).mockResolvedValueOnce({
      ok: true,
      data: {
        item: {
          id: "watch-1",
          project_id: "project-1",
          watch_reason: "Track releases",
          priority: "high",
          status: "active",
        },
        signals: [{ type: "release", title: "New release" }],
        meta: readyMeta(),
      },
    })

    const refreshed = await refreshProjectWatchlistItem("watch/1")
    expect(apiPost).toHaveBeenCalledWith("/api/v1/projects/watchlist/watch%2F1/refresh", undefined, undefined)
    expect(refreshed.signals).toHaveLength(1)
  })
})

function readyMeta() {
  return { source: "artifact", source_run_id: "run-project-radar", data_state: "ready", notices: [] }
}

function apiProject(id: string) {
  return {
    id,
    slug: id,
    name: "AgentKit",
    description: "Real Project Radar project.",
    github_url: "https://github.com/acme/agentkit",
    project_type: "tool",
    tags: ["agent"],
    source_confidence: 0.9,
    hot_score: 0.8,
    metric_summary: { github_stars: 100, github_forks: 5, stars_delta_7d: 10 },
    capability_count: 1,
    case_count: 1,
    source_count: 1,
  }
}

function apiTool(id: string) {
  return {
    project: apiProject(id),
    profile: {
      project_id: id,
      tool_type: "agent_runtime",
      input_types: ["text"],
      output_types: ["workflow"],
      is_open_source: true,
      license: "MIT",
      local_deployable: true,
      has_api: true,
      has_cli: true,
      has_python_sdk: true,
      has_docker: true,
      integration_difficulty: "medium",
      recommended_integration: "wrap_as_service",
      target_modules: ["collection"],
      setup_commands: ["pip install agentkit"],
      usage_example: "agentkit run",
      known_limits: ["Requires queue tuning"],
      experiment_status: "runnable",
    },
    capabilities: [],
    fit_reason: "Matches workflow orchestration needs.",
  }
}

function apiCase(id: string) {
  return {
    id,
    project_id: "project-1",
    title: "Workflow case",
    business_domain: "newsroom",
    module_type: "collection",
    problem: "Coordinate ingestion and analysis.",
    design_summary: "Use an explicit orchestration boundary.",
  }
}

function apiCollection(slug: string) {
  return {
    id: slug,
    slug,
    title: "Agent Collections",
    description: "Curated real Project Radar projects.",
    item_count: 1,
  }
}

function labSession(id: string) {
  return {
    id,
    user_problem: "Need a newsroom workflow module",
    selected_case_ids: ["case-1"],
    current_stage: "clarifying_requirements",
    next_action: "answer_question",
    can_generate_solution: false,
    unanswered_question_ids: ["q-context"],
    questions: [{ id: "q-context", question: "Which workflow stage needs help?", required: true }],
  }
}
