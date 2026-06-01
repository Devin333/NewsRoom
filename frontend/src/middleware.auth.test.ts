import { NextRequest } from "next/server"
import { afterEach, describe, expect, it } from "vitest"
import { middleware } from "@/middleware"

function request(path: string, cookie?: string) {
  return new NextRequest(`http://localhost${path}`, {
    headers: cookie ? { cookie } : undefined,
  })
}

describe("auth middleware", () => {
  const originalSurface = process.env.NEWSROOM_FRONTEND_SURFACE
  const originalPortalOrigin = process.env.NEWSROOM_PORTAL_ORIGIN
  const originalAdminOrigin = process.env.NEWSROOM_ADMIN_ORIGIN

  afterEach(() => {
    restoreEnv("NEWSROOM_FRONTEND_SURFACE", originalSurface)
    restoreEnv("NEWSROOM_PORTAL_ORIGIN", originalPortalOrigin)
    restoreEnv("NEWSROOM_ADMIN_ORIGIN", originalAdminOrigin)
  })

  it("keeps anonymous Research read routes public", () => {
    process.env.NEWSROOM_FRONTEND_SURFACE = "portal"

    expect(middleware(request("/papers")).headers.get("location")).toBeNull()
    expect(middleware(request("/papers/reader-paper?panel=summary")).headers.get("location")).toBeNull()
    expect(middleware(request("/papers/reader-paper/read")).headers.get("location")).toBeNull()
    expect(middleware(request("/papers/tasks/agents")).headers.get("location")).toBeNull()
    expect(middleware(request("/papers/methods/tool-use")).headers.get("location")).toBeNull()
  })

  it("allows protected routes when the session cookie exists", () => {
    process.env.NEWSROOM_FRONTEND_SURFACE = "portal"
    const response = middleware(request("/papers", "newsroom_session=session-token"))

    expect(response.headers.get("location")).toBeNull()
  })

  it("keeps the Portal root public", () => {
    process.env.NEWSROOM_FRONTEND_SURFACE = "portal"

    const response = middleware(request("/"))

    expect(response.headers.get("location")).toBeNull()
  })

  it("keeps login and auth APIs public", () => {
    expect(middleware(request("/login")).headers.get("location")).toBeNull()
    expect(middleware(request("/api/auth/session")).headers.get("location")).toBeNull()
  })

  it("redirects management routes away from the Portal surface", () => {
    process.env.NEWSROOM_FRONTEND_SURFACE = "portal"

    const response = middleware(request("/studio/runs"))

    expect(response.status).toBe(307)
    expect(response.headers.get("location")).toBe("http://localhost/")
  })

  it("redirects Portal routes away from the Admin surface when an origin is configured", () => {
    process.env.NEWSROOM_FRONTEND_SURFACE = "admin"
    process.env.NEWSROOM_PORTAL_ORIGIN = "http://localhost:3001"

    const response = middleware(request("/papers?period=weekly", "newsroom_session=session-token"))

    expect(response.status).toBe(307)
    expect(response.headers.get("location")).toBe("http://localhost:3001/papers?period=weekly")
  })

  it("protects Studio and Admin root in Admin surface mode", () => {
    process.env.NEWSROOM_FRONTEND_SURFACE = "admin"

    expect(middleware(request("/")).headers.get("location")).toBe("http://localhost/login?next=%2F")
    expect(middleware(request("/studio/runs")).headers.get("location")).toBe(
      "http://localhost/login?next=%2Fstudio%2Fruns"
    )
  })

  it("redirects authenticated Admin root to Studio", () => {
    process.env.NEWSROOM_FRONTEND_SURFACE = "admin"

    const response = middleware(request("/", "newsroom_session=session-token"))

    expect(response.headers.get("location")).toBe("http://localhost/studio")
  })
})

function restoreEnv(name: string, value: string | undefined) {
  if (value === undefined) {
    delete process.env[name]
    return
  }
  process.env[name] = value
}
