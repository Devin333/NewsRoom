import fs from "node:fs"
import path from "node:path"


export function loadRootEnv(configDir, { override = false } = {}) {
  const envPath = path.resolve(configDir, "..", ".env")
  if (!fs.existsSync(envPath)) return null

  const lines = fs.readFileSync(envPath, "utf8").split(/\r?\n/)
  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line || line.startsWith("#") || !line.includes("=")) continue

    const index = line.indexOf("=")
    const key = line.slice(0, index).trim()
    if (!key || (!override && process.env[key] !== undefined)) continue

    process.env[key] = normalizeEnvValue(line.slice(index + 1).trim())
  }

  return envPath
}

function normalizeEnvValue(value) {
  if (value.length >= 2 && value[0] === value[value.length - 1] && (value[0] === '"' || value[0] === "'")) {
    return value.slice(1, -1)
  }
  return value
}
