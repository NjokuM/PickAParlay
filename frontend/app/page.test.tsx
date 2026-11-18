import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DashboardPage from "./page";
import { viewport } from "@/vitest.setup";
import { calls, fail, loginAs, makeProp, mockBackend, renderWithProviders } from "@/test-utils";

const GAMES = [
  { game_id: "g1", home_team: "BOS", away_team: "NYK", matchup: "NYK @ BOS", game_date: "2026-11-18" },
  { game_id: "g1", home_team: "BOS", away_team: "NYK", matchup: "NYK @ BOS", game_date: "2026-11-18" },
  { game_id: "g2", home_team: "LAL", away_team: "GSW", matchup: "GSW @ LAL", game_date: "2026-11-18" },
];
const PROPS = [
  makeProp(),
  makeProp({ prop_id: 2, player_name: "Anthony Davis", player_id: 203076, market: "player_rebounds", market_label: "Rebounds",
    line: 11.5, side: "under", over_odds: 2.1, value_score: 81, is_special: true, edge: 0.09, game: "GSW @ LAL", suspicious_line: true }),
  makeProp({ prop_id: 3, player_name: "Anthony Davis", player_id: 203076, line: 24.5, value_score: 66, is_special: true, edge: 0.05 }),
  makeProp({ prop_id: null, player_name: "Zach Edey", player_id: 1641744, value_score: 40, line: 9.5, over_odds: 1.5,
    hit_probability: null, side: undefined as unknown as "over" }),
];

function backend(over: Record<string, unknown> = {}) {
  return mockBackend({
    "GET /api/props": PROPS, "GET /api/tonight": GAMES, "GET /api/bookmakers": ["fanduel", "draftkings"], ...over,
  });
}
const names = () => screen.getAllByText(/^(Jalen Brunson|Anthony Davis|Zach Edey)$/).map(e => e.textContent);

describe("DashboardPage", () => {
  it("lists tonight's props sorted by score, with games and special picks", async () => {
    backend();
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("4 props")).toBeInTheDocument();
    expect(screen.getByText(/3 games/)).toBeInTheDocument();
    expect(screen.getAllByRole("option", { name: "NYK @ BOS" })).toHaveLength(1);   // duplicate game ids collapse in the filter
    expect(screen.getByText("★ Tonight's Special Picks")).toBeInTheDocument();
    expect(screen.getByText(/2 highlighted below/)).toBeInTheDocument();
    expect(screen.getAllByText("★ SPECIAL")).toHaveLength(2);
    expect(screen.getByText("⚠ suspicious")).toBeInTheDocument();
    // the special-picks box shows each player's best edge once
    expect(screen.getByText("58% chance vs 52% priced")).toBeInTheDocument();
    expect(screen.queryByText("↻ Refresh")).toBeNull();   // not admin
  });

  it("re-sorts by name, line and odds", async () => {
    backend();
    renderWithProviders(<DashboardPage />);
    await screen.findByText("4 props");
    await userEvent.click(screen.getByRole("button", { name: "Name" }));
    expect(names().slice(-4)).toEqual(["Anthony Davis", "Anthony Davis", "Jalen Brunson", "Zach Edey"]);
    await userEvent.click(screen.getByRole("button", { name: "Line" }));
    expect(names().slice(-4)).toEqual(["Zach Edey", "Anthony Davis", "Anthony Davis", "Jalen Brunson"]);
    await userEvent.click(screen.getByRole("button", { name: "Odds" }));
    expect(names().at(-4)).toBe("Zach Edey");
  });

  it("sends filters to the API and clears them", async () => {
    const fetchMock = backend();
    renderWithProviders(<DashboardPage />);
    await screen.findByText("4 props");
    const [game, book, market, side] = screen.getAllByRole("combobox");
    await userEvent.selectOptions(game, "GSW @ LAL");
    await userEvent.selectOptions(book, "draftkings");
    await userEvent.selectOptions(market, "Rebounds");
    await userEvent.selectOptions(side, "under");
    await userEvent.type(screen.getByPlaceholderText("Search player…"), "Davis{Enter}");
    await waitFor(() => expect(calls(fetchMock).at(-3)).toBe(
      "GET /api/props?game=GSW+%40+LAL&player=Davis&bookmaker=draftkings&market=Rebounds&side=under"));
    await userEvent.type(screen.getByPlaceholderText("Search player…"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(calls(fetchMock).some(c => c.includes("player=Davisx"))).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(calls(fetchMock).at(-3)).toBe("GET /api/props"));
  });

  it("expands a row to show backing data and factors, and adds props to the slip", async () => {
    backend();
    renderWithProviders(<DashboardPage />);
    await screen.findByText("4 props");
    await userEvent.click(screen.getByText("Jalen Brunson"));
    expect(screen.getByText("season avg:")).toBeInTheDocument();
    expect(screen.getByText("8/10 over")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Jalen Brunson"));
    expect(screen.queryByText("season avg:")).toBeNull();
    const adds = screen.getAllByRole("button", { name: "+ Add" });
    expect(adds).toHaveLength(3);   // the prop without an id can't be added
    await userEvent.click(adds[0]);
    expect(screen.getByRole("button", { name: "In Slip" })).toBeDisabled();
  });

  it("explains an empty cache, and shows other errors as-is", async () => {
    backend({ "GET /api/props": () => fail(404) });
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText(/API \/api\/props.* → 404/)).toBeInTheDocument();
    expect(screen.getByText("No props match your filters.")).toBeInTheDocument();
  });

  it("lets admins refresh and polls until grading finishes", async () => {
    loginAs(true);
    let polls = 0;
    const fetchMock = backend({
      "POST /api/refresh": { status: "started" },
      "GET /api/refresh/status": () => {
        polls += 1;
        return { running: polls < 3, status: polls === 1 ? "prefetching logs" : "grading", props_graded: 5,
          props_total: 10, started_at: null, finished_at: null, run_id: 1, error: null };
      },
    });
    renderWithProviders(<DashboardPage />);
    await screen.findByText("4 props");
    await userEvent.click(screen.getByRole("button", { name: "↻ Refresh" }));
    expect(await screen.findByText("prefetching logs")).toBeInTheDocument();
    expect(await screen.findByText("Grading… 5/10", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(await screen.findByText("↻ Refresh", {}, { timeout: 3000 })).toBeInTheDocument();
    await waitFor(() => expect(calls(fetchMock).filter(c => c.startsWith("GET /api/props")).length).toBe(2));
  }, 10000);

  it("uses cards and a filter toggle on mobile", async () => {
    viewport.mobile = true;
    backend();
    renderWithProviders(<DashboardPage />);
    await screen.findByText("4 props");
    await screen.findByRole("button", { name: "Hide Filters" });
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));   // applying closes the panel on mobile
    expect(screen.queryByPlaceholderText("Search player…")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Filters" }));
    expect(screen.getByPlaceholderText("Search player…")).toBeInTheDocument();
    const card = screen.getAllByText("Jalen Brunson")[0].closest("div[style*='border-radius: 10px']") as HTMLElement;
    await userEvent.click(within(card).getByRole("button", { name: "+" }));
    expect(within(card).getByRole("button", { name: "✓" })).toBeDisabled();
    await userEvent.click(within(card).getByText("Jalen Brunson"));
    expect(within(card).getByText("8/10 over")).toBeInTheDocument();
    expect(screen.getByText("⚠")).toBeInTheDocument();
  });
});
