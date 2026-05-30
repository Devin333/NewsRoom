"use client"

import { useState } from "react"
import { useToast } from "@/components/common/Toast"

export function ReportExportBar({ reportId, title, markdown }: { reportId: string; title: string; markdown: string }) {
  const toast = useToast()
  const [copied, setCopied] = useState(false)

  function download() {
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${reportId}.md`
    a.click()
    URL.revokeObjectURL(url)
    toast("Downloaded", "success")
  }

  async function copy() {
    await navigator.clipboard.writeText(markdown)
    setCopied(true)
    toast("Copied to clipboard", "success")
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="flex gap-2">
      <button
        onClick={copy}
        className="rounded-md border border-line bg-white px-3 py-1.5 text-xs font-medium text-ink transition-colors hover:bg-surface"
      >
        {copied ? "Copied ✓" : "Copy"}
      </button>
      <button
        onClick={download}
        className="rounded-md border border-line bg-white px-3 py-1.5 text-xs font-medium text-ink transition-colors hover:bg-surface"
      >
        Download .md
      </button>
    </div>
  )
}
