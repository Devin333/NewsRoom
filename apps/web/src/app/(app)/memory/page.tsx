import { MemorySearchBox } from "@/components/memory/MemorySearchBox"

export default function MemoryPage() {
  return (
    <main className="space-y-6">
      <header className="border-b border-line pb-4">
        <h1 className="text-2xl font-semibold text-ink">Memory Search</h1>
        <p className="text-sm text-muted">Search indexed report memory by collection and limit.</p>
      </header>

      <MemorySearchBox />
    </main>
  )
}
