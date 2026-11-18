import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HistoryPage from "./page";
import { viewport } from "@/vitest.setup";
import type { SavedLeg, SavedSlip } from "@/lib/api";
import { calls, fail, mockBackend, renderWithProviders } from "@/test-utils";

function leg(id: number, over: Partial<SavedLeg> = {}): SavedLeg {
  return {
    id, slip_id: 1, player_name: `Player ${id}`, nba_player_id: 100 + id, market: "player_points",
    market_label: "Points", line: 20.5, over_odds: 1.9, bookmaker: "fanduel", is_paddy_power: 0,
    value_score: 70, side: "over", game_date: "2026-11-17", score_consistency: 80, score_opponent_defense: 50,
    score_vs_opponent: 30, score_home_away: null, score_injury: 60, score_team_context: null,
    score_season_avg: 70, score_blowout_risk: 55, score_volume_context: 66, leg_result: null, ...over,
  };
}
const OPEN: SavedSlip = {
  id: 1, run_id: 1, saved_at: "2026-11-17T18:30:00", target_odds_str: "", target_decimal: 3, combined_odds: 3.61,
  avg_value_score: 70, has_correlated: 0, bookmaker_filter: null, outcome: null, stake: null, profit_loss: null,
  result_at: null, legs: [leg(1), leg(2, { side: null, leg_result: "HIT" })],
};
const SETTLED: SavedSlip = {
  ...OPEN, id: 2, outcome: "LOSS", stake: 10, profit_loss: -10, result_at: "2026-11-18T03:00:00",
  legs: [leg(3, { leg_result: "MISS" })],
};
const WON: SavedSlip = { ...SETTLED, id: 3, outcome: "WIN", profit_loss: 26.1, stake: null, result_at: null, saved_at: "" };

const status = (s: string, extra = {}) => ({
  status: s, game_date: "2026-11-17", started_at: null, finished_at: null,
  checked: 10, hit: 6, miss: 4, no_data: 0, slips_resolved: 0, error: null, ...extra,
});

describe("HistoryPage", () => {
  it("lists saved slips with leg results", async () => {
    mockBackend({ "GET /api/history": [OPEN, SETTLED] });
    renderWithProviders(<HistoryPage />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("#1")).toBeInTheDocument();
    expect(screen.getAllByText("2026-11-17 18:30")).toHaveLength(2);
    expect(screen.getAllByText("OVER 20.5 Points")).toHaveLength(3);   // a leg with no side reads as OVER
  });

  it("shows an empty state", async () => {
    mockBackend({ "GET /api/history": () => fail(500) });
    renderWithProviders(<HistoryPage />);
    expect(await screen.findByText(/No saved slips yet/)).toBeInTheDocument();
  });

  it("records a manual outcome with stake and leg results", async () => {
    const fetchMock = mockBackend({ "GET /api/history": [OPEN], "PATCH /api/history/1/outcome": { updated: true } });
    renderWithProviders(<HistoryPage />);
    await screen.findByText("#1");
    await userEvent.click(screen.getByRole("button", { name: "▼" }));
    expect(screen.getByText("Factor scores at prediction time:")).toBeInTheDocument();
    expect(screen.queryByText("Home/Away")).toBeNull();   // missing factor scores are skipped
    const [hit1] = screen.getAllByRole("button", { name: "HIT" });
    const [, miss2] = screen.getAllByRole("button", { name: "MISS" });
    await userEvent.click(hit1);
    await userEvent.click(miss2);
    await userEvent.click(miss2);   // toggling the same result clears it
    await userEvent.click(screen.getAllByRole("button", { name: "MISS" })[1]);
    await userEvent.type(screen.getByPlaceholderText("10"), "5");
    await userEvent.click(screen.getByRole("button", { name: "VOID" }));
    await userEvent.click(screen.getByRole("button", { name: "VOID" }));   // deselect
    expect(screen.queryByRole("button", { name: "Save Result" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "WIN" }));
    await userEvent.click(screen.getByRole("button", { name: "Save Result" }));
    await waitFor(() => expect(calls(fetchMock)).toContain("PATCH /api/history/1/outcome"));
    const patch = fetchMock.mock.calls.find(([, i]) => i?.method === "PATCH")!;
    expect(JSON.parse(String(patch[1]?.body))).toEqual({ outcome: "WIN", stake: 5, leg_results: { "1": "HIT", "2": "MISS" } });
    await waitFor(() => expect(calls(fetchMock).filter(c => c.startsWith("GET /api/history"))).toHaveLength(2));
  });

  it("saves an outcome without stake or legs", async () => {
    const fetchMock = mockBackend({ "GET /api/history": [OPEN], "PATCH /api/history/1/outcome": { updated: true } });
    renderWithProviders(<HistoryPage />);
    await screen.findByText("#1");
    await userEvent.click(screen.getByRole("button", { name: "▼" }));
    await userEvent.click(screen.getByRole("button", { name: "LOSS" }));
    await userEvent.click(screen.getByRole("button", { name: "Save Result" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, i]) => i?.method === "PATCH")).toBe(true));
    const patch = fetchMock.mock.calls.find(([, i]) => i?.method === "PATCH")!;
    expect(JSON.parse(String(patch[1]?.body))).toEqual({ outcome: "LOSS" });
  });

  it("shows stake, P&L and settle time for settled slips", async () => {
    mockBackend({ "GET /api/history": [SETTLED, WON] });
    renderWithProviders(<HistoryPage />);
    await screen.findByText("#2");
    const [first, second] = screen.getAllByRole("button", { name: "▼" });
    await userEvent.click(first);
    expect(screen.getByText("-10.00")).toBeInTheDocument();
    expect(screen.getByText("Settled: 2026-11-18 03:00")).toBeInTheDocument();
    expect(screen.queryByText("Mark slip result:")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "▲" }));
    await userEvent.click(second);
    expect(screen.getByText("+26.10")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();   // no saved_at
  });

  it("auto-checks results that finish immediately and reloads", async () => {
    const fetchMock = mockBackend({
      "GET /api/history": [OPEN],
      "POST /api/results/check": { status: "started" },
      "GET /api/results/status": status("done", { no_data: 2, slips_resolved: 1 }),
    });
    renderWithProviders(<HistoryPage />);
    await screen.findByText("#1");
    fireEvent.change(document.querySelector('input[type="date"]')!, { target: { value: "2026-11-16" } });
    await userEvent.click(screen.getByRole("button", { name: "Check Results" }));
    expect(await screen.findByText(/6 HIT \/ 4 MISS · 2 no data/)).toBeInTheDocument();
    expect(screen.getByText("1 slip auto-resolved")).toBeInTheDocument();
    expect(calls(fetchMock)).toContain("POST /api/results/check?game_date=2026-11-16");
    await waitFor(() => expect(calls(fetchMock).filter(c => c.startsWith("GET /api/history"))).toHaveLength(2));
  });

  it("polls a running check until it finishes", async () => {
    let n = 0;
    mockBackend({
      "GET /api/history": [OPEN],
      "POST /api/results/check": { status: "started" },
      "GET /api/results/status": () => {
        n += 1;
        if (n === 1) return status("running");
        if (n === 2) return fail(500);   // a failed poll is ignored
        return status("done", { slips_resolved: 3 });
      },
    });
    renderWithProviders(<HistoryPage />);
    await screen.findByText("#1");
    await userEvent.click(screen.getByRole("button", { name: "Check Results" }));
    expect(await screen.findByText("Fetching box scores…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Checking…" })).toBeDisabled();
    expect(await screen.findByText("3 slips auto-resolved", {}, { timeout: 6000 })).toBeInTheDocument();
  }, 10000);

  it("polls to an error", async () => {
    let n = 0;
    mockBackend({
      "GET /api/history": [],
      "POST /api/results/check": { status: "started" },
      "GET /api/results/status": () => (++n === 1 ? status("running") : status("error", { error: "nba down" })),
    });
    const { unmount } = renderWithProviders(<HistoryPage />);
    await userEvent.click(screen.getByRole("button", { name: "Check Results" }));
    expect(await screen.findByText("Error: nba down", {}, { timeout: 4000 })).toBeInTheDocument();
    unmount();
  }, 10000);

  it("reports an immediate error and a failed request", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    let check = 0;
    mockBackend({
      "GET /api/history": [],
      "POST /api/results/check": () => (++check === 1 ? { status: "started" } : fail(403, "nope")),
      "GET /api/results/status": status("error", { error: "no games" }),
    });
    renderWithProviders(<HistoryPage />);
    await userEvent.click(screen.getByRole("button", { name: "Check Results" }));
    expect(await screen.findByText("Error: no games")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Check Results" }));
    await waitFor(() => expect(err).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Check Results" })).toBeEnabled();
  });

  it("drops headshots and the saved date on mobile", async () => {
    viewport.mobile = true;
    mockBackend({ "GET /api/history": [OPEN] });
    renderWithProviders(<HistoryPage />);
    const card = (await screen.findByText("#1")).closest("div[style*='border-radius: 8px']") as HTMLElement;
    await waitFor(() => expect(within(card).queryByText("2026-11-17 18:30")).toBeNull());
    expect(card.querySelectorAll("img")).toHaveLength(0);
  });
});
