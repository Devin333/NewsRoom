import { readdir, readFile, stat } from "node:fs/promises"
import path from "node:path"
import { safeApiGet } from "@/lib/api/server"
import { adaptCommunityBoardPayload } from "@/lib/community/community-adapter"
import { buildCommunityListResult } from "@/lib/community/community-filters"
import {
  buildCommunitySignalDetailResult,
  buildCommunitySignalListResult
} from "@/lib/community/community-signals"
import type {
  CommunityListParams,
  CommunityListResult,
  CommunitySignalDetailResult,
  CommunitySignalListParams,
  CommunitySignalListResult,
  CommunityTopicDetail
} from "@/types/community"

type JsonRecord = Record<string, unknown>

type LoadedCommunityData = {
  payload?: unknown
  source: CommunityListResult["source"]
  notice?: string
  generatedAt?: string
}

type RunListResponse = {
  runs?: unknown
  items?: unknown
}

type ArtifactResponse = {
  content?: unknown
  data?: unknown
}

type LocalCommunityCandidate = {
  runDir: string
  name: string
  manifest?: JsonRecord
  modifiedAt: string
}

const COMMUNITY_WORKFLOW_ID = "community_pulse-productized-board"
const MAX_ARTIFACT_BYTES = 8_000_000
const BACKEND_ARTIFACT_KEYS = ["board_output", "output"] as const
const LOCAL_ARTIFACT_FILES = ["board_output.json", "output.json"] as const
const LOCAL_SPLIT_FILES = ["cards.json", "detail_pages.json"] as const

export async function getCommunityList(params: CommunityListParams): Promise<CommunityListResult> {
  const loaded = await loadCommunityData()
  const adapted = adaptCommunityBoardPayload(loaded.payload, { notice: loaded.notice })

  return buildCommunityListResult(adapted.topics, params, {
    source: adapted.topics.length ? loaded.source : "empty",
    dataState: adapted.dataState,
    generatedAt: adapted.generatedAt ?? loaded.generatedAt,
    notices: adapted.notices
  })
}

export async function getCommunityTopic(slug: string): Promise<CommunityTopicDetail | undefined> {
  const loaded = await loadCommunityData()
  const adapted = adaptCommunityBoardPayload(loaded.payload, { notice: loaded.notice })
  return adapted.details.find((detail) => detail.slug === slug)
}

export async function getCommunitySignals(params: CommunitySignalListParams): Promise<CommunitySignalListResult> {
  const loaded = await loadCommunityData()
  const adapted = adaptCommunityBoardPayload(loaded.payload, { notice: loaded.notice })

  return buildCommunitySignalListResult(adapted.topics, adapted.details, params, {
    source: adapted.topics.length ? loaded.source : "empty",
    dataState: adapted.dataState,
    generatedAt: adapted.generatedAt ?? loaded.generatedAt,
    notices: adapted.notices
  })
}

export async function getCommunitySignal(signalId: string): Promise<CommunitySignalDetailResult | undefined> {
  const loaded = await loadCommunityData()
  const adapted = adaptCommunityBoardPayload(loaded.payload, { notice: loaded.notice })
  return buildCommunitySignalDetailResult(adapted.topics, adapted.details, signalId, {
    generatedAt: adapted.generatedAt ?? loaded.generatedAt,
    notices: adapted.notices
  })
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
  const runsResult = await safeApiGet<RunListResponse>(
    `/api/v1/runs?limit=80&workflow_id=${encodeURIComponent(COMMUNITY_WORKFLOW_ID)}`
  )
  if (!runsResult.ok) {
    return {
      source: "empty",
      notice: `Backend community run lookup failed: ${runsResult.errorMessage}`
    }
  }

  const runs = arrayRecords(runsResult.data.runs ?? runsResult.data.items).filter(isCommunityPulseRun).sort(compareRunTime)
  for (const run of runs) {
    const runId = text(run.run_id) || text(run.id)
    if (!runId) continue

    for (const artifactKey of BACKEND_ARTIFACT_KEYS) {
      const artifact = await loadBackendArtifact(runId, artifactKey)
      const payload = unwrapArtifactPayload(artifact)
      if (!payload) continue

      const adapted = adaptCommunityBoardPayload(payload)
      if (adapted.topics.length) {
        return {
          payload,
          source: "backend",
          notice: `Loaded from backend community_pulse ${artifactKey} artifact.`,
          generatedAt: adapted.generatedAt ?? runTimestamp(run)
        }
      }
    }
  }

  return {
    source: "empty",
    notice: "Backend did not expose a populated community_pulse board artifact."
  }
}

async function loadBackendArtifact(runId: string, artifactKey: (typeof BACKEND_ARTIFACT_KEYS)[number]): Promise<ArtifactResponse> {
  const response = await safeApiGet<ArtifactResponse>(
    `/api/v1/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactKey)}`
  )
  return response.ok ? response.data : {}
}

async function loadLatestArtifactBoardOutput(): Promise<LoadedCommunityData> {
  const runDirs = await communityRunDirs()
  for (const candidate of runDirs) {
    const payload = await readLocalPayload(candidate)
    if (payload === undefined) continue

    const adapted = adaptCommunityBoardPayload(payload)
    if (!adapted.topics.length) continue

    return {
      payload,
      source: "artifact",
      notice: `Loaded from local community_pulse artifact: ${candidate.name}.`,
      generatedAt: adapted.generatedAt ?? candidate.modifiedAt
    }
  }

  return {
    source: "empty",
    notice: "No local community_pulse artifact could be read."
  }
}

async function communityRunDirs() {
  const dirs: LocalCommunityCandidate[] = []

  for (const root of runsRoots()) {
    const entries = await safeReadDir(root)
    for (const entry of entries) {
      if (!entry.isDirectory() || entry.name === "_records") continue
      const fullPath = path.join(root, entry.name)
      const manifest = asRecord(await readJson(path.join(fullPath, "manifest.json")))
      if (!isCommunityPulseCandidate(entry.name, manifest)) continue

      const modifiedAt = await latestModifiedAt([
        path.join(fullPath, "board_output.json"),
        path.join(fullPath, "output.json"),
        path.join(fullPath, "cards.json"),
        path.join(fullPath, "detail_pages.json"),
        path.join(fullPath, "manifest.json")
      ])
      dirs.push({ runDir: fullPath, name: entry.name, manifest, modifiedAt })
    }
  }

  return dirs.sort((left, right) => Date.parse(right.modifiedAt) - Date.parse(left.modifiedAt))
}

function runsRoots() {
  const configuredRoots = [process.env.NEWSROOM_RUNS_DIR, process.env.NEWSROOM_RUNS_ROOT].filter(Boolean) as string[]
  if (configuredRoots.length) return uniquePaths(configuredRoots)

  return uniquePaths([
    path.resolve(process.cwd(), ".newsroom", "runs"),
    path.resolve(process.cwd(), "..", ".newsroom", "runs")
  ])
}

async function readLocalPayload(candidate: LocalCommunityCandidate) {
  const directPayload = await readFirstJson(candidate.runDir, LOCAL_ARTIFACT_FILES)
  if (directPayload !== undefined && adaptCommunityBoardPayload(directPayload).topics.length) {
    return directPayload
  }

  const cardsPayload = await readJson(path.join(candidate.runDir, LOCAL_SPLIT_FILES[0]))
  const cards = jsonArray(cardsPayload, "cards")
  if (!cards.length) return undefined

  const detailPagesPayload = await readJson(path.join(candidate.runDir, LOCAL_SPLIT_FILES[1]))
  return {
    board_type: "community_pulse",
    cards,
    detail_pages: jsonArray(detailPagesPayload, "detail_pages"),
    generated_at: manifestTimestamp(candidate.manifest) ?? candidate.modifiedAt
  }
}

async function readFirstJson(runDir: string, filenames: readonly string[]) {
  for (const filename of filenames) {
    const filePath = path.join(runDir, filename)
    const payload = await readJson(filePath)
    if (payload !== undefined) return payload
  }
  return undefined
}

async function readJson(filePath: string) {
  try {
    const info = await stat(filePath)
    if (!info.isFile() || info.size <= 2 || info.size > MAX_ARTIFACT_BYTES) return undefined
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

async function latestModifiedAt(filePaths: string[]) {
  const times: number[] = []
  for (const filePath of filePaths) {
    const info = await safeStat(filePath)
    if (info?.isFile()) times.push(info.mtimeMs)
  }
  return new Date(Math.max(0, ...times)).toISOString()
}

function unwrapArtifactPayload(value: unknown): unknown {
  const record = asRecord(value)
  if (!record) return parseJsonString(value) ?? value
  const content = parseJsonString(record.content) ?? record.content
  const data = parseJsonString(record.data) ?? record.data
  return content ?? data ?? value
}

function parseJsonString(value: unknown) {
  if (typeof value !== "string") return undefined
  try {
    return JSON.parse(value) as unknown
  } catch {
    return undefined
  }
}

function isCommunityPulseRun(run: JsonRecord) {
  const values = [run.workflow_id, run.workflowId, run.profile, run.run_id, run.id, run.board_type, run.boardType]
    .map(text)
    .join(" ")
    .toLowerCase()
  return values.includes(COMMUNITY_WORKFLOW_ID) || values.includes("community_pulse")
}

function isCommunityPulseCandidate(name: string, manifest?: JsonRecord) {
  const productization = asRecord(manifest?.business_productization)
  const values = [
    name,
    manifest?.workflow_id,
    manifest?.workflowId,
    manifest?.run_id,
    manifest?.id,
    productization?.board_type,
    productization?.boardType
  ]
    .map(text)
    .join(" ")
    .toLowerCase()
  return values.includes(COMMUNITY_WORKFLOW_ID) || values.includes("community_pulse")
}

function compareRunTime(left: JsonRecord, right: JsonRecord) {
  return runTime(right) - runTime(left)
}

function runTime(run: JsonRecord) {
  const value = runTimestamp(run)
  const time = Date.parse(value)
  return Number.isFinite(time) ? time : 0
}

function runTimestamp(run: JsonRecord) {
  return text(run.finished_at) || text(run.finishedAt) || text(run.completed_at) || text(run.started_at) || text(run.startedAt)
}

function manifestTimestamp(manifest?: JsonRecord) {
  return manifest ? runTimestamp(manifest) : ""
}

function arrayRecords(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(asRecord).filter((item): item is JsonRecord => item !== undefined) : []
}

function jsonArray(value: unknown, key: string): unknown[] {
  if (Array.isArray(value)) return value
  const record = asRecord(value)
  const nested = record?.[key]
  return Array.isArray(nested) ? nested : []
}

function asRecord(value: unknown): JsonRecord | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : undefined
}

function text(value: unknown) {
  return typeof value === "string" || typeof value === "number" ? String(value).trim() : ""
}

function uniquePaths(values: string[]) {
  return [...new Set(values)]
}
