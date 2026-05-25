import { NextRequest } from "next/server"
import { describe, expect, it } from "vitest"
import { middleware } from "@/middleware"

function request(path: string, cookie?: string) {
  return new NextRequest(`http://localhost${path}`, {
    headers: cookie ? { cookie } : undefined,
  })
}

describe("auth middleware", () => {
  it("redirects anonymous Reader Portal requests to login", () => {
    const response = middleware(request("/papers/reader-paper?panel=summary"))

    expect(response.status).toBe(307)
    expect(response.headers.get("location")).toBe(
      "http://localhost/login?next=%2Fpapers%2Freader-paper%3Fpanel%3Dsummary"
    )
  })

  it("allows protected routes when the session cookie exists", () => {
    const response = middleware(request("/papers", "newsroom_session=session-token"))

    expect(response.headers.get("location")).toBeNull()
  })

  it("keeps login, auth APIs, and Studio unprotected in this slice", () => {
    expect(middleware(request("/login")).headers.get("location")).toBeNull()
    expect(middleware(request("/api/auth/session")).headers.get("location")).toBeNull()
    expect(middleware(request("/studio")).headers.get("location")).toBeNull()
  })
})
