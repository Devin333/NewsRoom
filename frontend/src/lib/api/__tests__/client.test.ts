import { afterEach, describe, expect, it, vi } from "vitest"
import { apiGet } from "@/lib/api/client"

const originalFetch = globalThis.fetch

describe("browser api client", () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
    globalThis.fetch = originalFetch
  })

  it("keeps Next BFF /api routes same-origin even when a public backend base URL is set", async () => {
    vi.stubEnv("NEXT_PUBLIC_NEWSROOM_API_BASE_URL", "http://127.0.0.1:8000")
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, data: { initialized: true } }))
    globalThis.fetch = fetchMock

    await apiGet("/api/auth/session")

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/session",
      expect.objectContaining({ method: "GET" })
    )
  })

  it("still supports explicit absolute URLs", async () => {
    vi.stubEnv("NEXT_PUBLIC_NEWSROOM_API_BASE_URL", "http://127.0.0.1:8000")
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, data: { ok: true } }))
    globalThis.fetch = fetchMock

    await apiGet("https://api.example.test/status")

    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/status",
      expect.objectContaining({ method: "GET" })
    )
  })
})

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "content-type": "application/json" }
  })
}
