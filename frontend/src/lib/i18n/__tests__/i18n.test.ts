import { describe, expect, it } from "vitest"
import { createTranslator, formatDataState, formatDateTime, formatStatus, translate } from "@/lib/i18n"

describe("shared i18n helpers", () => {
  it("falls back to English or the key for missing translations", () => {
    expect(translate("zh", "common.search")).toBe("搜索")
    expect(translate("zh", "not.real.key")).toBe("not.real.key")
  })

  it("interpolates named params", () => {
    const t = createTranslator("zh")
    expect(t("portal.news.showing", { shown: 3, total: 12 })).toBe("已显示 3 / 12 条匹配新闻")
  })

  it("formats statuses and data states for both locales", () => {
    expect(formatStatus("zh", "running")).toBe("运行中")
    expect(formatStatus("en", "running")).toBe("Running")
    expect(formatDataState("zh", "partial")).toBe("部分可用")
    expect(formatDataState("en", "fallback")).toBe("Fallback")
  })

  it("formats dates by locale and preserves invalid values", () => {
    expect(formatDateTime("zh", "2026-05-25T12:00:00Z")).toContain("2026")
    expect(formatDateTime("en", "2026-05-25T12:00:00Z")).toMatch(/2026|May/)
    expect(formatDateTime("zh", "not-a-date")).toBe("not-a-date")
    expect(formatDateTime("zh", null)).toBe("--")
  })
})
