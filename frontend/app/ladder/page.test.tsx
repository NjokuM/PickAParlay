import { describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LadderPage from "./page";
import { viewport } from "@/vitest.setup";
import { calls, fail, makePropResult, makeSlip, mockBackend, renderWithProviders, setRange } from "@/test-utils";

const ladderStatus = (status: string, extra = {}) =>
  ({ running: status === "running", started_at: null, finished_at: null, status, props_graded: 0, error: null, ...extra });
const altStatus = (status: string, extra = {}) => ({ ...ladderStatus(status), props_total: 0, ...extra });
const SINGLE = { ...makeSlip(1), type: "single" as const, combined_odds: 2.05 };
const MULTI = { ...makeSlip(2), type: "multi" as const, has_correlated_legs: true, combined_odds: 2.1 };
const ALT = [
  makePropResult({ id: 11, player_name: "Jalen Brunson", line: 20.5, decimal_odds: 1.6, value_score: 85 }),
  makePropResult({ id: 12, player_name: "Josh Hart", market_label: "Rebounds", line: 8.5, side: "under",
    decimal_odds: null, value_score: 55, recommendation: "Moderate Value" }),
  makePropResult({ id: 13, player_name: "Karl-Anthony Towns", line: 30.5, decimal_odds: 2.4, value_score: 40,
    side: null as unknown as string, matchup: null }),
];

function backend(over: Record<string, unknown> = {}) {
  return mockBackend({
    "GET /api/ladder/status": ladderStatus("idle"), "GET /api/ladder/results": [],
    "GET /api/alt-refresh/status": altStatus("idle"), "GET /api/alt-props": ALT, ...over,
  });
}
const altRows = () => screen.getAllByText(/^(Jalen Brunson|Josh Hart|Karl-Anthony Towns)$/).map(e => e.textContent);

describe("LadderPage", () => {
  it("prompts to run when idle", async () => {
    const fetchMock = backend();
    renderWithProviders(<LadderPage />);
    expect(await screen.findByText(/Click "Run Ladder"/)).toBeInTheDocument();
    expect(await screen.findByText("📊 Alt Lines Browser (3)")).toBeInTheDocument();
    expect(calls(fetchMock)).toContain("GET /api/alt-props?limit=500");
  });

  it.each([
    ["no_games", "No NBA games tonight."],
    ["no_props", "No alternate props available for tonight's games."],
    ["done", "No ladder picks found."],
  ])("explains an empty %s result", async (s, text) => {
    backend({ "GET /api/ladder/status": ladderStatus(s) });
    renderWithProviders(<LadderPage />);
    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it("shows single picks and parlays with expandable detail", async () => {
    backend({ "GET /api/ladder/status": ladderStatus("done"), "GET /api/ladder/results": [SINGLE, MULTI] });
    renderWithProviders(<LadderPage />);
    expect(await screen.findByText("Single Picks")).toBeInTheDocument();
    expect(screen.getByText("Parlays at ~2.0")).toBeInTheDocument();
    expect(screen.getByText("2 picks found")).toBeInTheDocument();
    expect(screen.getByText("⚠")).toBeInTheDocument();
    const [single, multi] = screen.getAllByRole("button", { name: "Detail" });
    await userEvent.click(single);
    expect(screen.getByText(/Player 1 — OVER 10.5 Points/)).toBeInTheDocument();
    await userEvent.click(multi);   // only one card open at a time
    expect(screen.getAllByText(/— OVER/)).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(screen.queryByText(/— OVER/)).toBeNull();
  });

  it("runs the ladder and polls until results arrive", async () => {
    let polls = 0;
    const fetchMock = backend({
      "POST /api/ladder": { status: "started" },
      "GET /api/ladder/status": () => {
        polls += 1;
        if (polls === 1) return ladderStatus("idle");
        if (polls === 2) return ladderStatus("running");
        if (polls === 3) return fail(500);   // ignored
        return ladderStatus("done");
      },
      "GET /api/ladder/results": () => (polls >= 4 ? [SINGLE] : []),
    });
    renderWithProviders(<LadderPage />);
    await screen.findByText(/Click "Run Ladder"/);
    await userEvent.click(screen.getByRole("button", { name: "Run Ladder" }));
    expect(await screen.findByRole("button", { name: "Building…" })).toBeDisabled();
    expect(screen.getByText("Searching…")).toBeInTheDocument();
    expect(await screen.findByText("Single Picks", {}, { timeout: 7000 })).toBeInTheDocument();
    expect(screen.getByText("🎯 Ladder Picks (1)")).toBeInTheDocument();
    expect(calls(fetchMock).filter(c => c.startsWith("GET /api/alt-props"))).toHaveLength(2);
  }, 12000);

  it("logs a failed ladder trigger", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    backend({ "POST /api/ladder": () => fail(500, "busy"), "GET /api/ladder/status": ladderStatus("error", { error: "boom" }) });
    renderWithProviders(<LadderPage />);
    expect(await screen.findByText("boom")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run Ladder" }));
    await waitFor(() => expect(err).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Run Ladder" })).toBeEnabled();
  });

  it("refreshes alt lines and polls progress", async () => {
    let polls = 0;
    const fetchMock = backend({
      "POST /api/alt-refresh": { status: "started" },
      "GET /api/alt-refresh/status": () => {
        polls += 1;
        if (polls === 1) return altStatus("idle");
        if (polls === 2) return altStatus("running", { props_graded: 3, props_total: 9 });
        if (polls === 3) return fail(500);
        return altStatus("done");
      },
    });
    renderWithProviders(<LadderPage />);
    await screen.findByText(/Click "Run Ladder"/);
    await userEvent.click(screen.getByRole("button", { name: "Refresh Alt Lines" }));
    expect(await screen.findByText("3/9 graded")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refreshing…" })).toBeDisabled();
    expect(await screen.findByText("Done", {}, { timeout: 7000 })).toBeInTheDocument();
    await waitFor(() => expect(calls(fetchMock).filter(c => c.startsWith("GET /api/alt-props"))).toHaveLength(2));
  }, 12000);

  it("logs a failed alt refresh and shows refresh errors", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    backend({ "POST /api/alt-refresh": () => fail(500), "GET /api/alt-refresh/status": altStatus("error", { error: "no credits" }) });
    renderWithProviders(<LadderPage />);
    expect(await screen.findByText("no credits")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Refresh Alt Lines" }));
    await waitFor(() => expect(err).toHaveBeenCalled());
  });

  it("browses alt lines: filter, sort, expand and add to slip", async () => {
    backend();
    renderWithProviders(<LadderPage />);
    await userEvent.click(await screen.findByText("📊 Alt Lines Browser (3)"));
    expect(altRows()).toEqual(["Jalen Brunson", "Josh Hart", "Karl-Anthony Towns"]);
    const sort = screen.getByRole("combobox");
    await userEvent.selectOptions(sort, "line");
    expect(altRows()).toEqual(["Karl-Anthony Towns", "Jalen Brunson", "Josh Hart"]);
    await userEvent.selectOptions(sort, "odds");
    expect(altRows()).toEqual(["Karl-Anthony Towns", "Jalen Brunson", "Josh Hart"]);
    await userEvent.type(screen.getByPlaceholderText("e.g. Points"), "reb");
    expect(screen.getByText("1 prop")).toBeInTheDocument();
    await userEvent.clear(screen.getByPlaceholderText("e.g. Points"));
    await userEvent.type(screen.getByPlaceholderText("Search…"), "jal");
    expect(altRows()).toEqual(["Jalen Brunson"]);
    await userEvent.clear(screen.getByPlaceholderText("Search…"));
    await userEvent.click(screen.getByText("Jalen Brunson"));
    expect(screen.getByText("Consistency")).toBeInTheDocument();
    expect(screen.queryByText("vs Opponent")).toBeNull();   // null factor scores are skipped
    await userEvent.click(screen.getByText("Jalen Brunson"));
    expect(screen.queryByText("Consistency")).toBeNull();
    await userEvent.click(screen.getAllByRole("button", { name: "+ Add" })[0]);
    expect(screen.getByRole("button", { name: "In Slip" })).toBeDisabled();
    await userEvent.click(screen.getByText("Karl-Anthony Towns"));
    expect(screen.getByText("Consistency")).toBeInTheDocument();
  });

  it("filters alt lines by minimum score", async () => {
    backend();
    renderWithProviders(<LadderPage />);
    await userEvent.click(await screen.findByText("📊 Alt Lines Browser (3)"));
    setRange(screen.getByRole("slider"), 60);
    await waitFor(() => expect(screen.getByText("1 prop")).toBeInTheDocument());
  });

  it("explains an empty alt-lines browser", async () => {
    backend({ "GET /api/alt-props": () => fail(500), "GET /api/ladder/status": () => fail(500),
      "GET /api/ladder/results": () => fail(500), "GET /api/alt-refresh/status": () => fail(500) });
    renderWithProviders(<LadderPage />);
    await userEvent.click(screen.getByText("📊 Alt Lines Browser"));
    expect(await screen.findByText(/No alt lines available yet/)).toBeInTheDocument();
  });

  it("uses cards on mobile", async () => {
    viewport.mobile = true;
    backend({ "GET /api/ladder/results": [SINGLE] });
    renderWithProviders(<LadderPage />);
    await screen.findByText("Single Picks");
    await userEvent.click(await screen.findByText("📊 Alt Lines Browser (3)"));
    const card = screen.getByText("Josh Hart").closest("div[style*='cursor: pointer']") as HTMLElement;
    await userEvent.click(within(card).getByRole("button", { name: "+" }));
    expect(within(card).getByRole("button", { name: "✓" })).toBeDisabled();
    await userEvent.click(card);
    expect(screen.getByText("Consistency")).toBeInTheDocument();
  });
});
