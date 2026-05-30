import { MemorySearchBox } from "@/components/memory/MemorySearchBox"

export default function MemoryPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-ink">Memory</h1>
        <p className="mt-0.5 text-sm text-muted">Search indexed report memory</p>
      </div>
      <div className="rounded-xl border border-line bg-white p-5 shadow-card">
        <MemorySearchBox />
      </div>
    </div>
  )
}
