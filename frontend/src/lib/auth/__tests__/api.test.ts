import { beforeEach, describe, expect, it, vi } from "vitest"
import { apiGet, apiPost } from "@/lib/api/client"
import { bootstrapAccount, fetchAuthSession, login, logout } from "@/lib/auth/api"

vi.mock("@/lib/api/client", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn()
}))

describe("auth API client", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset()
    vi.mocked(apiPost).mockReset()
  })

  it("uses auth BFF routes for session, bootstrap, login, and logout", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({ success: true, data: { initialized: true, session: null } })
    await fetchAuthSession()
    expect(apiGet).toHaveBeenCalledWith("/api/auth/session", undefined)

    vi.mocked(apiPost).mockResolvedValueOnce({
      success: true,
      data: {
        session: {
          user: { userId: "user-1", username: "admin", role: "admin" },
          sessionId: "sess-1",
          expiresAt: "2026-06-01T00:00:00Z"
        }
      }
    })
    await bootstrapAccount("admin", "correct horse")
    expect(apiPost).toHaveBeenCalledWith(
      "/api/auth/bootstrap",
      { username: "admin", password: "correct horse" },
      undefined
    )

    vi.mocked(apiPost).mockResolvedValueOnce({
      success: true,
      data: {
        session: {
          user: { userId: "user-1", username: "admin", role: "admin" },
          sessionId: "sess-2",
          expiresAt: "2026-06-01T00:00:00Z"
        }
      }
    })
    await login("admin", "correct horse")
    expect(apiPost).toHaveBeenCalledWith(
      "/api/auth/login",
      { username: "admin", password: "correct horse" },
      undefined
    )

    vi.mocked(apiPost).mockResolvedValueOnce({ success: true, data: { revoked: true } })
    await logout()
    expect(apiPost).toHaveBeenCalledWith("/api/auth/logout", undefined, undefined)
  })

  it("surfaces auth errors without raw backend payloads", async () => {
    vi.mocked(apiPost).mockResolvedValueOnce({
      success: false,
      error: {
        code: "auth_invalid_credentials",
        message: "invalid username or password",
        requestId: "req-1"
      }
    })

    await expect(login("admin", "wrong horse")).rejects.toThrow("invalid username or password")
  })
})
