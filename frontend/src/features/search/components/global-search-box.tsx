"use client"

import { Search } from "lucide-react"
import { useI18n } from "@/lib/i18n/use-i18n"

export function GlobalSearchBox({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const { locale } = useI18n()

  return (
    <label className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3">
      <Search className="h-5 w-5 text-muted-foreground" />
      <input
        className="w-full bg-transparent text-base outline-none placeholder:text-muted-foreground"
        placeholder={locale === "zh" ? "搜索新闻、主题、证据、报告、技术、记忆..." : "Search news, topics, evidence, reports, technology, memory..."}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}
