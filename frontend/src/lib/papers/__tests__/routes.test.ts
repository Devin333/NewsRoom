import { describe, expect, it } from "vitest"
import { decodePaperRouteSlug, papersRoutes } from "@/lib/papers/routes"

describe("paper module routes", () => {
  it("encodes dynamic task and method slugs consistently", () => {
    expect(papersRoutes.detail("agent paper/v2")).toBe("/papers/agent%20paper%2Fv2")
    expect(papersRoutes.reader("agent paper/v2")).toBe("/papers/agent%20paper%2Fv2/read")
    expect(papersRoutes.taskDetail("agent planning/v2")).toBe("/papers/tasks/agent%20planning%2Fv2")
    expect(papersRoutes.methodDetail("tool use/v2")).toBe("/papers/methods/tool%20use%2Fv2")
  })

  it("decodes route slugs defensively for dynamic detail pages", () => {
    expect(decodePaperRouteSlug("agent%20planning%2Fv2")).toBe("agent planning/v2")
    expect(decodePaperRouteSlug("bad%2")).toBe("bad%2")
  })
})
