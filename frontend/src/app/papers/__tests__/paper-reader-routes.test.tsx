import type { ReactElement } from "react"
import { describe, expect, it, vi } from "vitest"
import PaperReaderRoute from "@/app/papers/[slug]/page"
import PaperDocumentReadRoute from "@/app/papers/[slug]/read/page"
import { loadPaperDocumentPayload } from "@/lib/paper-reader/server-loader"
import type { PaperDocumentResponse } from "@/lib/paper-reader/types"
import type { Paper } from "@/lib/papers/types"

vi.mock("next/navigation", () => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND")
  }),
  redirect: vi.fn((href: string) => {
    throw new Error(`NEXT_REDIRECT:${href}`)
  })
}))

vi.mock("@/lib/paper-reader/server-loader", () => ({
  loadPaperDocumentPayload: vi.fn()
}))

const paper: Paper = {
  id: "paper-special",
  slug: "agent paper/v2",
  title: "Agent Paper v2",
  abstractSnippet: "A published paper with a route-sensitive slug.",
  authors: ["NewsRoom"],
  publishedAt: "2026-05-30T00:00:00Z",
  tags: [],
  taskRefs: [],
  methodRefs: [],
  isPublished: true
}

const payload: PaperDocumentResponse = {
  paper,
  status: {
    paperId: paper.id,
    status: "queued",
    updatedAt: "2026-05-30T00:00:00Z",
    diagnostics: []
  },
  document: null,
  manifest: null,
  ai: {
    summary: null,
    signals: {
      abstractSnippet: paper.abstractSnippet,
      taskRefs: [],
      methodRefs: [],
      benchmarks: [],
      implementations: []
    },
    diagnostics: []
  }
}

describe("paper reader routes", () => {
  it("redirects encoded legacy reader slugs without double encoding", async () => {
    await expect(PaperReaderRoute({ params: { slug: "agent%20paper%2Fv2" } })).rejects.toThrow(
      "NEXT_REDIRECT:/papers/agent%20paper%2Fv2/read"
    )
  })

  it("loads document payloads with the decoded paper slug", async () => {
    vi.mocked(loadPaperDocumentPayload).mockResolvedValueOnce(payload)

    const element = await PaperDocumentReadRoute({ params: { slug: "agent%20paper%2Fv2" } }) as ReactElement<{
      payload: PaperDocumentResponse
    }>

    expect(loadPaperDocumentPayload).toHaveBeenCalledWith("agent paper/v2")
    expect(element.props.payload).toBe(payload)
  })
})
