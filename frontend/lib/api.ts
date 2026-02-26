const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body != null ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt);
  }
  return res.json();
}

async function patch<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: body != null ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`PATCH ${path} → ${res.status}`);
  return res.json();
}

// ─── Types ───────────────────────────────────────────────────────────────────

export interface Factor {
  name: string;
  score: number;
  weight: number;
  evidence?: string[];
  confidence?: number;
}

export interface Prop {
  player_name: string;
  player_id: number;
  market: string;
  market_label: string;
  line: number;
  side: "over" | "under";
  over_odds: number;
  bookmaker: string;
  is_paddy_power: boolean;
  value_score: number;
  recommendation: string;
  game: string;
  game_date: string;
  suspicious_line: boolean;
  suspicious_reason: string;
  factors: Factor[];
  backing_data: Record<string, unknown>;
}

export interface SlipLeg {
  player_name: string;
  market: string;
  market_label: string;
  line: number;
  side: "over" | "under";
  over_odds: number;
  bookmaker: string;
  is_paddy_power: boolean;
  value_score: number;
  recommendation: string;
  game: string;
  factors: Factor[];
}

export interface Slip {
  combined_odds: number;
  target_decimal: number;
  target_odds_str: string;
  avg_value_score: number;
  has_correlated_legs: boolean;
  summary: string;
  legs: SlipLeg[];
}

export interface SavedLeg {
  id: number;
  slip_id: number;
  player_name: string;
  market: string;
  market_label: string;
  line: number;
  over_odds: number;
  bookmaker: string;
  is_paddy_power: number;
  value_score: number;
  score_consistency: number | null;
  score_vs_opponent: number | null;
  score_home_away: number | null;
  score_injury: number | null;
  score_team_context: number | null;
  score_season_avg: number | null;
  score_blowout_risk: number | null;
  score_volume_context: number | null;
  leg_result: "HIT" | "MISS" | null;
}

export interface SavedSlip {
  id: number;
  run_id: number | null;
  saved_at: string;
  target_odds_str: string;
  target_decimal: number;
  combined_odds: number;
  avg_value_score: number;
  has_correlated: number;
  bookmaker_filter: string | null;
  outcome: "WIN" | "LOSS" | "VOID" | null;
  stake: number | null;
  profit_loss: number | null;
  result_at: string | null;
  legs: SavedLeg[];
}

export interface Analytics {
  overall: {
    total_slips: number;
    wins: number;
    win_rate: number;
    total_pnl: number;
  };
  by_market: { market_label: string; total: number; hits: number }[];
  calibration: { bucket: number; total: number; hits: number }[];
}

export interface Credits {
  used: number;
  remaining: number;
  total: number;
}

export interface RefreshStatus {
  running: boolean;
  started_at: string | null;
  finished_at: string | null;
  status: string;
  props_graded: number;
  props_total: number;
  run_id: number | null;
  error: string | null;
}

export interface Game {
  game_id: string;
  home_team: string;
  away_team: string;
  matchup: string;
  game_date: string;
}

// ─── API calls ────────────────────────────────────────────────────────────────

export const api = {
  tonight: () => get<Game[]>("/api/tonight"),

  props: (params?: {
    min_score?: number;
    game?: string;
    player?: string;
    bookmaker?: string;
    market?: string;
    side?: "over" | "under";
  }) => {
    const qs = new URLSearchParams();
    if (params?.min_score != null) qs.set("min_score", String(params.min_score));
    if (params?.game) qs.set("game", params.game);
    if (params?.player) qs.set("player", params.player);
    if (params?.bookmaker) qs.set("bookmaker", params.bookmaker);
    if (params?.market) qs.set("market", params.market);
    if (params?.side) qs.set("side", params.side);
    const q = qs.toString();
    return get<Prop[]>(`/api/props${q ? `?${q}` : ""}`);
  },

  bookmakers: () => get<string[]>("/api/bookmakers"),

  refresh: (season?: string) =>
    post<{ status: string }>(`/api/refresh${season ? `?season=${season}` : ""}`),

  refreshStatus: () => get<RefreshStatus>("/api/refresh/status"),

  slips: (params: {
    odds: string;
    legs?: number;
    min_score?: number;
    bookmaker?: string;
  }) => {
    const qs = new URLSearchParams({ odds: params.odds });
    if (params.legs != null) qs.set("legs", String(params.legs));
    if (params.min_score != null) qs.set("min_score", String(params.min_score));
    if (params.bookmaker) qs.set("bookmaker", params.bookmaker);
    return get<Slip[]>(`/api/slips?${qs.toString()}`);
  },

  saveSlip: (req: {
    odds: string;
    slip_index?: number;
    bookmaker?: string;
    legs?: number;
    min_score?: number;
  }) => post<{ slip_id: number; saved: boolean }>("/api/slips/save", req),

  history: (limit = 20) => get<SavedSlip[]>(`/api/history?limit=${limit}`),

  recordOutcome: (
    slipId: number,
    req: {
      outcome: "WIN" | "LOSS" | "VOID";
      stake?: number;
      leg_results?: Record<string, "HIT" | "MISS">;
    }
  ) => patch<{ updated: boolean }>(`/api/history/${slipId}/outcome`, req),

  analytics: () => get<Analytics>("/api/analytics"),

  credits: () => get<Credits>("/api/credits"),
};
