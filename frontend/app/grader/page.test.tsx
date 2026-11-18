import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import GraderPage from "./page";
import { viewport } from "@/vitest.setup";
import { calls, fail, makeProp, mockBackend } from "@/test-utils";

const PLAYERS = [
  { player_name: "Jalen Brunson", player_id: 1628973, team: "NYK" },
  { player_name: "Jayson Tatum", player_id: 1628369, team: "BOS" },
  { player_name: "Derrick White", player_id: 1628401, team: "BOS" },
  { player_name: "Stephen Curry", player_id: 201939, team: "GSW" },
];
const GAMES = [{ game_id: "g1", home_team: "BOS", away_team: "NYK", matchup: "NYK @ BOS", game_date: "2026-11-18" }];

const backend = (grade: unknown = makeProp({ suspicious_line: true, suspicious_reason: "line far below average" })) =>
  mockBackend({ "GET /api/players": PLAYERS, "GET /api/tonight": GAMES, "POST /api/grade-custom": grade });
const lineInput = () => document.querySelector('input[type="number"]') as HTMLInputElement;

describe("GraderPage", () => {
  it("browses a game's roster by team and grades a pick", async () => {
    const fetchMock = backend();
    render(<GraderPage />);
    expect(screen.getByText("Pick a game to browse players")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Select a player to grade" })).toBeDisabled();
    await userEvent.click(await screen.findByRole("button", { name: "NYK @ BOS" }));
    const names = screen.getAllByText(/^(Jalen Brunson|Jayson Tatum|Derrick White|Stephen Curry)$/).map(e => e.textContent);
    expect(names).toEqual(["Jalen Brunson", "Derrick White", "Jayson Tatum"]);   // away first, each sorted; GSW not in game
    await userEvent.hover(screen.getByText("Derrick White"));
    await userEvent.unhover(screen.getByText("Derrick White"));
    await userEvent.click(screen.getByText("Jalen Brunson"));
    await userEvent.click(screen.getByRole("button", { name: "R+A" }));
    await userEvent.click(screen.getByRole("button", { name: "UNDER" }));
    await userEvent.click(screen.getByRole("button", { name: "+" }));
    await userEvent.click(screen.getByRole("button", { name: "Grade Brunson Under 11.5 R+A" }));
    expect(await screen.findByText("Jalen Brunson", { selector: "div" })).toBeInTheDocument();
    expect(screen.getByText(/line far below average/)).toBeInTheDocument();
    expect(screen.getByText("8/10 over")).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/grade-custom"))!;
    expect(JSON.parse(String(post[1]?.body))).toEqual({
      player_name: "Jalen Brunson", player_id: 1628973, market: "player_rebounds_assists", line: 11.5, side: "under",
    });
    await userEvent.click(screen.getByRole("button", { name: "NYK @ BOS" }));   // toggles the browser closed
    expect(screen.getByText("Pick a game to browse players")).toBeInTheDocument();
  });

  it("searches players by name or team and clears the selection", async () => {
    backend();
    render(<GraderPage />);
    const search = await screen.findByPlaceholderText("Search any player...");
    await userEvent.type(search, "j");
    expect(screen.queryByText("Jayson Tatum")).toBeNull();   // needs 2+ characters
    await userEvent.type(search, "a");
    expect(screen.getByText("Jalen Brunson")).toBeInTheDocument();
    await userEvent.clear(search);
    await userEvent.type(search, "gsw");
    const option = screen.getByText("Stephen Curry");
    await userEvent.hover(option);
    await userEvent.unhover(option);
    fireEvent.mouseDown(option);
    expect(screen.getByText("GSW")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "×" }));
    expect(screen.getByPlaceholderText("Search any player...")).toBeInTheDocument();
  });

  it("closes the dropdown on blur", async () => {
    backend();
    render(<GraderPage />);
    const search = await screen.findByPlaceholderText("Search any player...");
    await userEvent.type(search, "cur");
    expect(screen.getByText("Stephen Curry")).toBeInTheDocument();
    fireEvent.blur(search);
    await waitFor(() => expect(screen.queryByText("Stephen Curry")).toBeNull());
  });

  it("validates the line and adjusts it within bounds", async () => {
    const fetchMock = backend();
    render(<GraderPage />);
    await userEvent.click(await screen.findByRole("button", { name: "NYK @ BOS" }));
    await userEvent.click(screen.getByText("Jayson Tatum"));
    await userEvent.clear(lineInput());
    await userEvent.click(screen.getByRole("button", { name: "−" }));
    expect(lineInput().value).toBe("0.5");   // floors at 0.5
    await userEvent.clear(lineInput());
    await userEvent.type(lineInput(), "-3");
    await userEvent.click(screen.getByRole("button", { name: /^Grade Tatum/ }));
    expect(screen.getByText("Enter a valid line (e.g. 10.5)")).toBeInTheDocument();
    expect(calls(fetchMock)).not.toContain("POST /api/grade-custom");
  });

  it("shows the API's error detail, or the raw message", async () => {
    let n = 0;
    mockBackend({
      "GET /api/players": PLAYERS, "GET /api/tonight": GAMES,
      "POST /api/grade-custom": () => (++n === 1 ? fail(404, { detail: "No game log for player" }) : fail(500, "kaput")),
    });
    render(<GraderPage />);
    await userEvent.click(await screen.findByRole("button", { name: "NYK @ BOS" }));
    await userEvent.click(screen.getByText("Jayson Tatum"));
    await userEvent.click(screen.getByRole("button", { name: /^Grade Tatum/ }));
    expect(await screen.findByText("No game log for player")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^Grade Tatum/ }));
    expect(await screen.findByText("kaput")).toBeInTheDocument();
  });

  it("copes with the player list failing to load, on mobile", async () => {
    viewport.mobile = true;
    mockBackend({ "GET /api/players": () => fail(500), "GET /api/tonight": () => fail(500) });
    render(<GraderPage />);
    expect(screen.getByPlaceholderText("Loading players...")).toBeDisabled();
    expect(await screen.findByPlaceholderText("Search any player...")).toBeEnabled();
    expect(screen.queryByRole("button", { name: "NYK @ BOS" })).toBeNull();
  });

  it("renders an over result on mobile", async () => {
    viewport.mobile = true;
    backend(makeProp({ backing_data: undefined as unknown as Record<string, unknown> }));
    render(<GraderPage />);
    await userEvent.click(await screen.findByRole("button", { name: "NYK @ BOS" }));
    await userEvent.click(screen.getByText("Jalen Brunson"));
    await userEvent.click(screen.getByRole("button", { name: /^Grade Brunson Over/ }));
    expect(await screen.findByText("25.5 Points")).toBeInTheDocument();
    expect(screen.queryByText("season avg:")).toBeNull();
  });
});
