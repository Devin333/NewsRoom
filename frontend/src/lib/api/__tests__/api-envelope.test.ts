import { describe, expect, it } from "vitest"
import { normalizeApiError } from "@/lib/api/api-errors"
import { unwrapApiEnvelope } from "@/lib/api/api-envelope"

describe("api envelope utilities", () => {
  it("unwraps a success envelope", () => {
    const result = unwrapApiEnvelope<{ id: string }>({
      success: true,
      data: { id: "run-1" },
      request_id: "req-1",
      schema_version: "v1"
    })

    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.data).toEqual({ id: "run-1" })
      expect(result.requestId).toBe("req-1")
      expect(result.schemaVersion).toBe("v1")
    }
  })

  it("unwraps a direct payload", () => {
    const payload = { id: "direct-payload" }
    const result = unwrapApiEnvelope<typeof payload>(payload)

    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.data).toEqual(payload)
      expect(result.requestId).toBeUndefined()
    }
  })

  it("preserves camelCase request ids", () => {
    const result = unwrapApiEnvelope<{ id: string }>({
      success: true,
      data: { id: "run-2" },
      requestId: "req-camel",
      schemaVersion: "v2"
    })

    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.requestId).toBe("req-camel")
      expect(result.schemaVersion).toBe("v2")
    }
  })

  it("normalizes an error envelope", () => {
    const result = unwrapApiEnvelope({
      success: false,
      request_id: "req-error",
      error: {
        code: "source_unavailable",
        message: "Source API is unavailable",
        details: { source_id: "hn" },
        retryable: true,
        user_action_required: false
      }
    })

    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error).toMatchObject({
        code: "source_unavailable",
        message: "Source API is unavailable",
        details: { source_id: "hn" },
        retryable: true,
        userActionRequired: false,
        requestId: "req-error"
      })
    }
  })

  it("normalizes thrown and unknown errors", () => {
    const thrown = new Error("network down") as Error & { code: string; requestId: string }
    thrown.code = "network_error"
    thrown.requestId = "req-thrown"

    expect(normalizeApiError(thrown)).toMatchObject({
      code: "network_error",
      message: "network down",
      requestId: "req-thrown"
    })

    expect(normalizeApiError(null)).toMatchObject({
      code: "request_failed",
      message: "API request failed"
    })
  })
})
