import { beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import SlipBuilderPanel from "./SlipBuilderPanel";
import { SlipBuilderProvider, useSlipBuilder } from "@/lib/slip-builder-context";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: { saveCustomSlip: vi.fn() } }));

function Seed({ n }: { n: number }) {
  const { addLeg } = useSlipBuilder();
  useEffect(() => {
    for (let i = 1; i <= n; i++) addLeg({ propId: i, playerName: `Player ${i}`, playerId: i, market: "player_points",
      marketLabel: "Points", line: 20.5, side: "over", decimalOdds: 1.9, valueScore: 70, bookmaker: "fanduel", matchup: "NYK @ BOS" });
  }, [addLeg, n]);
  return null;
}
const setup = (n: number) => render(<SlipBuilderProvider><Seed n={n} /><SlipBuilderPanel /></SlipBuilderProvider>);

describe("SlipBuilderPanel", () => {
  beforeEach(() => vi.mocked(api.saveCustomSlip).mockReset());

  it("is hidden with no legs", () => {
    const { container } = setup(0);
    expect(container).toBeEmptyDOMElement();
  });

  it("expands, saves and clears", async () => {
    vi.mocked(api.saveCustomSlip).mockResolvedValue({ slip_id: 42 } as never);
    setup(2);
    await userEvent.click(screen.getByText("My Slip"));
    expect(screen.getByText("Player 1")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Save Slip"));
    expect(api.saveCustomSlip).toHaveBeenCalledWith([1, 2]);
    expect(await screen.findByText(/Saved as slip #42/)).toBeInTheDocument();
    await userEvent.click(screen.getByText("Clear"));
    expect(screen.queryByText("My Slip")).toBeNull();
  });

  it("removes a leg, collapses, and survives a failed save", async () => {
    // A plain stub, not a vi.fn: vitest reports a vi.fn's rejection as a
    // test error even though the panel catches it.
    const original = api.saveCustomSlip;
    api.saveCustomSlip = async () => { throw new Error("down"); };
    onTestFinished(() => { api.saveCustomSlip = original; });
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    setup(2);
    await userEvent.click(screen.getByText("My Slip"));
    await userEvent.click(screen.getAllByTitle("Remove")[1]);
    expect(screen.queryByText("Player 2")).toBeNull();
    await userEvent.click(screen.getByText("Save Slip"));
    await screen.findByText("Save Slip");
    expect(err).toHaveBeenCalled();
    await userEvent.click(screen.getByText("▾"));
    expect(screen.getByText("My Slip")).toBeInTheDocument();
  });
});
