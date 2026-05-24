import { beforeEach, describe, expect, it, vi } from "vitest"
import {
  clearPaperEnrichmentCache,
  enrichPapersForPublicStream,
  fetchOpenAlexCitation,
  githubRepoSlug,
  normalizeGithubRepoUrl
} from "@/lib/papers/enrichment"
import type { Paper } from "@/lib/papers/types"

const basePaper: Paper = {
  id: "paper-test",
  slug: "test-paper",
  title: "SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering",
  abstractSnippet: "A real paper with a real repository.",
  authors: ["John Yang"],
  publishedAt: "2024-05-06",
  citationDoi: "10.48550/arxiv.2405.15793",
  tags: ["agents"],
  taskRefs: [],
  methodRefs: [],
  repoUrl: "https://github.com/SWE-agent/SWE-agent",
  pdfUrl: "https://arxiv.org/pdf/2405.15793.pdf",
  isPublished: true
}

beforeEach(() => {
  clearPaperEnrichmentCache()
})

describe("GitHub repo URL handling", () => {
  it("accepts real owner/repo URLs and rejects the GitHub root", () => {
    expect(githubRepoSlug("https://github.com/SWE-agent/SWE-agent")).toBe("SWE-agent/SWE-agent")
    expect(githubRepoSlug("SWE-agent/SWE-agent")).toBe("SWE-agent/SWE-agent")
    expect(normalizeGithubRepoUrl("https://github.com/SWE-agent/SWE-agent")).toBe("https://github.com/SWE-agent/SWE-agent")
    expect(normalizeGithubRepoUrl("https://github.com/")).toBeUndefined()
    expect(normalizeGithubRepoUrl("https://example.com/SWE-agent/SWE-agent")).toBeUndefined()
  })
})

describe("OpenAlex citation lookup", () => {
  it("uses a DOI-backed OpenAlex work and validates the returned title", async () => {
    const fetchImpl = vi.fn(async () =>
      new Response(
        JSON.stringify({
          id: "https://openalex.org/W4405451285",
          display_name: basePaper.title,
          cited_by_count: 24
        }),
        { status: 200 }
      )
    )

    await expect(fetchOpenAlexCitation(basePaper, fetchImpl)).resolves.toEqual({
      citationCount: 24,
      openAlexId: "https://openalex.org/W4405451285"
    })
    expect(fetchImpl).toHaveBeenCalledWith(
      "https://api.openalex.org/works/https%3A%2F%2Fdoi.org%2F10.48550%2Farxiv.2405.15793",
      expect.any(Object)
    )
  })
})

describe("public paper enrichment", () => {
  it("keeps only papers with a verified GitHub repo and OpenAlex citation", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = input.toString()
      if (url.includes("api.github.com/repos/SWE-agent/SWE-agent")) {
        return new Response(
          JSON.stringify({
            full_name: "SWE-agent/SWE-agent",
            html_url: "https://github.com/SWE-agent/SWE-agent",
            stargazers_count: 19281
          }),
          { status: 200 }
        )
      }

      if (url.includes("api.openalex.org/works/")) {
        return new Response(
          JSON.stringify({
            id: "https://openalex.org/W4405451285",
            display_name: basePaper.title,
            cited_by_count: 24
          }),
          { status: 200 }
        )
      }

      return new Response("{}", { status: 404 })
    })

    const papers = await enrichPapersForPublicStream([
      basePaper,
      { ...basePaper, id: "paper-without-repo", repoUrl: undefined },
      { ...basePaper, id: "paper-root-repo", repoUrl: "https://github.com/" }
    ], fetchImpl)

    expect(papers).toHaveLength(1)
    expect(papers[0]).toMatchObject({
      repoUrl: "https://github.com/SWE-agent/SWE-agent",
      githubStars: 19281,
      citationCount: 24,
      starsPerHour: undefined
    })
  })
})
