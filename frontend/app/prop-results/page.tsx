"use client";

import { useEffect, useRef, useState } from "react";
import { api, PropResult, ResultsStatus } from "@/lib/api";
import { ScoreBadge, LegResultBadge } from "@/components/Badge";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function nDaysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function bookmakerLabel(b: string) {
  const m: Record<string, string> = {
    paddypower: "Paddy Power", draftkings: "DraftKings",
    fanduel: "FanDuel", betmgm: "BetMGM",
  };
  return m[b] ?? b;
}

// ─── Summary computations ─────────────────────────────────────────────────────

interface MarketStat { label: string; total: number; hits: number; pct: number }
interface PlayerStat {
  player: string; market: string;
  total: number; hits: number; hit_pct: number; avg_score: number;
  pending?: number;
}

function computeMarketStats(rows: PropResult[]): MarketStat[] {
  const acc: Record<string, { total: number; hits: number }> = {};
  for (const r of rows) {
    if (r.leg_result == null) continue;          // skip ungraded
    const m = r.market_label;
    if (!acc[m]) acc[m] = { total: 0, hits: 0 };
    acc[m].total++;
    if (r.leg_result === "HIT") acc[m].hits++;
  }
  return Object.entries(acc)
    .map(([label, s]) => ({ label, ...s, pct: s.total ? Math.round(s.hits / s.total * 100) : 0 }))
    .sort((a, b) => b.pct - a.pct);
}

function computePlayerStats(rows: PropResult[]): PlayerStat[] {
  const acc: Record<string, {
    player: string; market: string;
    graded: number; hits: number; scores: number[];
    pending: number;
  }> = {};
  for (const r of rows) {
    const key = `${r.player_name}||${r.market_label}`;
    if (!acc[key]) acc[key] = { player: r.player_name, market: r.market_label, graded: 0, hits: 0, scores: [], pending: 0 };
    acc[key].scores.push(r.value_score ?? 0);
    if (r.leg_result == null) { acc[key].pending++; continue; }
    acc[key].graded++;
    if (r.leg_result === "HIT") acc[key].hits++;
  }
  return Object.values(acc)
    .map(v => ({
      player:    v.player,
      market:    v.market,
      total:     v.graded,                     // graded count for hit-rate calc
      hits:      v.hits,
      hit_pct:   v.graded ? Math.round(v.hits / v.graded * 100) : 0,
      avg_score: Math.round(v.scores.reduce((a, b) => a + b, 0) / v.scores.length),
      pending:   v.pending,
    }))
    .sort((a, b) => b.total - a.total || b.hit_pct - a.hit_pct);
}

// ─── Small inline bar ─────────────────────────────────────────────────────────

function PctBar({ pct, hits, total }: { pct: number; hits: number; total: number }) {
  const color = pct >= 60 ? "var(--green)" : pct >= 45 ? "var(--accent)" : "var(--red)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: "var(--surface2)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 12, minWidth: 60, color, fontWeight: 600 }}>
        {pct}% ({hits}/{total})
      </span>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

const MARKETS = [
  "", "Points", "Assists", "Rebounds", "3-Pointers Made",
  "Blocks", "Steals", "Turnovers",
  "Pts+Reb+Ast", "Pts+Reb", "Pts+Ast", "Reb+Ast",
];

export default function PropResultsPage() {
  const [dateFrom,   setDateFrom]   = useState(nDaysAgo(7));
  const [dateTo,     setDateTo]     = useState(today());
  const [player,     setPlayer]     = useState("");
  const [market,     setMarket]     = useState("");
  const [minScore,   setMinScore]   = useState(0);
  const [side,       setSide]       = useState<"" | "over" | "under">("");
  const [result,     setResult]     = useState<"" | "HIT" | "MISS">("");
  const [picksOnly,  setPicksOnly]  = useState(true);
  const [activeOnly, setActiveOnly] = useState(true);
  const [gradedOnly, setGradedOnly] = useState(true);
  const [view,       setView]       = useState<"table" | "players">("table");
  const [rows,       setRows]       = useState<PropResult[]>([]);
  const [loading,    setLoading]    = useState(false);
  const [loaded,     setLoaded]     = useState(false);

  // ── Check Results state ─────────────────────────────────────────────────
  const [checkDate,   setCheckDate]   = useState(nDaysAgo(1));
  const [checkStatus, setCheckStatus] = useState<ResultsStatus | null>(null);
  const [checking,    setChecking]    = useState(false);
  const checkPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function autoCheck() {
    setChecking(true);
    setCheckStatus(null);
    try {
      await api.results.check(checkDate);
      const initial = await api.results.status();
      setCheckStatus(initial);
      if (initial.status === "running") {
        checkPollRef.current = setInterval(async () => {
          try {
            const s = await api.results.status();
            setCheckStatus(s);
            if (s.status !== "running") {
              clearInterval(checkPollRef.current!);
              checkPollRef.current = null;
              setChecking(false);
              if (s.status === "done") load();   // auto-refresh table
            }
          } catch { /* ignore poll errors */ }
        }, 2000);
      } else {
        setChecking(false);
        if (initial.status === "done") load();
      }
    } catch (e) {
      console.error(e);
      setChecking(false);
    }
  }

  // Cleanup poll on unmount
  useEffect(() => () => {
    if (checkPollRef.current) clearInterval(checkPollRef.current);
  }, []);

  async function load() {
    setLoading(true);
    try {
      const data = await api.propResults({
        date_from:   dateFrom || undefined,
        date_to:     dateTo   || undefined,
        player:      player   || undefined,
        market:      market   || undefined,
        min_score:   minScore > 0 ? minScore : undefined,
        side:        side     || undefined,
        result:      result   || undefined,
        picks_only:  picksOnly  || undefined,
        active_only: activeOnly || undefined,
        graded_only: gradedOnly,
        limit: 500,
      });
      setRows(data);
      setLoaded(true);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  // Summary stats — separate graded vs pending
  const total    = rows.length;
  const graded   = rows.filter(r => r.leg_result != null).length;
  const hits     = rows.filter(r => r.leg_result === "HIT").length;
  const misses   = rows.filter(r => r.leg_result === "MISS").length;
  const pending  = total - graded;
  const hitPct   = graded ? Math.round(hits / graded * 100) : 0;
  const byMarket = computeMarketStats(rows);
  const byPlayer = computePlayerStats(rows);

  const S: React.CSSProperties = {
    background: "var(--surface2)", border: "1px solid var(--border)",
    borderRadius: 6, padding: "6px 10px", color: "var(--text)",
    fontSize: 13, outline: "none",
  };
  const btn = (active?: boolean): React.CSSProperties => ({
    padding: "6px 14px", borderRadius: 6, border: "1px solid var(--border)",
    background: active ? "var(--accent)" : "var(--surface2)",
    color: active ? "#0d1117" : "var(--text)",
    cursor: "pointer", fontSize: 13, fontWeight: active ? 600 : 400,
  });
  const pill = (active?: boolean): React.CSSProperties => ({
    padding: "4px 12px", borderRadius: 4, border: "1px solid var(--border)",
    background: active ? "var(--accent)" : "var(--surface2)",
    color: active ? "#0d1117" : "var(--muted)",
    cursor: "pointer", fontSize: 12,
  });

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ margin: "0 0 4px", fontSize: 20, fontWeight: 700 }}>📊 Prop Results</h1>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>
          Individual prop leg outcomes — filter by date, player, market, or score to spot trends.
        </p>
      </div>

      {/* Filter controls */}
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "14px 16px", marginBottom: 20, display: "flex", flexWrap: "wrap", gap: 12, alignItems: "flex-end" }}>
        <div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>From</div>
          <input type="date" style={{ ...S, width: 136 }} value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
        </div>
        <div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>To</div>
          <input type="date" style={{ ...S, width: 136 }} value={dateTo} onChange={e => setDateTo(e.target.value)} />
        </div>
        <div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Player</div>
          <input style={{ ...S, width: 140 }} placeholder="Any player" value={player}
            onChange={e => setPlayer(e.target.value)}
            onKeyDown={e => e.key === "Enter" && load()} />
        </div>
        <div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Market</div>
          <select style={{ ...S, minWidth: 120 }} value={market} onChange={e => setMarket(e.target.value)}>
            {MARKETS.map(m => <option key={m} value={m}>{m || "All Markets"}</option>)}
          </select>
        </div>
        <div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>
            Min Score: <strong style={{ color: "var(--text)" }}>{minScore || "Any"}</strong>
          </div>
          <input type="range" min={0} max={90} step={5} value={minScore}
            onChange={e => setMinScore(Number(e.target.value))}
            style={{ width: 110, accentColor: "var(--accent)" }} />
        </div>
        <div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Side</div>
          <div style={{ display: "flex", gap: 4 }}>
            {(["", "over", "under"] as const).map(s => (
              <button key={s} style={pill(side === s)} onClick={() => setSide(s)}>
                {s === "" ? "All" : s === "over" ? "OVER" : "UNDER"}
              </button>
            ))}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Result</div>
          <div style={{ display: "flex", gap: 4 }}>
            {(["", "HIT", "MISS"] as const).map(r => (
              <button key={r} style={pill(result === r)} onClick={() => setResult(r)}>
                {r || "All"}
              </button>
            ))}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Filters</div>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            <button style={pill(picksOnly)} onClick={() => setPicksOnly(!picksOnly)}>
              Picks Only
            </button>
            <button style={pill(activeOnly)} onClick={() => setActiveOnly(!activeOnly)}>
              Active Only
            </button>
            <button style={pill(gradedOnly)} onClick={() => setGradedOnly(!gradedOnly)}>
              Graded Only
            </button>
          </div>
        </div>
        <button
          style={{ ...btn(true), padding: "8px 20px", opacity: loading ? 0.6 : 1 }}
          onClick={load} disabled={loading}
        >
          {loading ? "Loading…" : "Load Results"}
        </button>
      </div>

      {/* ── Check Results control ── */}
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "12px 16px", marginBottom: 20, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>Check Results</div>
        <input
          type="date"
          value={checkDate}
          onChange={e => setCheckDate(e.target.value)}
          style={{ ...S, width: 140 }}
        />
        <button
          style={{ ...btn(true), opacity: checking ? 0.6 : 1 }}
          onClick={autoCheck}
          disabled={checking}
        >
          {checking ? "Checking…" : "Check Results"}
        </button>

        {checkStatus && (
          <div style={{ display: "flex", gap: 12, alignItems: "center", fontSize: 12 }}>
            {checkStatus.status === "running" && (
              <span style={{ color: "var(--accent)" }}>Fetching box scores…</span>
            )}
            {checkStatus.status === "done" && (
              <>
                <span style={{ color: "var(--green)", fontWeight: 600 }}>
                  ✓ {checkStatus.hit} HIT / {checkStatus.miss} MISS
                  {checkStatus.no_data > 0 && ` · ${checkStatus.no_data} no data`}
                </span>
                {checkStatus.slips_resolved > 0 && (
                  <span style={{ color: "var(--accent)" }}>
                    {checkStatus.slips_resolved} slip{checkStatus.slips_resolved !== 1 ? "s" : ""} auto-resolved
                  </span>
                )}
              </>
            )}
            {checkStatus.status === "error" && (
              <span style={{ color: "var(--red)" }}>Error: {checkStatus.error}</span>
            )}
          </div>
        )}

        {!checkStatus && loaded && pending > 0 && !checking && (
          <span style={{ fontSize: 12, color: "var(--muted)" }}>
            {pending} props pending — select a date and check to grade them
          </span>
        )}

        <div style={{ marginLeft: "auto", fontSize: 11, color: "var(--muted)" }}>
          Grades props from NBA box scores
        </div>
      </div>

      {/* Summary stats — only shown when data loaded */}
      {loaded && total > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "auto auto 1fr", gap: 12, marginBottom: 20 }}>
          {/* KPI pills */}
          <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "12px 20px", textAlign: "center" }}>
            <div style={{ fontSize: 24, fontWeight: 700 }}>{total}</div>
            <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>
              {pending > 0 ? `${graded} graded · ${pending} pending` : "Graded props"}
            </div>
          </div>
          <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "12px 20px", textAlign: "center" }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: graded === 0 ? "var(--muted)" : hitPct >= 55 ? "var(--green)" : hitPct >= 45 ? "var(--accent)" : "var(--red)" }}>
              {graded === 0 ? "—" : `${hitPct}%`}
            </div>
            <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>{hits} HIT · {misses} MISS</div>
          </div>
          {/* Market breakdown */}
          <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "12px 16px" }}>
            <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 8 }}>Hit rate by market</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 24px" }}>
              {byMarket.map(m => (
                <div key={m.label}>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 2 }}>{m.label}</div>
                  <PctBar pct={m.pct} hits={m.hits} total={m.total} />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {loaded && total === 0 && (
        <div style={{ color: "var(--muted)", padding: "40px 0", textAlign: "center", fontSize: 14 }}>
          No graded props found for those filters. Try widening the date range or running Auto-Check Results in History.
        </div>
      )}

      {/* View toggle */}
      {total > 0 && (
        <div style={{ display: "flex", gap: 6, marginBottom: 14, alignItems: "center" }}>
          <button style={btn(view === "table")}   onClick={() => setView("table")}>Results Table</button>
          <button style={btn(view === "players")} onClick={() => setView("players")}>By Player</button>
          <span style={{ fontSize: 12, color: "var(--muted)", marginLeft: 8 }}>
            {total} props{pending > 0 ? ` (${pending} pending)` : ""}
          </span>
        </div>
      )}

      {/* ── Results Table ── */}
      {view === "table" && rows.length > 0 && (
        <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
          {/* Table header */}
          <div style={{ display: "grid", gridTemplateColumns: "90px 160px 110px 60px 55px 60px 70px 60px 110px", gap: 0, padding: "8px 12px", borderBottom: "1px solid var(--border)", fontSize: 11, color: "var(--muted)", fontWeight: 600 }}>
            <span>Date</span>
            <span>Player</span>
            <span>Market</span>
            <span>Side</span>
            <span>Line</span>
            <span>Score</span>
            <span>Result</span>
            <span>Odds</span>
            <span>Matchup</span>
          </div>
          {rows.map(r => (
            <div key={r.id} style={{
              display: "grid", gridTemplateColumns: "90px 160px 110px 60px 55px 60px 70px 60px 110px",
              gap: 0, padding: "7px 12px", borderBottom: "1px solid var(--border)", fontSize: 13,
              alignItems: "center", opacity: r.is_active === 0 ? 0.45 : 1,
            }}>
              <span style={{ fontSize: 11, color: "var(--muted)" }}>{r.game_date ?? "—"}</span>
              <span style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: 4 }}>
                {r.player_name}
                {r.is_best_side === 1 && <span style={{ fontSize: 9, background: "var(--accent)", color: "#0d1117", padding: "1px 4px", borderRadius: 3, fontWeight: 700, flexShrink: 0 }}>PICK</span>}
              </span>
              <span style={{ fontSize: 12, color: "var(--muted)" }}>{r.market_label}</span>
              <span style={{ fontSize: 11, color: r.side === "under" ? "var(--orange)" : "var(--accent)" }}>
                {(r.side ?? "over").toUpperCase()}
              </span>
              <span>{r.line}</span>
              <ScoreBadge score={r.value_score ?? 0} />
              {r.leg_result ? (
                <LegResultBadge result={r.leg_result} />
              ) : (
                <span style={{ fontSize: 11, color: "var(--muted)" }}>—</span>
              )}
              <span style={{ color: "var(--muted)", fontSize: 12 }}>{r.decimal_odds?.toFixed(2) ?? "—"}</span>
              <span style={{ fontSize: 11, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.matchup ?? (r.is_paddy_power ? "🍀 PP" : bookmakerLabel(r.bookmaker))}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* ── By Player View ── */}
      {view === "players" && total > 0 && (
        <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
          {/* Header */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 130px 70px 70px 100px 80px", gap: 0, padding: "8px 12px", borderBottom: "1px solid var(--border)", fontSize: 11, color: "var(--muted)", fontWeight: 600 }}>
            <span>Player</span>
            <span>Market</span>
            <span>Graded</span>
            <span>Hits</span>
            <span style={{ minWidth: 160 }}>Hit Rate</span>
            <span>Avg Score</span>
          </div>
          {byPlayer.map((p, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 130px 70px 70px 100px 80px", gap: 0, padding: "8px 12px", borderBottom: "1px solid var(--border)", fontSize: 13, alignItems: "center" }}>
              <span style={{ fontWeight: 600 }}>{p.player}</span>
              <span style={{ fontSize: 12, color: "var(--muted)" }}>{p.market}</span>
              <span style={{ color: "var(--muted)" }}>
                {p.total}{(p.pending ?? 0) > 0 && <span style={{ fontSize: 10, color: "var(--orange)" }}> +{p.pending}</span>}
              </span>
              <span style={{ color: "var(--green)" }}>{p.hits}</span>
              <div style={{ paddingRight: 16 }}>
                {p.total > 0 ? (
                  <PctBar pct={p.hit_pct} hits={p.hits} total={p.total} />
                ) : (
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>pending</span>
                )}
              </div>
              <ScoreBadge score={p.avg_score} />
            </div>
          ))}
        </div>
      )}

      {!loaded && (
        <div style={{ color: "var(--muted)", padding: "40px 0", textAlign: "center", fontSize: 14 }}>
          Set filters and click <strong style={{ color: "var(--text)" }}>Load Results</strong> to view graded props.
        </div>
      )}
    </div>
  );
}
