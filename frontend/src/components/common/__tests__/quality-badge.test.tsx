import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { QualityBadge } from "@/components/common/quality-badge";

describe("QualityBadge", () => {
  it("renders score and quality label", () => {
    render(<QualityBadge score={91} />);
    expect(screen.getByText(/高质量/)).toBeInTheDocument();
    expect(screen.getByText(/91/)).toBeInTheDocument();
  });
});
