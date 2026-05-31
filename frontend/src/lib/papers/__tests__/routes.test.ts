import { describe, expect, it } from "vitest"
import { papersRoutes } from "@/lib/papers/routes"

describe("paper module routes", () => {
  it("encodes dynamic task and method slugs consistently", () => {
    expect(papersRoutes.taskDetail("agent planning/v2")).toBe("/papers/tasks/agent%20planning%2Fv2")
    expect(papersRoutes.methodDetail("tool use/v2")).toBe("/papers/methods/tool%20use%2Fv2")
  })
})
