import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { setAuth } from "./auth";

type Call = { url: string; init: RequestInit };
let calls: Call[];
let status = 200;

beforeEach(() => {
  calls = [];
  status = 200;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return { ok: status < 400, status, json: async () => ({ ok: true }), text: async () => "boom" } as Response;
  }));
});
afterEach(() => vi.unstubAllGlobals());

const last = () => calls[calls.length - 1];

describe("api client", () => {
  it("sends the bearer token when logged in", async () => {
    setAuth("tok", { user_id: 1, username: "a", display_name: null, is_admin: false });
    await api.tonight();
    expect((last().init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
  });

  it("builds query strings for filtered endpoints", async () => {
    await api.props({ min_score: 60, game: "BOS", player: "Jane", bookmaker: "fanduel", market: "Pts+Reb", side: "over" });
    expect(last().url).toMatch(/\/api\/props\?.*min_score=60.*side=over/);
    await api.slips({ odds: "5/2", legs: 3, min_score: 55, bookmaker: "fanduel" });
    expect(last().url).toMatch(/odds=5%2F2|odds=5\/2/);
    await api.altProps({ market: "Points", player: "J", min_score: 50, side: "over", limit: 10 });
    await api.propResults({ market: "Points", player: "J", date_from: "2026-04-01", date_to: "2026-04-02", min_score: 50,
                            result: "HIT", side: "over", picks_only: true, active_only: true, graded_only: false, alt_filter: "all" });
    expect(last().url).toContain("/api/prop-results?");
    await api.analytics(65);
    expect(last().url).toContain("min_score=65");
    await api.analytics();
    expect(last().url).toMatch(/\/api\/analytics$/);
  });

  it("covers every endpoint and method", async () => {
    await Promise.all([
      api.bookmakers(), api.refreshStatus(), api.history(5), api.credits(), api.schedule(), api.tonightPlayers(),
      api.ladder.status(), api.ladder.results(), api.altRefresh.status(), api.results.status(), api.auth.me(),
    ]);
    await api.refresh("2026-27");
    expect(last().url).toContain("season=2026-27");
    await api.refresh();
    await api.ladder.trigger("2026-27"); await api.ladder.trigger(); await api.altRefresh.run();
    await api.results.check("2026-04-01");
    expect(last().url).toContain("game_date=2026-04-01");
    await api.saveSlip({ odds: "5/2", slip_index: 0 });
    await api.saveCustomSlip([1, 2]);
    expect(JSON.parse(last().init.body as string)).toEqual({ leg_ids: [1, 2] });
    await api.gradeCustom({ player_name: "J", player_id: 1, market: "player_points", line: 20.5, side: "over" });
    await api.auth.register({ username: "a", password: "b", invite_code: "c" });
    await api.auth.login({ username: "a", password: "b" });
    await api.recordOutcome(7, { outcome: "WIN" });
    expect(last().init.method).toBe("PATCH");
    expect(calls.length).toBeGreaterThan(20);
  });

  it("throws on errors and sends 401s to the login page", async () => {
    status = 500;
    await expect(api.tonight()).rejects.toThrow("/api/tonight → 500");
    await expect(api.refresh()).rejects.toThrow("boom");
    await expect(api.recordOutcome(1, { outcome: "WIN" })).rejects.toThrow("PATCH");
    status = 401;
    setAuth("tok", { user_id: 1, username: "a", display_name: null, is_admin: false });
    await expect(api.history()).rejects.toThrow();
    expect(localStorage.getItem("pap_token")).toBeNull();
  });
});
