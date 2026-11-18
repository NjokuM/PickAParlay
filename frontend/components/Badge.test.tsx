import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { LegResultBadge, OutcomeBadge, RecoBadge, ScoreBadge } from "./Badge";

describe("badges", () => {
  it.each([[90, "90.0"], [72, "72.0"], [55, "55.0"], [30, "30.0"]])("score %s", (score, text) => {
    render(<ScoreBadge score={score} />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });
  it.each(["Strong Value", "Good Value", "Marginal Value", "Poor Value"])("recommendation %s", (reco) => {
    render(<RecoBadge reco={reco} />);
    expect(screen.getByText(reco)).toBeInTheDocument();
  });
  it("outcomes and leg results", () => {
    render(<><OutcomeBadge outcome={null} /><OutcomeBadge outcome="WIN" /><OutcomeBadge outcome="LOSS" /><OutcomeBadge outcome="VOID" />
      <LegResultBadge result={null} /><LegResultBadge result="HIT" /><LegResultBadge result="MISS" /></>);
    expect(screen.getByText("Pending")).toBeInTheDocument();
    for (const t of ["WIN", "LOSS", "VOID", "✓", "✗"]) expect(screen.getByText(t)).toBeInTheDocument();
  });
});
