import { describe, expect, it } from "vitest"
import { normalizePdfUrl, paperPdfUrlFromSource } from "@/lib/papers/format"

describe("paper PDF URL helpers", () => {
  it("derives arXiv PDF URLs", () => {
    expect(paperPdfUrlFromSource("https://arxiv.org/abs/2508.03680")).toBe("https://arxiv.org/pdf/2508.03680.pdf")
    expect(paperPdfUrlFromSource("http://arxiv.org/pdf/2508.03680")).toBe("https://arxiv.org/pdf/2508.03680.pdf")
  })

  it("derives PDF URLs for common paper sites", () => {
    expect(paperPdfUrlFromSource("https://openreview.net/forum?id=abc123")).toBe("https://openreview.net/pdf?id=abc123")
    expect(paperPdfUrlFromSource("https://aclanthology.org/2024.acl-long.1/")).toBe("https://aclanthology.org/2024.acl-long.1.pdf")
    expect(paperPdfUrlFromSource("https://proceedings.mlr.press/v202/lee23g.html")).toBe("https://proceedings.mlr.press/v202/lee23g/lee23g.pdf")
    expect(paperPdfUrlFromSource("https://openaccess.thecvf.com/content/CVPR2024/html/Li_Example_Paper_CVPR_2024_paper.html")).toBe(
      "https://openaccess.thecvf.com/content/CVPR2024/papers/Li_Example_Paper_CVPR_2024_paper.pdf"
    )
  })

  it("only accepts explicit PDF URLs when a source cannot be safely inferred", () => {
    expect(normalizePdfUrl("https://papers.nips.cc/paper_files/paper/2024/file/example-Paper-Conference.pdf")).toBe(
      "https://papers.nips.cc/paper_files/paper/2024/file/example-Paper-Conference.pdf"
    )
    expect(normalizePdfUrl("https://example.com/paper.html")).toBeUndefined()
    expect(paperPdfUrlFromSource("https://example.com/paper.html")).toBeUndefined()
  })
})
