import { describe, expect, it } from "vitest";
import { formatBytes, formatDateTime, formatDurationMs, formatRelativeTime, formatScore } from "@/lib/format";

describe("format helpers", () => {
  it("formats dates and relative time", () => {
    expect(formatDateTime("2026-05-22T12:00:00Z")).toContain("5月22日");
    expect(formatRelativeTime("2026-05-22T11:59:00Z", new Date("2026-05-22T12:00:00Z"))).toBe("1分钟前");
  });

  it("formats duration, bytes, and scores", () => {
    expect(formatDurationMs(950)).toBe("950 毫秒");
    expect(formatDurationMs(65_000)).toBe("1分 5秒");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatScore(0.91)).toBe("91%");
    expect(formatScore(88.4)).toBe("88%");
  });
});
