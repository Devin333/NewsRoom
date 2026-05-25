import { fileURLToPath } from "node:url"
import path from "node:path"
import { loadRootEnv } from "./root-env.mjs"

const configDir = path.dirname(fileURLToPath(import.meta.url))

loadRootEnv(configDir)

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true
}

export default nextConfig
