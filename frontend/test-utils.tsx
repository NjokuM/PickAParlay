// Shared helpers for page tests: a fake backend behind `fetch`, and the app's providers.
import { vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import type { ReactElement } from "react";
import { SlipBuilderProvider } from "@/lib/slip-builder-context";
import { OddsFormatProvider } from "@/lib/odds";
import { setAuth } from "@/lib/auth";
import type { Prop, PropResult, Slip } from "@/lib/api";

type Reply = unknown | ((url: URL, init?: RequestInit) => unknown);
export interface Fail { status: number; body?: unknown }
/** Return from a route handler to answer with an HTTP error (a string body is sent raw). */
export const fail = (status: number, body: unknown = { detail: "error" }): Fail & { __fail: true } =>
  ({ status, body, __fail: true });

/**
 * Stub `fetch` with routes keyed "METHOD /path" (query string ignored).
 * A route's value is the JSON body, or a function of (url, init) returning one
 * (or `fail(...)`). Unknown routes answer 404. Returns the fetch mock.
 */
export function mockBackend(routes: Record<string, Reply>) {
  const fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const key = `${(init?.method ?? "GET").toUpperCase()} ${url.pathname}`;
    if (!(key in routes)) return new Response(JSON.stringify({ detail: `no route ${key}` }), { status: 404 });
    const route = routes[key];
    const out = typeof route === "function" ? (route as (u: URL, i?: RequestInit) => unknown)(url, init) : route;
    if (out && typeof out === "object" && "__fail" in out) {
      const f = out as unknown as Fail;
      return new Response(typeof f.body === "string" ? f.body : JSON.stringify(f.body), { status: f.status });
    }
    return new Response(JSON.stringify(out), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Requests the page made, as "METHOD /path?query". */
export const calls = (fetchMock: ReturnType<typeof mockBackend>) =>
  fetchMock.mock.calls.map(([u, i]) => {
    const url = new URL(String(u));
    return `${(i?.method ?? "GET").toUpperCase()} ${url.pathname}${url.search}`;
  });

export function loginAs(isAdmin = false) {
  setAuth("tok", { user_id: 1, username: "mike", display_name: "Mike", is_admin: isAdmin });
}

export const renderWithProviders = (ui: ReactElement) =>
  render(<OddsFormatProvider><SlipBuilderProvider>{ui}</SlipBuilderProvider></OddsFormatProvider>);

export function makeProp(over: Partial<Prop> = {}): Prop {
  return {
    prop_id: 1, player_name: "Jalen Brunson", player_id: 1628973, market: "player_points",
    market_label: "Points", line: 25.5, side: "over", over_odds: 1.9, bookmaker: "fanduel",
    is_paddy_power: false, value_score: 72, recommendation: "STRONG", game: "NYK @ BOS",
    game_date: "2026-11-18", suspicious_line: false, suspicious_reason: "",
    hit_probability: 0.58, market_probability: 0.52, edge: 0.06, is_special: false,
    factors: [{ name: "Consistency", score: 80, weight: 0.2, evidence: ["8/10 over"] }],
    backing_data: { season_avg: 27.1, tonight_home: false, nested: { x: 1 } },
    ...over,
  };
}

export function makeSlip(legCount: number, over: Partial<Slip> = {}): Slip {
  const legs = Array.from({ length: legCount }, (_, i) => {
    const { prop_id: _id, suspicious_line: _s, suspicious_reason: _r, game_date: _d, backing_data: _b, ...leg } =
      makeProp({ player_name: `Player ${i + 1}`, player_id: 100 + i, line: 10.5 + i });
    return leg;
  });
  return {
    combined_odds: 3.61, target_decimal: null, target_odds_str: "", avg_value_score: 71.25,
    has_correlated_legs: false, summary: "", legs, ...over,
  };
}

export function makePropResult(over: Partial<PropResult> = {}): PropResult {
  return {
    id: 1, player_name: "Jalen Brunson", nba_player_id: 1628973, market: "player_points", market_label: "Points",
    line: 25.5, side: "over", game_date: "2026-11-17", over_odds: 1.9, under_odds: 1.9, decimal_odds: 1.9,
    bookmaker: "fanduel", is_paddy_power: 0, is_alternate: 0, value_score: 72, recommendation: "Strong Value",
    is_best_side: 1, is_active: 1, leg_result: null, matchup: "NYK @ BOS", graded_at: "2026-11-17T18:00:00",
    result_at: null, score_consistency: 80, score_opponent_defense: 60, score_vs_opponent: null, score_home_away: 55,
    score_injury: 50, score_team_context: null, score_season_avg: 70, score_blowout_risk: 52, score_volume_context: 64,
    ...over,
  };
}

/** Move a range slider (user-event can't type into one). */
export function setRange(slider: HTMLElement, value: number) {
  fireEvent.change(slider, { target: { value: String(value) } });
}
