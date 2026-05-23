import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { QualityResultTable } from "@/features/quality/components/quality-result-table";
import { qualityResults } from "@/lib/mock-data";

describe("QualityResultTable", () => {
  it("renders quality result rows", () => {
    render(<QualityResultTable results={qualityResults.slice(0, 2)} selectedResultId={qualityResults[0].id} onSelectResult={vi.fn()} />);
    expect(screen.getByText(qualityResults[0].objectTitle)).toBeInTheDocument();
    expect(screen.getAllByText("需要复核").length).toBeGreaterThan(0);
  });
});
