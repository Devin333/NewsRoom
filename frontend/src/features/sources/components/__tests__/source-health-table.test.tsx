import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SourceHealthTable } from "@/features/sources/components/source-health-table";
import { sources } from "@/lib/mock-data";

describe("SourceHealthTable", () => {
  it("renders source health rows", () => {
    render(<SourceHealthTable sources={sources.slice(0, 2)} selectedSourceId={sources[0].id} onSelectSource={vi.fn()} />);
    expect(screen.getByText("OpenAI Blog")).toBeInTheDocument();
    expect(screen.getAllByText("健康").length).toBeGreaterThan(0);
  });
});
