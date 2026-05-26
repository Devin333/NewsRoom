import { readdir, readFile, stat } from "node:fs/promises"
import path from "node:path"
import { safeApiPost } from "@/lib/api/server"
import { adaptCommunityBoardPayload } from "@/lib/community/community-adapter"
import { buildCommunityListResult } from "@/lib/community/community-filters"
import type { CommunityListParams, CommunityListResult, CommunityTopicDetail } from "@/types/community"

type LoadedCommunityData = {
  payload?: unknown
  source: CommunityListResult["source"]
  notice?: string
}

export async function getCommunityList(params: CommunityListParams): Promise<CommunityListResult> {
  const loaded = await loadCommunityData()
  const adapted = adaptCommunityBoardPayload(loaded.payload, { notice: loaded.notice })

  return buildCommunityListResult(adapted.topics, params, {
    source: adapted.topics.length ? loaded.source : "empty",
    dataState: adapted.dataState,
    generatedAt: adapted.generatedAt,
    notices: adapted.notices
  })
}

export async function getCommunityTopic(slug: string): Promise<CommunityTopicDetail | undefined> {
  const loaded = await loadCommunityData()
  const adapted = adaptCommunityBoardPayload(loaded.payload, { notice: loaded.notice })
  return adapted.details.find((detail) => detail.slug === slug)
}

async function loadCommunityData(): Promise<LoadedCommunityData> {
  const backend = await loadBackendBoardOutput()
  if (backend.payload) return backend

  const artifact = await loadLatestArtifactBoardOutput()
  if (artifact.payload) return artifact

  return {
    source: "empty",
    notice: "No backend output or local community_pulse artifact was found."
  }
}

async function loadBackendBoardOutput(): Promise<LoadedCommunityData> {
  const response = await safeApiPost<unknown>("/api/v1/boards/community_pulse/output", { items: [] })
  if (!response.ok) {
    return {
      source: "empty",
      notice: `Backend community board output unavailable: ${response.errorMessage}`
    }
  }

  const adapted = adaptCommunityBoardPayload(response.data)
  if (!adapted.topics.length) {
    return {
      source: "empty",
      notice: "Backend community board output returned no displayable topics; local artifacts were checked."
    }
  }

  return {
    payload: response.data,
    source: "backend",
    notice: "Loaded from backend community_pulse board output."
  }
}

async function loadLatestArtifactBoardOutput(): Promise<LoadedCommunityData> {
  const runDirs = await communityRunDirs()
  for (const runDir of runDirs) {
    const payload = await readFirstJson(runDir, ["board_output.json", "output.json"])
    if (payload !== undefined) {
      return {
        payload,
        source: "artifact",
        notice: `Loaded from local community_pulse artifact: ${path.basename(runDir)}.`
      }
    }
  }

  return {
    source: "empty",
    notice: "No local community_pulse artifact could be read."
  }
}

async function communityRunDirs() {
  const roots = uniquePaths([
    path.resolve(process.cwd(), ".newsroom", "runs"),
    path.resolve(process.cwd(), "..", ".newsroom", "runs")
  ])
  const dirs: Array<{ path: string; mtimeMs: number }> = []

  for (const root of roots) {
    const entries = await safeReadDir(root)
    for (const entry of entries) {
      if (!entry.isDirectory() || !entry.name.includes("community_pulse")) continue
      const fullPath = path.join(root, entry.name)
      const info = await safeStat(fullPath)
      if (info) dirs.push({ path: fullPath, mtimeMs: info.mtimeMs })
    }
  }

  return dirs.sort((left, right) => right.mtimeMs - left.mtimeMs).map((entry) => entry.path)
}

async function readFirstJson(runDir: string, filenames: string[]) {
  for (const filename of filenames) {
    const filePath = path.join(runDir, filename)
    const payload = await readJson(filePath)
    if (payload !== undefined) return payload
  }
  return undefined
}

async function readJson(filePath: string) {
  try {
    return JSON.parse(await readFile(filePath, "utf-8")) as unknown
  } catch {
    return undefined
  }
}

async function safeReadDir(root: string) {
  try {
    return await readdir(root, { withFileTypes: true })
  } catch {
    return []
  }
}

async function safeStat(filePath: string) {
  try {
    return await stat(filePath)
  } catch {
    return undefined
  }
}

function uniquePaths(values: string[]) {
  return [...new Set(values)]
}
