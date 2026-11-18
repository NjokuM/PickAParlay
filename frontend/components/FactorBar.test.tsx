import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { FactorBar, FactorGrid } from "./FactorBar";

const factors = [
  { name: "Consistency", score: 85, weight: 0.3, evidence: ["Last 5 games: 1, 2"], confidence: 1 },
  { name: "Injury Context", score: 40, weight: 0.1, evidence: [], confidence: 0.5 },
  { name: "Hit Model", score: 66, weight: 0, evidence: ["Chance of hitting: 56%"] },
];

describe("factor bars", () => {
  it("renders each factor with its evidence", () => {
    render(<FactorGrid factors={factors} />);
    expect(screen.getByText("Consistency")).toBeInTheDocument();
    expect(screen.getByText(/Last 5 games/)).toBeInTheDocument();
    expect(screen.getByText(/Chance of hitting/)).toBeInTheDocument();
  });
  it("renders a single bar without evidence", () => {
    render(<FactorBar factor={{ name: "Season Average", score: 70, weight: 0.06 }} />);
    expect(screen.getByText("Season Average")).toBeInTheDocument();
  });
});
