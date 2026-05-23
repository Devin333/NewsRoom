import { describe, expect, it } from "vitest";
import { getStatusVariant, qualityStatusVariants, sourceHealthStatusVariants } from "@/lib/constants/status-variants";

describe("status variants", () => {
  it("maps source and quality statuses", () => {
    expect(sourceHealthStatusVariants.healthy).toBe("success");
    expect(sourceHealthStatusVariants.failed).toBe("danger");
    expect(qualityStatusVariants.review_required).toBe("info");
  });

  it("falls back through generic status mapping", () => {
    expect(getStatusVariant("published")).toBe("success");
    expect(getStatusVariant("partially_failed")).toBe("warning");
    expect(getStatusVariant("unknown-state")).toBe("default");
  });
});
