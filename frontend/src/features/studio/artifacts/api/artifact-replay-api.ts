import { safeApiGet } from "@/lib/api/server"
import {
  fallbackRuns,
  mapArtifact,
  mapFallbackDetail,
  mapLineage,
  mapReplayBundle,
  mapRunSummary,
  buildRunDetail,
  type ApiArtifact,
  type ApiArtifactList,
  type ApiLineageResult,
  type ApiReplayBundle,
  type ApiRunDetail,
  type ApiRunList
} from "@/features/studio/artifacts/lib/artifact-adapter"
import type { StudioArtifactRunDetail, StudioArtifactRunSummary, StudioReplayBundle } from "@/types/artifact"

export async function getArtifactRunSummaries(): Promise<{
  runs: StudioArtifactRunSummary[]
  notices: string[]
}> {
  const runsResult = await safeApiGet<ApiRunList>("/api/v1/runs?limit=20")
  if (!runsResult.ok || !runsResult.data.runs?.length) {
    return {
      runs: fallbackRuns,
      notices: [
        runsResult.ok
          ? "API 未返回运行记录，当前显示 Artifact Replay 兜底数据。"
          : `API 不可用：${runsResult.errorMessage}。当前显示 Artifact Replay 兜底数据。`
      ]
    }
  }

  const sourceRuns = runsResult.data.runs.slice(0, 20)
  const hydratedRuns = await Promise.all(
    sourceRuns.slice(0, 12).map(async (run) => {
      const runId = run.run_id ?? run.id
      if (!runId) {
        return mapRunSummary(run, undefined, ["运行记录缺少 run_id，无法加载产物详情。"])
      }
      const encodedRunId = encodeURIComponent(runId)
      const [artifactsResult, replayResult] = await Promise.all([
        safeApiGet<ApiArtifactList>(`/api/v1/runs/${encodedRunId}/artifacts`),
        safeApiGet<ApiReplayBundle>(`/api/v1/runs/${encodedRunId}/replay`)
      ])
      const notices: string[] = []
      if (!artifactsResult.ok) notices.push(`artifacts API 失败：${artifactsResult.errorMessage}`)
      if (!replayResult.ok) notices.push(`replay API 失败：${replayResult.errorMessage}`)

      const replayPayload = replayResult.ok
        ? replayResult.data
        : artifactsResult.ok
          ? replayFromArtifactList(runId, artifactsResult.data)
          : undefined

      return mapRunSummary(run, replayPayload, notices)
    })
  )

  const unhydratedRuns = sourceRuns.slice(12).map((run) => mapRunSummary(run, undefined, ["列表页仅预取最近 12 条运行的 replay 摘要。"]))

  return {
    runs: [...hydratedRuns, ...unhydratedRuns],
    notices: ["已加载 API 运行记录；缺失的 replay/artifact 字段会显示局部兜底提示。"]
  }
}

export async function getArtifactRunDetail(runIdValue: string): Promise<StudioArtifactRunDetail> {
  const decodedRunId = decodeURIComponent(runIdValue)
  const encodedRunId = encodeURIComponent(decodedRunId)
  const [runResult, artifactsResult, replayResult, lineageResult] = await Promise.all([
    safeApiGet<ApiRunDetail>(`/api/v1/runs/${encodedRunId}`),
    safeApiGet<ApiArtifactList>(`/api/v1/runs/${encodedRunId}/artifacts`),
    safeApiGet<ApiReplayBundle>(`/api/v1/runs/${encodedRunId}/replay`),
    safeApiGet<ApiLineageResult>(`/api/v1/runs/${encodedRunId}/lineage`)
  ])

  if (!runResult.ok && !artifactsResult.ok && !replayResult.ok && !lineageResult.ok) {
    return mapFallbackDetail(decodedRunId)
  }

  const notices = apiFailureNotices({
    run: runResult,
    artifacts: artifactsResult,
    replay: replayResult,
    lineage: lineageResult
  })
  const replayPayload = replayResult.ok
    ? replayResult.data
    : artifactsResult.ok
      ? replayFromArtifactList(decodedRunId, artifactsResult.data)
      : undefined
  const replay = replayPayload
    ? mapReplayBundle(replayPayload, {
        partial: !replayResult.ok,
        notices: replayResult.ok ? [] : ["replay API 未返回完整 bundle，当前使用 artifacts 列表组成局部视图。"]
      })
    : undefined
  const artifacts = artifactsResult.ok
    ? artifactsResult.data.artifacts?.map((artifact) => mapArtifact(artifact, decodedRunId)) ?? []
    : replay?.artifacts ?? []
  const run = mapRunSummary(
    runResult.ok
      ? runResult.data
      : {
          run_id: decodedRunId,
          status: replay?.ready ? "succeeded" : "unknown",
          manifest_path: replay?.manifestPath,
          artifact_count: artifacts.length,
          event_count: replay?.eventCount
        },
    replayPayload,
    notices
  )

  return buildRunDetail({
    run,
    artifacts: mergeArtifactContent(artifacts, replay?.artifacts ?? []),
    replay,
    lineage: lineageResult.ok ? mapLineage(lineageResult.data, "upstream", decodedRunId) : [],
    notices,
    dataState: notices.length ? "partial" : "ready"
  })
}

export async function getArtifactRunDetailWithArtifact(
  runIdValue: string,
  artifactKeyValue: string
): Promise<StudioArtifactRunDetail> {
  const decodedRunId = decodeURIComponent(runIdValue)
  const decodedArtifactKey = decodeURIComponent(artifactKeyValue)
  const detail = await getArtifactRunDetail(decodedRunId)
  const artifactResult = await safeApiGet<ApiArtifact>(
    `/api/v1/runs/${encodeURIComponent(decodedRunId)}/artifacts/${encodeURIComponent(decodedArtifactKey)}`
  )

  if (!artifactResult.ok) {
    return {
      ...detail,
      notices: [...detail.notices, `artifact detail API 失败：${artifactResult.errorMessage}`],
      dataState: detail.dataState === "fallback" ? "fallback" : "partial"
    }
  }

  const hydratedArtifact = mapArtifact(artifactResult.data, decodedRunId)
  const artifacts = upsertArtifact(detail.artifacts, hydratedArtifact)
  return buildRunDetail({
    run: detail.run,
    artifacts,
    replay: detail.replay,
    lineage: detail.lineage,
    selectedArtifactKey: hydratedArtifact.artifactKey,
    notices: detail.notices,
    dataState: detail.dataState
  })
}

export async function getReplayBundle(runIdValue: string): Promise<{
  replay: StudioReplayBundle
  lineage: ReturnType<typeof mapLineage>
}> {
  const decodedRunId = decodeURIComponent(runIdValue)
  const encodedRunId = encodeURIComponent(decodedRunId)
  const [replayResult, lineageResult] = await Promise.all([
    safeApiGet<ApiReplayBundle>(`/api/v1/runs/${encodedRunId}/replay`),
    safeApiGet<ApiLineageResult>(`/api/v1/runs/${encodedRunId}/lineage`)
  ])

  if (!replayResult.ok) {
    const fallback = mapFallbackDetail(decodedRunId)
    return {
      replay: fallback.replay as StudioReplayBundle,
      lineage: fallback.lineage
    }
  }

  const notices = lineageResult.ok ? [] : [`lineage API 失败：${lineageResult.errorMessage}`]
  return {
    replay: mapReplayBundle(replayResult.data, { partial: notices.length > 0, notices }),
    lineage: lineageResult.ok ? mapLineage(lineageResult.data, "upstream", decodedRunId) : []
  }
}

function replayFromArtifactList(runId: string, payload: ApiArtifactList): ApiReplayBundle {
  return {
    run_id: payload.run_id ?? runId,
    artifact_count: payload.artifact_count ?? payload.artifacts?.length ?? 0,
    artifacts: payload.artifacts ?? [],
    event_count: 0,
    events: [],
    step_result_count: 0,
    step_results: {},
    integrity: {
      valid: (payload.artifact_count ?? payload.artifacts?.length ?? 0) > 0,
      source: "artifacts_list"
    }
  }
}

function mergeArtifactContent(summaryArtifacts: ReturnType<typeof mapArtifact>[], replayArtifacts: ReturnType<typeof mapArtifact>[]) {
  return summaryArtifacts.map((artifact) => {
    const hydrated = replayArtifacts.find((item) => item.artifactKey === artifact.artifactKey)
    return hydrated ? { ...artifact, ...hydrated, relativePath: artifact.relativePath ?? hydrated.relativePath } : artifact
  })
}

function upsertArtifact(artifacts: ReturnType<typeof mapArtifact>[], artifact: ReturnType<typeof mapArtifact>) {
  const index = artifacts.findIndex((item) => item.artifactKey === artifact.artifactKey)
  if (index === -1) return [artifact, ...artifacts]
  return artifacts.map((item, itemIndex) => (itemIndex === index ? artifact : item))
}

function apiFailureNotices(results: Record<string, { ok: boolean; errorMessage?: string }>): string[] {
  return Object.entries(results)
    .filter(([, result]) => !result.ok)
    .map(([name, result]) => `${name} API 失败：${result.errorMessage ?? "unknown error"}`)
}
