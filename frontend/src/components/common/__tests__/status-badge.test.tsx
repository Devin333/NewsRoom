import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge } from "@/components/common/status-badge";

describe("StatusBadge", () => {
  it("renders a readable status label", () => {
    render(<StatusBadge status="review_required" />);
    expect(screen.getByText("需要复核")).toBeInTheDocument();
  });
});
