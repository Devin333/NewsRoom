import type { RunArtifact } from "@/lib/types"

function fmtBytes(n: number | null | undefined) {
  if (!n) return "—"
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function RunArtifacts({ artifacts }: { artifacts: RunArtifact[] }) {
  if (!artifacts.length) return <p className="text-sm text-muted">No artifacts.</p>
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-line">
          <th className="pb-3 pr-4 text-left text-xs font-medium text-muted">Key</th>
          <th className="pb-3 pr-4 text-left text-xs font-medium text-muted">Path</th>
          <th className="pb-3 pr-4 text-left text-xs font-medium text-muted">Type</th>
          <th className="pb-3 text-right text-xs font-medium text-muted">Size</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {artifacts.map((a) => (
          <tr key={a.artifact_key}>
            <td className="py-2.5 pr-4 font-mono text-xs text-ink">{a.artifact_key}</td>
            <td className="py-2.5 pr-4 font-mono text-xs text-muted">{a.relative_path ?? "—"}</td>
            <td className="py-2.5 pr-4 text-xs text-muted">{a.content_type ?? "—"}</td>
            <td className="py-2.5 text-right font-mono text-xs text-muted">{fmtBytes(a.size_bytes)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
