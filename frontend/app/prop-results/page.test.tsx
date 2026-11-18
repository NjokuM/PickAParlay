import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PropResultsPage from "./page";
import { viewport } from "@/vitest.setup";
import { calls, fail, loginAs, makePropResult, mockBackend, renderWithProviders, setRange } from "@/test-utils";

const ROWS = [
  makePropResult({ id: 1, leg_result: "HIT" }),
  makePropResult({ id: 2, leg_result: "MISS", line: 27.5, is_best_side: 0 }),
  makePropResult({ id: 3, player_name: "Josh Hart", nba_player_id: 1628404, market_label: "Rebounds", side: "under",
    leg_result: "HIT", is_alternate: 1, matchup: null, value_score: null as unknown as number }),
  makePropResult({ id: 4, player_name: "Mikal Bridges", market_label: "Assists", leg_result: null, is_active: 0,
    side: null as unknown as string, game_date: null as unknown as string }),
  makePropResult({ id: 5, player_name: "Mikal Bridges", market_label: "Rebounds", leg_result: "MISS" }),
];
const status = (s: string, extra = {}) => ({
  status: s, game_date: "2026-11-17", started_at: null, finished_at: null,
  checked: 5, hit: 3, miss: 2, no_data: 0, slips_resolved: 0, error: null, ...extra,
});
const lastPropsQuery = (fetchMock: ReturnType<typeof mockBackend>) =>
  new URLSearchParams(calls(fetchMock).filter(c => c.startsWith("GET /api/prop-results")).at(-1)!.split("?")[1]);

describe("PropResultsPage", () => {
  it("loads yesterday's graded regular props with summary stats", async () => {
    const fetchMock = mockBackend({ "GET /api/prop-results": ROWS });
    renderWithProviders(<PropResultsPage />);
    expect(screen.getByText("Loading yesterday's results…")).toBeInTheDocument();
    expect(await screen.findByText("4 graded · 1 pending")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByText("2 HIT · 2 MISS")).toBeInTheDocument();
    expect(screen.getByText("Hit rate by market")).toBeInTheDocument();
    expect(screen.getByText("5 props (1 pending)")).toBeInTheDocument();
    expect(screen.getAllByText("PICK").length).toBeGreaterThan(0);
    expect(screen.getByText("ALT")).toBeInTheDocument();
    const q = lastPropsQuery(fetchMock);
    expect(q.get("date_from")).toBe(q.get("date_to"));
    expect(q.get("graded_only")).toBe("true");
    expect(q.get("alt_filter")).toBe("regular");
    expect(q.get("limit")).toBe("5000");
    expect(screen.queryByText("🔧 Check Results")).toBeNull();
  });

  it("applies every filter", async () => {
    const fetchMock = mockBackend({ "GET /api/prop-results": ROWS });
    renderWithProviders(<PropResultsPage />);
    await screen.findByText("4 graded · 1 pending");
    const [from, to] = document.querySelectorAll<HTMLInputElement>('input[type="date"]');
    fireEvent.change(from, { target: { value: "2026-11-01" } });
    fireEvent.change(to, { target: { value: "2026-11-10" } });
    await userEvent.selectOptions(screen.getByRole("combobox"), "Assists");
    setRange(screen.getByRole("slider"), 65);
    await userEvent.click(screen.getByRole("button", { name: "UNDER" }));
    await userEvent.click(screen.getByRole("button", { name: "MISS" }));
    await userEvent.click(screen.getByRole("button", { name: "Alt Lines" }));
    await userEvent.click(screen.getByRole("button", { name: "Active Only" }));
    await userEvent.click(screen.getByRole("button", { name: "Graded Only" }));
    await userEvent.type(screen.getByPlaceholderText("Any player"), "hart{Enter}");
    await waitFor(() => expect(lastPropsQuery(fetchMock).get("player")).toBe("hart"));
    expect(Object.fromEntries(lastPropsQuery(fetchMock))).toEqual({
      market: "Assists", player: "hart", date_from: "2026-11-01", date_to: "2026-11-10", min_score: "65",
      result: "MISS", side: "under", limit: "5000", active_only: "true", graded_only: "false", alt_filter: "alt",
    });
    await userEvent.click(screen.getByRole("button", { name: "OVER" }));
    await userEvent.click(screen.getAllByRole("button", { name: "All" })[0]);
    await userEvent.click(screen.getByRole("button", { name: "Apply Filters" }));
    await waitFor(() => expect(lastPropsQuery(fetchMock).get("side")).toBeNull());
  });

  it("summarises by player", async () => {
    mockBackend({ "GET /api/prop-results": ROWS });
    renderWithProviders(<PropResultsPage />);
    await screen.findByText("4 graded · 1 pending");
    await userEvent.click(screen.getByRole("button", { name: "By Player" }));
    expect(screen.getAllByText("50% (1/2)")).toHaveLength(3);     // Points + Rebounds market bars, and Brunson's row
    expect(screen.getByText("pending")).toBeInTheDocument();       // Bridges assists has nothing graded
    expect(screen.getByText("+1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Results Table" }));
    expect(screen.getByText("Matchup")).toBeInTheDocument();
  });

  it("shows an empty state, with a hint for admins", async () => {
    loginAs(true);
    mockBackend({ "GET /api/prop-results": [] });
    renderWithProviders(<PropResultsPage />);
    expect(await screen.findByText(/No graded props found for yesterday yet/)).toBeInTheDocument();
    expect(screen.getByText(/to grade them manually/)).toBeInTheDocument();
  });

  it("logs a failed load", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    mockBackend({ "GET /api/prop-results": () => fail(500) });
    renderWithProviders(<PropResultsPage />);
    await waitFor(() => expect(err).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Apply Filters" })).toBeEnabled();
  });

  it("lets admins check results and polls until done", async () => {
    loginAs(true);
    let n = 0;
    const fetchMock = mockBackend({
      "GET /api/prop-results": ROWS,
      "POST /api/results/check": { status: "started" },
      "GET /api/results/status": () => {
        n += 1;
        if (n === 1) return status("running");
        if (n === 2) return fail(500);
        return status("done", { no_data: 1, slips_resolved: 1 });
      },
    });
    renderWithProviders(<PropResultsPage />);
    await screen.findByText("4 graded · 1 pending");
    fireEvent.change(document.querySelectorAll('input[type="date"]')[2], { target: { value: "2026-11-15" } });
    await userEvent.click(screen.getByRole("button", { name: "Check Results" }));
    expect(await screen.findByText("Fetching box scores…")).toBeInTheDocument();
    expect(await screen.findByText(/3 HIT \/ 2 MISS · 1 no data/, {}, { timeout: 7000 })).toBeInTheDocument();
    expect(screen.getByText("1 slip auto-resolved")).toBeInTheDocument();
    expect(calls(fetchMock)).toContain("POST /api/results/check?game_date=2026-11-15");
    await waitFor(() => expect(calls(fetchMock).filter(c => c.startsWith("GET /api/prop-results"))).toHaveLength(2));
  }, 12000);

  it("handles immediate results, errors and failed checks", async () => {
    loginAs(true);
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    let n = 0;
    mockBackend({
      "GET /api/prop-results": ROWS,
      "POST /api/results/check": () => (++n === 3 ? fail(500) : { status: "started" }),
      "GET /api/results/status": () => (n === 1 ? status("done", { slips_resolved: 2 }) : status("error", { error: "no games" })),
    });
    renderWithProviders(<PropResultsPage />);
    await screen.findByText("4 graded · 1 pending");
    await userEvent.click(screen.getByRole("button", { name: "Check Results" }));
    expect(await screen.findByText("2 slips auto-resolved")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Check Results" }));
    expect(await screen.findByText("Error: no games")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Check Results" }));
    await waitFor(() => expect(err).toHaveBeenCalled());
  });

  it("polls a running check to an error and stops on unmount", async () => {
    loginAs(true);
    let n = 0;
    mockBackend({
      "GET /api/prop-results": [],
      "POST /api/results/check": { status: "started" },
      "GET /api/results/status": () => (++n === 1 ? status("running") : status("error", { error: "late" })),
    });
    const { unmount } = renderWithProviders(<PropResultsPage />);
    await userEvent.click(screen.getByRole("button", { name: "Check Results" }));
    expect(await screen.findByText("Error: late", {}, { timeout: 4000 })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Check Results" }));
    unmount();   // clears the running poll
  }, 10000);

  it("uses cards on mobile for both views", async () => {
    viewport.mobile = true;
    mockBackend({ "GET /api/prop-results": [makePropResult({ id: 9, leg_result: null })] });
    renderWithProviders(<PropResultsPage />);
    expect(await screen.findByText("0 graded · 1 pending")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByText("2026-11-17 · NYK @ BOS")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "By Player" }));
    expect(screen.getByText("+1 pending")).toBeInTheDocument();
    expect(screen.getByText("0 graded")).toBeInTheDocument();
  });

  it("colours a strong mobile player summary", async () => {
    viewport.mobile = true;
    mockBackend({ "GET /api/prop-results": [makePropResult({ id: 1, leg_result: "HIT", matchup: null })] });
    renderWithProviders(<PropResultsPage />);
    expect(await screen.findByText("Graded props")).toBeInTheDocument();
    expect(screen.getByText("2026-11-17 · FanDuel")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "By Player" }));
    expect(screen.getAllByText("100%")).toHaveLength(2);   // headline KPI + the player card
  });
});
