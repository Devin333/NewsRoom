"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"

export function JsonPreview({ value, label, defaultOpen = false }: { value?: unknown; label: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)

  if (value === undefined) {
    return (
      <div className="rounded-md border border-border bg-secondary/40 p-3 text-sm text-muted-foreground">
        {label}：无
      </div>
    )
  }

  const json = typeof value === "string" ? value : JSON.stringify(value, null, 2)
  const preview = json.length > 600 && !open ? `${json.slice(0, 600)}\n...` : json

  return (
    <section className="rounded-md border border-border bg-secondary/40">
      <div className="flex items-center justify-between gap-3 border-b border-border px-3 py-2">
        <p className="text-xs font-medium uppercase tracking-normal text-muted-foreground">{label}</p>
        <Button type="button" variant="ghost" size="sm" onClick={() => setOpen((value) => !value)}>
          {open ? "收起" : "展开"}
        </Button>
      </div>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words p-3 text-xs leading-5 text-foreground">{preview}</pre>
    </section>
  )
}
