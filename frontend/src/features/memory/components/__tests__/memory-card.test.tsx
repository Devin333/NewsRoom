import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryCard } from "@/features/memory/components/memory-card";
import { memoryItems } from "@/lib/mock-data";

describe("MemoryCard", () => {
  it("renders memory title and tags", () => {
    render(<MemoryCard item={memoryItems[0]} />);
    expect(screen.getByText(memoryItems[0].title)).toBeInTheDocument();
    expect(screen.getByText(memoryItems[0].tags[0])).toBeInTheDocument();
  });
});
