"use client";

import { useEffect, useState, useCallback } from "react";
import { api, Prop, Game, RefreshStatus } from "@/lib/api";
import { FactorGrid } from "@/components/FactorBar";
import { ScoreBadge, RecoBadge } from "@/components/Badge";
import { PlayerHeadshot } from "@/components/PlayerHeadshot";

const MARKETS = [
  "All Markets", "Points", "Assists", "Rebounds", "Pts+Reb+Ast",
  "Pts+Reb", "Pts+Ast", "Reb+Ast", "3-Pointers Made", "Blocks", "Steals", "Turnovers",
];

function bookmakerLabel(b: string) {
  const map: Record<string, string> = {
    paddypower: "Paddy Power", draftkings: "DraftKings",
    fanduel: "FanDuel", betmgm: "BetMGM", bovada: "Bovada",
  };
  return map[b] ?? b;
}

interface Filters {
  minScore: number; game: string; player: string; bookmaker: string; market: string; side: "" | "over" | "under";
}

export default function DashboardPage() {
  const [props, setProps]           = useState<Prop[]>([]);
  const [games, setGames]           = useState<Game[]>([]);
  const [bookmakers, setBookmakers] = useState<string[]>([]);
  const [filters, setFilters]       = useState<Filters>({ minScore: 0, game: "", player: "", bookmaker: "", market: "", side: "" });
  const [expanded, setExpanded]     = useState<string | null>(null);
  const [loading, setLoading]       = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshStatus, setRefreshStatus] = useState<RefreshStatus | null>(null);
  const [error, setError]           = useState<string | null>(null);
  const [playerInput, setPlayerInput] = useState("");
  const [sortKey, setSortKey]       = useState<"value_score" | "line" | "over_odds" | "player_name">("value_score");

  const fetchData = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [p, g, b] = await Promise.all([
        api.props({
          min_score: filters.minScore || undefined,
          game: filters.game || undefined,
          player: filters.player || undefined,
          bookmaker: filters.bookmaker || undefined,
          market: filters.market === "All Markets" || !filters.market ? undefined : filters.market,
          side: filters.side || undefined,
        }),
        api.tonight(), api.bookmakers(),
      ]);
      setProps(p); setGames(g); setBookmakers(b);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally { setLoading(false); }
  }, [filters]);

  useEffect(() => { fetchData(); }, [fetchData]);

  useEffect(() => {
    if (!refreshing) return;
    const id = setInterval(async () => {
      const s = await api.refreshStatus();
      setRefreshStatus(s);
      if (!s.running) { setRefreshing(false); clearInterval(id); setTimeout(fetchData, 500); }
    }, 1500);
    return () => clearInterval(id);
  }, [refreshing, fetchData]);

  async function handleRefresh() {
    setRefreshing(true); setError(null);
    await api.refresh();
    setRefreshStatus(await api.refreshStatus());
  }

  const setFilter = <K extends keyof Filters>(k: K, v: Filters[K]) =>
    setFilters(f => ({ ...f, [k]: v }));

  const sorted = [...props].sort((a, b) =>
    sortKey === "player_name" ? a.player_name.localeCompare(b.player_name)
    : sortKey === "line" || sortKey === "over_odds" ? a[sortKey] - b[sortKey]
    : b[sortKey] - a[sortKey]
  );

  const S: React.CSSProperties = { background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6, padding: "6px 10px", color: "var(--text)", fontSize: 13, outline: "none" };
  const btn = (active?: boolean): React.CSSProperties => ({ padding: "6px 12px", borderRadius: 6, border: "1px solid var(--border)", background: active ? "var(--accent)" : "var(--surface2)", color: active ? "#0d1117" : "var(--text)", cursor: "pointer", fontSize: 13, fontWeight: active ? 600 : 400 });

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Tonight&apos;s Props</h1>
          {games.length > 0 && (
            <p style={{ margin: "4px 0 0", color: "var(--muted)", fontSize: 13 }}>
              {games.length} game{games.length !== 1 ? "s" : ""}: {games.map(g => g.matchup).join(" · ")}
            </p>
          )}
        </div>
        <button onClick={handleRefresh} disabled={refreshing} style={{ ...btn(false), color: "var(--accent)", borderColor: "var(--accent)" }}>
          {refreshing ? `Grading… ${refreshStatus?.props_graded ?? 0}/${refreshStatus?.props_total ?? "?"}` : "↻ Refresh"}
        </button>
      </div>

      {error && (
        <div style={{ padding: "10px 14px", borderRadius: 6, background: "#2d1e1e", border: "1px solid var(--red)", color: "var(--red)", marginBottom: 16, fontSize: 13 }}>
          {error.includes("cached") ? <>No cached props — click <strong>↻ Refresh</strong> to fetch tonight&apos;s props.</> : error}
        </div>
      )}

      {/* Filters */}
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "14px 16px", marginBottom: 16, display: "flex", flexWrap: "wrap", gap: 10, alignItems: "flex-end" }}>
        <div><div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Game</div>
          <select style={{ ...S, minWidth: 140 }} value={filters.game} onChange={e => setFilter("game", e.target.value)}>
            <option value="">All Games</option>
            {games.map(g => <option key={g.game_id} value={g.matchup}>{g.matchup}</option>)}
          </select></div>

        <div><div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Sportsbook</div>
          <select style={{ ...S, minWidth: 120 }} value={filters.bookmaker} onChange={e => setFilter("bookmaker", e.target.value)}>
            <option value="">All Books</option>
            {bookmakers.map(b => <option key={b} value={b}>{bookmakerLabel(b)}</option>)}
          </select></div>

        <div><div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Market</div>
          <select style={{ ...S, minWidth: 130 }} value={filters.market} onChange={e => setFilter("market", e.target.value)}>
            {MARKETS.map(m => <option key={m} value={m === "All Markets" ? "" : m}>{m}</option>)}
          </select></div>

        <div><div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Side</div>
          <select style={{ ...S, minWidth: 90 }} value={filters.side} onChange={e => setFilter("side", e.target.value as "" | "over" | "under")}>
            <option value="">Both</option>
            <option value="over">Over</option>
            <option value="under">Under</option>
          </select></div>

        <div><div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Player</div>
          <input style={{ ...S, minWidth: 150 }} placeholder="Search player…" value={playerInput}
            onChange={e => setPlayerInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && setFilter("player", playerInput)} /></div>

        <div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Min Score: <strong style={{ color: "var(--text)" }}>{filters.minScore}</strong></div>
          <input type="range" min={0} max={90} step={5} value={filters.minScore} onChange={e => setFilter("minScore", Number(e.target.value))} style={{ width: 120, accentColor: "var(--accent)" }} />
        </div>

        <div style={{ display: "flex", gap: 6 }}>
          <button style={btn(true)} onClick={() => setFilter("player", playerInput)}>Apply</button>
          <button style={btn()} onClick={() => { setFilters({ minScore: 0, game: "", player: "", bookmaker: "", market: "", side: "" }); setPlayerInput(""); }}>Clear</button>
        </div>
      </div>

      {/* Sort + count */}
      <div style={{ display: "flex", gap: 6, marginBottom: 10, alignItems: "center" }}>
        <span style={{ color: "var(--muted)", fontSize: 12 }}>Sort:</span>
        {(["value_score", "player_name", "line", "over_odds"] as const).map(k => (
          <button key={k} style={btn(sortKey === k)} onClick={() => setSortKey(k)}>
            {k === "value_score" ? "Score" : k === "player_name" ? "Name" : k === "line" ? "Line" : "Odds"}
          </button>
        ))}
        <span style={{ marginLeft: "auto", color: "var(--muted)", fontSize: 12 }}>{sorted.length} props</span>
      </div>

      {/* Table */}
      {loading ? (
        <div style={{ color: "var(--muted)", padding: "60px 0", textAlign: "center" }}>Loading…</div>
      ) : sorted.length === 0 ? (
        <div style={{ color: "var(--muted)", padding: "60px 0", textAlign: "center" }}>No props match your filters.</div>
      ) : (
        <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
          {/* Header row */}
          <div style={{ display: "grid", gridTemplateColumns: "48px 52px 1fr 130px 80px 56px 72px 110px 20px", gap: "0 10px", padding: "8px 16px", background: "var(--surface2)", fontSize: 11, color: "var(--muted)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", borderBottom: "1px solid var(--border)" }}>
            <span>Score</span><span /><span>Player</span><span>Market</span><span>Line</span><span>Odds</span><span>Book</span><span>Game</span><span />
          </div>

          {sorted.map((p) => {
            const key = `${p.player_id}-${p.market}-${p.side ?? "over"}`;
            const isX = expanded === key;
            return (
              <div key={key}>
                <div onClick={() => setExpanded(isX ? null : key)} style={{ display: "grid", gridTemplateColumns: "48px 52px 1fr 130px 80px 56px 72px 110px 20px", gap: "0 10px", padding: "10px 16px", borderBottom: "1px solid var(--border)", cursor: "pointer", background: isX ? "var(--surface2)" : "transparent", alignItems: "center" }}>
                  <ScoreBadge score={p.value_score} />
                  <PlayerHeadshot playerId={p.player_id} size={40} />
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 13 }}>{p.player_name}</div>
                    <RecoBadge reco={p.recommendation} />
                    {p.suspicious_line && <span style={{ fontSize: 10, color: "var(--orange)", marginLeft: 6 }}>⚠ suspicious</span>}
                  </div>
                  <div style={{ fontSize: 13 }}>{p.market_label}</div>
                  <div style={{ fontSize: 13 }}>
                    <span style={{ fontSize: 10, fontWeight: 700, marginRight: 3, color: p.side === "under" ? "var(--orange)" : "var(--accent)" }}>
                      {(p.side ?? "over").toUpperCase()}
                    </span>
                    {p.line}
                  </div>
                  <div style={{ fontSize: 13, color: "var(--accent)" }}>{p.over_odds.toFixed(2)}</div>
                  <div style={{ fontSize: 12, color: "var(--muted)" }}>{p.is_paddy_power ? "🍀 PP" : p.bookmaker}</div>
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>{p.game}</div>
                  <div style={{ color: "var(--muted)" }}>{isX ? "▲" : "▼"}</div>
                </div>

                {isX && (
                  <div style={{ padding: "16px 24px", borderBottom: "1px solid var(--border)", background: "var(--bg)" }}>
                    <div style={{ marginBottom: 8, display: "flex", gap: 16, flexWrap: "wrap" }}>
                      {p.backing_data && Object.entries(p.backing_data).map(([k, v]) =>
                        typeof v !== "object" ? (
                          <span key={k} style={{ fontSize: 12, color: "var(--muted)" }}>
                            <strong style={{ color: "var(--text)" }}>{k.replace(/_/g, " ")}:</strong> {String(v)}
                          </span>
                        ) : null
                      )}
                    </div>
                    <FactorGrid factors={p.factors} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
