import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AnalyticsPage from "./page";
import { viewport } from "@/vitest.setup";
import type { Analytics, PickAnalytics } from "@/lib/api";
import { calls, fail, loginAs, mockBackend } from "@/test-utils";

const REGULAR: PickAnalytics = {
  picks: { total: 100, hits: 58, misses: 42, hit_rate: 0.58, roi_pct: 6.2, implied_prob_pct: 52.4,
    edge_pct: 5.6, avg_decimal_odds: 1.91, picks_with_odds: 90 },
  value_calibration: [
    { bucket: 65, total: 40, hits: 20, roi_pct: -3.1, avg_implied_prob: 0.52, edge_pct: -2.0 },
    { bucket: 70, total: 60, hits: 38, roi_pct: null, avg_implied_prob: null, edge_pct: null },
  ],
  factor_calibration: {
    Consistency: [{ bucket: 50, total: 30, hits: 12 }, { bucket: 70, total: 70, hits: 46 }],
    Injury: [{ bucket: 40, total: 10, hits: 5 }],
  },
  by_market: [
    { market_label: "Points", total: 60, hits: 37, roi_pct: 9.1, edge_pct: 8.0 },
    { market_label: "Assists", total: 40, hits: 16, roi_pct: null, edge_pct: null },
  ],
  by_side: [{ side: "over", total: 30, hits: 13 }, { side: "under", total: 70, hits: 45 }],
  daily_trend: [{ game_date: "2026-11-16", total: 50, hits: 30 }, { game_date: "2026-11-17", total: 50, hits: 28 }],
  daily_pnl: [{ game_date: "2026-11-16", day_roi_units: 4.2, picks: 50 }, { game_date: "2026-11-17", day_roi_units: 2.0, picks: 50 }],
  threshold_table: [
    { min_score: 65, total: 100, hits: 58, hit_rate_pct: 58, roi_pct: 6.2, implied_prob_pct: 52.4, edge_pct: 5.6 },
    { min_score: 80, total: 0, hits: 0, hit_rate_pct: 0, roi_pct: null, implied_prob_pct: null, edge_pct: null },
    { min_score: 70, total: 60, hits: 30, hit_rate_pct: 50, roi_pct: -4.0, implied_prob_pct: 52.0, edge_pct: -2.0 },
  ],
};
const ALT: PickAnalytics = {
  picks: { total: 0, hits: 0, misses: 0, hit_rate: 0, roi_pct: null, implied_prob_pct: null, edge_pct: null,
    avg_decimal_odds: null, picks_with_odds: 0 },
  value_calibration: [], factor_calibration: {}, by_market: [], by_side: [], daily_trend: [], daily_pnl: [],
};
const DATA: Analytics = {
  ...REGULAR, regular: REGULAR, alt: ALT, model_version: "2.1",
  by_model_version: [
    { version: "2.0", first_date: "2026-10-21", last_date: "2026-11-01", graded: 500, graded_hit_rate_pct: 51.0,
      avg_score: 61, picks: 120, hits: 60, hit_rate_pct: 50.0, implied_prob_pct: 52.0, edge_pct: -2.0, roi_pct: -4.1 },
    { version: "2.1", first_date: "2026-11-17", last_date: "2026-11-17", graded: 80, graded_hit_rate_pct: null,
      avg_score: 63, picks: 20, hits: 0, hit_rate_pct: null, implied_prob_pct: null, edge_pct: null, roi_pct: null },
  ],
  special_picks: { total: 12, hits: 8, hit_rate_pct: 66.7, implied_prob_pct: 51.0, model_prob_pct: 62.3, roi_pct: 25.0,
    by_version: [], by_night: [] },
  slips: { total_slips: 4, wins: 1, win_rate: 0.25, total_pnl: -12.5 },
};

describe("AnalyticsPage", () => {
  // recharts warns about zero-size containers under jsdom
  beforeEach(() => { vi.spyOn(console, "warn").mockImplementation(() => {}); });

  it("shows headline KPIs, sides, thresholds, special picks and model versions", async () => {
    const fetchMock = mockBackend({ "GET /api/analytics": DATA });
    render(<AnalyticsPage />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("58 hits · 42 misses · 100 picks")).toBeInTheDocument();
    expect(screen.getAllByText("58.0%")).toHaveLength(2);   // headline + the active threshold row
    expect(calls(fetchMock)).toEqual(["GET /api/analytics?min_score=65"]);
    expect(screen.getByText("avg odds 1.91")).toBeInTheDocument();
    expect(screen.getAllByText("+5.6pp")).toHaveLength(2);
    expect(screen.getByText("on 90 picks with odds")).toBeInTheDocument();
    expect(screen.getByText("OVER: 43% · UNDER: 64%")).toBeInTheDocument();
    expect(screen.getByText("💡 Model strength: UNDER picks")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(screen.getByText("66.7%")).toBeInTheDocument();
    expect(screen.getByText("2.1", { selector: "b" })).toBeInTheDocument();
    expect(screen.getByText("2026-10-21 → 2026-11-01")).toBeInTheDocument();
    expect(screen.getByText("Cumulative ROI")).toBeInTheDocument();
    // diagnostics are admin-only
    expect(screen.queryByText("Value Score Calibration")).toBeNull();
    expect(screen.queryByText("Min Score Threshold")).toBeNull();
  });

  it("gives admins diagnostics and a threshold picker", async () => {
    loginAs(true);
    const fetchMock = mockBackend({ "GET /api/analytics": DATA });
    render(<AnalyticsPage />);
    expect(await screen.findByText("Value Score Calibration")).toBeInTheDocument();
    expect(screen.getByText("Daily Hit Rate Trend")).toBeInTheDocument();
    expect(screen.getByText("Hit Rate by Market")).toBeInTheDocument();
    expect(screen.getByText("Bet Slip Stats")).toBeInTheDocument();
    expect(screen.getByText("-12.50")).toBeInTheDocument();
    expect(screen.getByText("25.0%")).toBeInTheDocument();
    expect(screen.getByText("Factor Calibration: Consistency")).toBeInTheDocument();
    expect(screen.getByText("(n=70)")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Injury", { selector: "span" }));
    expect(screen.getByText("Factor Calibration: Injury")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Blowout Risk" }));
    expect(screen.getByText("No data for Blowout Risk — check results first.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "75+" }));
    await waitFor(() => expect(calls(fetchMock)).toContain("GET /api/analytics?min_score=75"));
  });

  it("falls back to simple lists when there's little data", async () => {
    loginAs(true);
    const thin: PickAnalytics = {
      ...REGULAR,
      picks: { ...REGULAR.picks, hit_rate: 0.4, roi_pct: -8, edge_pct: -12, implied_prob_pct: null, avg_decimal_odds: null, picks_with_odds: 0 },
      value_calibration: [{ bucket: 60, total: 10, hits: 4, roi_pct: null, avg_implied_prob: null, edge_pct: null }],
      daily_trend: [{ game_date: "2026-11-17", total: 10, hits: 4 }],
      daily_pnl: [{ game_date: "2026-11-17", day_roi_units: -0.8, picks: 10 }],
      by_side: [{ side: "over", total: 40, hits: 30 }, { side: "under", total: 0, hits: 0 }],
      by_market: [], threshold_table: [],
    };
    mockBackend({ "GET /api/analytics": { ...DATA, regular: thin, by_model_version: [], special_picks: undefined,
      slips: { total_slips: 0, wins: 0, win_rate: 0, total_pnl: 0 } } });
    render(<AnalyticsPage />);
    expect(await screen.findByText("Line chart will appear after 2+ days of data.")).toBeInTheDocument();
    expect(screen.getByText("40% (4/10)")).toBeInTheDocument();
    expect(screen.getByText("Score 60–64")).toBeInTheDocument();
    expect(screen.getByText("No data")).toBeInTheDocument();
    expect(screen.getByText("💡 Model strength: OVER picks")).toBeInTheDocument();
    expect(screen.getByText("breakeven probability")).toBeInTheDocument();
    expect(screen.getByText("1 unit per pick")).toBeInTheDocument();
    expect(screen.queryByText("Cumulative ROI")).toBeNull();
    expect(screen.queryByText("Bet Slip Stats")).toBeNull();
    expect(screen.queryByText("Hit Rate by Market")).toBeNull();
  });

  it("switches to alt lines and explains when there's nothing graded", async () => {
    mockBackend({ "GET /api/analytics": { ...DATA, special_picks: { ...DATA.special_picks!, total: 0 } } });
    render(<AnalyticsPage />);
    expect(await screen.findByText("No graded special picks yet.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Alt Lines" }));
    expect(screen.getByText(/Alt-line accuracy from ladder picks \(65\+ score only\)/)).toBeInTheDocument();
    expect(screen.getByText(/No graded picks yet/)).toBeInTheDocument();
    expect(screen.queryByText("★ Special Picks")).toBeNull();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4);
    await userEvent.click(screen.getByRole("button", { name: "Regular Props" }));
    expect(screen.getByText("★ Special Picks")).toBeInTheDocument();
  });

  it("renders nothing when the request fails", async () => {
    mockBackend({ "GET /api/analytics": () => fail(500) });
    const { container } = render(<AnalyticsPage />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("stacks cards on mobile", async () => {
    viewport.mobile = true;
    loginAs(true);
    mockBackend({ "GET /api/analytics": DATA });
    render(<AnalyticsPage />);
    expect(await screen.findByText("Bet Slip Stats")).toBeInTheDocument();
  });
});
