import { describe, expect, it } from "vitest"
import {
  getStudioNavigationItems,
  studioModuleEntries,
  studioNavigationGroups
} from "@/features/studio/shared/lib/studio-navigation"

describe("studio navigation", () => {
  it("contains only routable Studio entries for Task A", () => {
    const hrefs = getStudioNavigationItems().map((item) => item.href)

    expect(hrefs).toEqual([
      "/studio/runs",
      "/studio/artifacts",
      "/studio/boards",
      "/studio/evidence",
      "/studio/quality",
      "/studio/review",
      "/studio/sources"
    ])
  })

  it("keeps every navigation href under /studio", () => {
    expect(getStudioNavigationItems().every((item) => item.href.startsWith("/studio"))).toBe(true)
  })

  it("groups the existing routes by shell section", () => {
    expect(studioNavigationGroups.map((group) => group.label)).toEqual([
      "Runtime",
      "Business",
      "Governance",
      "System"
    ])
  })

  it("module cards point to existing routes", () => {
    const moduleHrefs = studioModuleEntries.map((entry) => entry.href)

    expect(moduleHrefs).toEqual([
      "/studio/runs",
      "/studio/boards",
      "/studio/evidence",
      "/studio/artifacts",
      "/studio/quality",
      "/studio/review",
      "/studio/sources"
    ])
  })
})
