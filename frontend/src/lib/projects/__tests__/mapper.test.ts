import { describe, expect, it } from "vitest"
import { buildProjectListResult, mapProjectPayload, normalizeGitHubRepoUrl } from "@/lib/projects/mapper"

describe("project radar mapper", () => {
  it("maps project_radar payloads to public GitHub projects without defaulting missing stars", () => {
    const payload = {
      board_type: "project_radar",
      cards: [
        {
          card_id: "card-codex",
          name: "codex",
          repo_full_name: "openai/codex",
          description: "A coding agent that runs in your terminal.",
          language: "TypeScript",
          star_growth_7d: 120,
          quality: { score: 0.92 },
          tags: ["agent", "devtool"],
          evidence_refs: [
            {
              external_id: "ev-1",
              source_name: "GitHub",
              source_type: "github",
              url: "https://github.com/openai/codex",
            },
          ],
        },
      ],
    }

    const result = mapProjectPayload(payload)

    expect(result.items).toHaveLength(1)
    expect(result.items[0]).toMatchObject({
      id: "card-codex",
      slug: "openai-codex",
      fullName: "openai/codex",
      repoUrl: "https://github.com/openai/codex",
      owner: "openai",
      language: "TypeScript",
      starGrowth7d: 120,
      qualityScore: 0.92,
      categories: ["agent_framework", "coding"],
      relationCounts: { papers: 0, news: 1, community: 0 },
    })
    expect(result.items[0].stars).toBeUndefined()
    expect(JSON.stringify(result.items[0])).not.toMatch(/raw_payload|raw_html|token|secret/i)
  })

  it("skips records that do not have a legal GitHub repo URL", () => {
    const result = mapProjectPayload({
      cards: [
        {
          card_id: "bad",
          title: "not a repo",
          source_url: "https://openai.com/index/example",
          raw_payload: { token: "do-not-leak" },
        },
      ],
    })

    expect(result.items).toHaveLength(0)
    expect(result.notices.join(" ")).toContain("GitHub")
  })

  it("filters, sorts, and paginates mapped projects", () => {
    const payload = {
      cards: [
        {
          card_id: "agent",
          name: "AgentKit",
          repo_url: "https://github.com/acme/agentkit",
          description: "Agent workflow toolkit",
          language: "Python",
          stars: 100,
          starGrowth7d: 20,
          tags: ["agent"],
        },
        {
          card_id: "rag",
          name: "RagStore",
          repo_url: "https://github.com/acme/ragstore",
          description: "RAG data layer",
          language: "Rust",
          stars: 300,
          starGrowth7d: 5,
          tags: ["rag"],
        },
      ],
    }

    const result = buildProjectListResult(payload, { category: "agent", sort: "growth", page: 1, pageSize: 1 }, { source: "artifact" })

    expect(result.items).toHaveLength(1)
    expect(result.items[0].name).toBe("AgentKit")
    expect(result.page).toMatchObject({ page: 1, pageSize: 1, total: 1, hasNext: false })
    expect(result.options.categories.map((option) => option.value)).toEqual(["agent_framework", "rag"])
  })

  it("supports PRD aliases for topic, period, maturity, activity sort, and limit", () => {
    const now = new Date().toISOString()
    const payload = {
      cards: [
        {
          card_id: "active-agent",
          name: "ActiveAgent",
          repo_url: "https://github.com/acme/active-agent",
          description: "Agent workflow toolkit",
          language: "Python",
          stars: 100,
          star_growth_7d: 20,
          pushed_at: now,
          tags: ["agent"],
        },
        {
          card_id: "old-rag",
          name: "OldRag",
          repo_url: "https://github.com/acme/old-rag",
          description: "RAG data layer",
          language: "Rust",
          stars: 300,
          pushed_at: "2020-01-01T00:00:00Z",
          tags: ["rag"],
        },
      ],
    }

    const result = buildProjectListResult(
      payload,
      { topic: "agent", period: "weekly", maturity: "rising", sort: "activity", limit: 1 },
      { source: "artifact" }
    )

    expect(result.items).toHaveLength(1)
    expect(result.items[0].name).toBe("ActiveAgent")
    expect(result.items[0].maturity).toBe("rising")
    expect(result.page.pageSize).toBe(1)
    expect(result.options.maturity.map((option) => option.value)).toContain("rising")
  })

  it("normalizes only full HTTPS GitHub repository URLs", () => {
    expect(normalizeGitHubRepoUrl("https://github.com/openai/codex")?.url).toBe("https://github.com/openai/codex")
    expect(normalizeGitHubRepoUrl("github.com/openai/codex.git")?.url).toBe("https://github.com/openai/codex")
    expect(normalizeGitHubRepoUrl("https://github.com/")).toBeNull()
    expect(normalizeGitHubRepoUrl("http://github.com/openai/codex")).toBeNull()
  })
})
