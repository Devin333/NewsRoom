const statusMap: Record<string, { dot: string; text: string; bg: string }> = {
  ok:          { dot: "bg-good",   text: "text-good",   bg: "bg-good/8 border-good/20" },
  healthy:     { dot: "bg-good",   text: "text-good",   bg: "bg-good/8 border-good/20" },
  succeeded:   { dot: "bg-good",   text: "text-good",   bg: "bg-good/8 border-good/20" },
  ready:       { dot: "bg-good",   text: "text-good",   bg: "bg-good/8 border-good/20" },
  running:     { dot: "bg-accent", text: "text-accent", bg: "bg-accent/8 border-accent/20" },
  queued:      { dot: "bg-accent", text: "text-accent", bg: "bg-accent/8 border-accent/20" },
  accepted:    { dot: "bg-accent", text: "text-accent", bg: "bg-accent/8 border-accent/20" },
  blocked:     { dot: "bg-warn",   text: "text-warn",   bg: "bg-warn/8 border-warn/20" },
  failed:      { dot: "bg-bad",    text: "text-bad",    bg: "bg-bad/8 border-bad/20" },
  unavailable: { dot: "bg-bad",    text: "text-bad",    bg: "bg-bad/8 border-bad/20" },
  cancelled:   { dot: "bg-subtle", text: "text-muted",  bg: "bg-surface border-line" },
}

export function StatusBadge({ status }: { status: string }) {
  const s = statusMap[status.toLowerCase()] ?? { dot: "bg-subtle", text: "text-muted", bg: "bg-surface border-line" }
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium ${s.bg} ${s.text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {status}
    </span>
  )
}
