import { describe, expect, it } from "vitest"
import { paperAssetUrl, paperSourcePreviewUrl } from "@/lib/paper-reader/api"

describe("paper reader API URL helpers", () => {
  it("versions binary asset URLs with the artifact checksum", () => {
    expect(paperAssetUrl("paper 1", "asset/1", "sha256:abc 123")).toBe(
      "/api/papers/paper%201/assets/asset%2F1?v=sha256%3Aabc%20123",
    )
  })

  it("versions source preview URLs without dropping page and bbox parameters", () => {
    const url = paperSourcePreviewUrl(
      "paper-1",
      {
        pageNumber: 2,
        bbox: { x0: 1, y0: 2, x1: 30, y1: 40 },
      },
      "source-hash",
    )

    expect(url).toContain("/api/papers/paper-1/source-preview?page=2&bbox=")
    expect(url).toContain("&v=source-hash")
  })
})
