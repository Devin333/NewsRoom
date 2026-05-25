import { afterEach, describe, expect, it } from "vitest"
import { defaultPostLoginPath, getFrontendSurface, resolveFrontendSurface } from "@/lib/frontend-surface"

describe("frontend surface helpers", () => {
  const originalSurface = process.env.NEWSROOM_FRONTEND_SURFACE

  afterEach(() => {
    if (originalSurface === undefined) {
      delete process.env.NEWSROOM_FRONTEND_SURFACE
      return
    }
    process.env.NEWSROOM_FRONTEND_SURFACE = originalSurface
  })

  it("defaults missing and invalid surface values to portal", () => {
    expect(resolveFrontendSurface()).toBe("portal")
    expect(resolveFrontendSurface("portal")).toBe("portal")
    expect(resolveFrontendSurface("unknown")).toBe("portal")
  })

  it("resolves admin surface and default post-login path", () => {
    process.env.NEWSROOM_FRONTEND_SURFACE = "admin"

    expect(getFrontendSurface()).toBe("admin")
    expect(defaultPostLoginPath()).toBe("/")
    expect(defaultPostLoginPath("portal")).toBe("/papers")
  })
})
