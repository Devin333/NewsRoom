import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SourceHealthBadge } from "@/components/common/source-health-badge";

describe("SourceHealthBadge", () => {
  it("renders source health status", () => {
    render(<SourceHealthBadge status="degraded" />);
    expect(screen.getByText("降级")).toBeInTheDocument();
  });
});
