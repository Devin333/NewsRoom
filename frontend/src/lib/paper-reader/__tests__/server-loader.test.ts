import { describe, expect, it, vi, beforeEach } from "vitest"
import { safeApiGet } from "@/lib/api/server"
import { getPaperById } from "@/lib/papers/real-data"
import type { Paper } from "@/lib/papers/types"
import { loadPaperCompileStatus, loadPaperDocumentPayload } from "@/lib/paper-reader/server-loader"
import type { PaperDocumentResponse } from "@/lib/paper-reader/types"

vi.mock("@/lib/api/server", () => ({
  safeApiGet: vi.fn(),
}))

vi.mock("@/lib/papers/real-data", () => ({
  getPaperById: vi.fn(),
}))

const paper: Paper = {
  id: "arxiv-2605.26111v1",
  slug: "squeezing-capacity-from-multimodal-large-language-models-for-subject-driven-gene",
  title: "Squeezing Capacity from Multimodal Large Language Models for Subject-driven Generation",
  abstractSnippet: "Real abstract from the paper index.",
  authors: ["A"],
  publishedAt: "2026-05-25T17:59:35Z",
  venue: "arXiv",
  tags: ["cs.CV"],
  taskRefs: [],
  methodRefs: [],
  paperUrl: "https://arxiv.org/abs/2605.26111v1",
  pdfUrl: "https://arxiv.org/pdf/2605.26111v1.pdf",
  isPublished: true,
}

const compiledPayload: PaperDocumentResponse = {
  paper,
  status: {
    paperId: paper.id,
    status: "compiled",
    updatedAt: "2026-05-28T00:00:00Z",
    diagnostics: [],
  },
  document: {
    paperId: paper.id,
    schemaVersion: "paper_document_v1",
    status: "compiled",
    title: paper.title,
    compiledAt: "2026-05-28T00:00:00Z",
    sourceHash: "hash",
    paper: { id: paper.id, title: paper.title },
    outline: [],
    blocks: [],
  },
  manifest: {
    paperId: paper.id,
    schemaVersion: "paper_document_v1",
    createdAt: "2026-05-28T00:00:00Z",
    sourceHash: "hash",
    assets: [],
  },
}

describe("paper reader server loader", () => {
  beforeEach(() => {
    vi.mocked(safeApiGet).mockReset()
    vi.mocked(getPaperById).mockReset()
  })

  it("returns the published document when the visual compiler API has it", async () => {
    vi.mocked(safeApiGet).mockResolvedValueOnce({ ok: true, data: compiledPayload })

    await expect(loadPaperDocumentPayload(paper.slug)).resolves.toBe(compiledPayload)
    expect(getPaperById).not.toHaveBeenCalled()
  })

  it("resolves a slug to the real paper id before retrying the document endpoint", async () => {
    vi.mocked(safeApiGet)
      .mockResolvedValueOnce({ ok: false, errorCode: "paper_not_found", errorMessage: "paper was not found" })
      .mockResolvedValueOnce({ ok: true, data: compiledPayload })
    vi.mocked(getPaperById).mockResolvedValueOnce(paper)

    await expect(loadPaperDocumentPayload(paper.slug)).resolves.toBe(compiledPayload)
    expect(safeApiGet).toHaveBeenNthCalledWith(
      2,
      `/api/v1/papers/${encodeURIComponent(paper.id)}/document`,
    )
  })

  it("builds a non-body fallback payload when the compiler endpoints are unavailable", async () => {
    vi.mocked(safeApiGet)
      .mockResolvedValueOnce({ ok: false, errorCode: "not_found", errorMessage: "Not Found" })
      .mockResolvedValueOnce({ ok: false, errorCode: "not_found", errorMessage: "Not Found" })
      .mockResolvedValueOnce({ ok: false, errorCode: "not_found", errorMessage: "Not Found" })
    vi.mocked(getPaperById).mockResolvedValue(paper)

    const payload = await loadPaperDocumentPayload(paper.slug)

    expect(payload).toMatchObject({
      paper: { id: paper.id },
      document: null,
      manifest: null,
      status: {
        paperId: paper.id,
        status: "queued",
        diagnostics: [{ code: "not_found", message: "Not Found" }],
      },
    })
    expect(payload?.ai?.signals?.abstractSnippet).toBe(paper.abstractSnippet)
  })

  it("returns null when neither id nor slug matches a real paper", async () => {
    vi.mocked(safeApiGet).mockResolvedValueOnce({ ok: false, errorCode: "paper_not_found", errorMessage: "missing" })
    vi.mocked(getPaperById).mockResolvedValueOnce(null)

    await expect(loadPaperDocumentPayload("missing-paper")).resolves.toBeNull()
  })

  it("returns fallback compile status for known papers when status endpoint is unavailable", async () => {
    vi.mocked(getPaperById).mockResolvedValueOnce(paper)
    vi.mocked(safeApiGet).mockResolvedValueOnce({ ok: false, errorCode: "not_found", errorMessage: "Not Found" })

    const status = await loadPaperCompileStatus(paper.slug)

    expect(status).toMatchObject({
      paperId: paper.id,
      status: "queued",
      diagnostics: [{ code: "not_found", message: "Not Found" }],
    })
  })
})
