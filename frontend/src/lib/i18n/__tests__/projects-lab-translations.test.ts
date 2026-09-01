import { describe, expect, it } from "vitest"
import { translate } from "@/lib/i18n"

const labKeys = [
  "projects.lab.workspace",
  "projects.lab.startSession",
  "projects.lab.generateSolution",
  "projects.lab.questions",
  "projects.lab.context",
  "projects.lab.summary",
  "projects.lab.structured",
  "projects.lab.evidence",
  "projects.lab.saveSession",
  "projects.lab.saveFailed",
] as const

describe("Projects Lab translations", () => {
  it("provides touched Lab labels in both supported locales", () => {
    for (const key of labKeys) {
      expect(translate("en", key)).not.toBe(key)
      expect(translate("zh", key)).not.toBe(key)
    }
  })
})
