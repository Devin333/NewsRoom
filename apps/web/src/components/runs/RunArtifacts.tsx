import { EmptyState } from "@/components/common/EmptyState"
import { formatNumber } from "@/lib/format"
import type { RunArtifact } from "@/lib/types"

export function RunArtifacts({ artifacts }: { artifacts: RunArtifact[] }) {
  if (!artifacts.length) {
    return <EmptyState title="No artifacts" message="No artifact references were returned for this run." />
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-white">
      <table className="w-full table-fixed border-collapse text-left text-sm">
        <thead className="bg-surface text-xs uppercase text-muted">
          <tr>
            <th className="w-48 px-4 py-3 font-medium">Key</th>
            <th className="w-56 px-4 py-3 font-medium">Path</th>
            <th className="w-40 px-4 py-3 font-medium">Type</th>
            <th className="w-24 px-4 py-3 font-medium">Size</th>
          </tr>
        </thead>
        <tbody>
          {artifacts.map((artifact) => (
            <tr key={artifact.artifact_key} className="border-t border-line">
              <td className="truncate px-4 py-3 font-medium text-ink">{artifact.artifact_key}</td>
              <td className="truncate px-4 py-3 text-muted">{artifact.relative_path ?? "n/a"}</td>
              <td className="truncate px-4 py-3 text-muted">{artifact.content_type ?? "n/a"}</td>
              <td className="truncate px-4 py-3 text-muted">{formatNumber(artifact.size_bytes)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
