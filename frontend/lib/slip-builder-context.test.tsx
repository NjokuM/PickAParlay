import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { ReactNode } from "react";
import { SlipBuilderProvider, useSlipBuilder } from "./slip-builder-context";

const leg = (propId: number, odds = 2, score = 60) => ({
  propId, playerName: `P${propId}`, playerId: propId, market: "player_points", marketLabel: "Points",
  line: 20.5, side: "over", decimalOdds: odds, valueScore: score, bookmaker: "fanduel", matchup: "NYK @ BOS",
});
const wrapper = ({ children }: { children: ReactNode }) => <SlipBuilderProvider>{children}</SlipBuilderProvider>;

describe("slip builder", () => {
  it("adds, dedupes, combines, removes and clears legs", () => {
    const { result } = renderHook(() => useSlipBuilder(), { wrapper });
    expect(result.current.avgScore).toBe(0);
    act(() => { result.current.addLeg(leg(1, 2, 60)); result.current.addLeg(leg(2, 1.5, 80)); result.current.addLeg(leg(1)); });
    expect(result.current.legs).toHaveLength(2);
    expect(result.current.combinedOdds).toBe(3);
    expect(result.current.avgScore).toBe(70);
    expect(result.current.isInSlip(2)).toBe(true);
    act(() => result.current.removeLeg(2));
    expect(result.current.isInSlip(2)).toBe(false);
    act(() => result.current.clearSlip());
    expect(result.current.legs).toHaveLength(0);
  });
  it("requires the provider", () => {
    expect(() => renderHook(() => useSlipBuilder())).toThrow(/SlipBuilderProvider/);
  });
});
