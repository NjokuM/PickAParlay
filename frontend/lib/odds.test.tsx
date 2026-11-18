import { describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { formatOdds, OddsFormatProvider, OddsFormatSelector, useOddsFormat } from "./odds";

describe("formatOdds", () => {
  it("formats decimal, fractional and american", () => {
    expect(formatOdds(1.9, "decimal")).toBe("1.90");
    expect(formatOdds(5, "fractional")).toBe("4/1");
    expect(formatOdds(1.909, "fractional")).toBe("10/11");
    expect(formatOdds(2.5, "american")).toBe("+150");
    expect(formatOdds(1.5, "american")).toBe("-200");
  });
  it("handles odd inputs", () => {
    expect(formatOdds(null, "decimal")).toBe("—");
    expect(formatOdds(0, "decimal")).toBe("—");
    expect(formatOdds(1, "fractional")).toBe("0/1");
    expect(formatOdds(1.137, "fractional")).toMatch(/\//);
  });
});

function Probe() {
  const { format } = useOddsFormat();
  return <span data-testid="fmt">{format}</span>;
}

describe("OddsFormatProvider", () => {
  it("restores the saved format and saves changes", async () => {
    localStorage.setItem("odds_format", "american");
    render(<OddsFormatProvider><Probe /><OddsFormatSelector /></OddsFormatProvider>);
    expect(screen.getByTestId("fmt")).toHaveTextContent("american");
    await userEvent.click(screen.getByText("Frac"));
    expect(screen.getByTestId("fmt")).toHaveTextContent("fractional");
    expect(localStorage.getItem("odds_format")).toBe("fractional");
    expect(screen.getByText("Odds Format")).toBeInTheDocument();
  });
  it("compact selector hides the label", () => {
    render(<OddsFormatProvider><OddsFormatSelector compact /></OddsFormatProvider>);
    expect(screen.queryByText("Odds Format")).toBeNull();
  });
});
