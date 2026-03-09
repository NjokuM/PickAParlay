"use client";

import { useEffect, useState, useRef } from "react";
import { api, Slip, LadderStatus, AltRefreshStatus, PropResult } from "@/lib/api";
import { FactorGrid } from "@/components/FactorBar";
import { ScoreBadge } from "@/components/Badge";
import { PlayerHeadshot } from "@/components/PlayerHeadshot";
import { useSlipBuilder } from "@/lib/slip-builder-context";

function bookmakerLabel(b: string) {
  const m: Record<string, string> = { paddypower: "Paddy Power", draftkings: "DraftKings", fanduel: "FanDuel", betmgm: "BetMGM" };
  return m[b] ?? b;
}

const btn = (active?: boolean): React.CSSProperties => ({
  padding: "6px 14px", borderRadius: 6, border: "1px solid var(--border)",
  background: active ? "var(--accent)" : "var(--surface2)",
  color: active ? "#0d1117" : "var(--text)",
  cursor: "pointer", fontSize: 13, fontWeight: active ? 600 : 400,
});

const S: React.CSSProperties = {
  background: "var(--surface2)", border: "1px solid var(--border)",
  borderRadius: 6, padding: "6px 10px", color: "var(--text)", fontSize: 13, outline: "none",
};

const statusLabel: Record<string, { text: string; color: string }> = {
  idle:     { text: "Not run yet",      color: "var(--muted)"  },
  running:  { text: "Searching…",       color: "var(--accent)" },
  done:     { text: "Done",             color: "var(--green)"  },
  no_games: { text: "No games tonight", color: "var(--muted)"  },
  no_props: { text: "No alternate props found", color: "var(--orange)" },
  error:    { text: "Error",            color: "var(--red)"    },
};

function scoreColor(s: number): string {
  if (s >= 80) return "var(--green)";
  if (s >= 65) return "#2ea043";
  if (s >= 50) return "var(--yellow)";
  return "var(--red)";
}

export default function LadderPage() {
  // Slip builder
  const { addLeg, isInSlip } = useSlipBuilder();

  // Ladder state
  const [status, setStatus]         = useState<LadderStatus | null>(null);
  const [slips, setSlips]           = useState<Slip[]>([]);
  const [expanded, setExpanded]     = useState<number | null>(null);
  const [triggering, setTriggering] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Alt refresh state
  const [refreshStatus, setRefreshStatus] = useState<AltRefreshStatus | null>(null);
  const [refreshing, setRefreshing]       = useState(false);
  const refreshPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Alt Lines browser state
  const [altProps, setAltProps]       = useState<PropResult[]>([]);
  const [altLoading, setAltLoading]   = useState(false);
  const [altMarket, setAltMarket]     = useState("");
  const [altPlayer, setAltPlayer]     = useState("");
  const [altMinScore, setAltMinScore] = useState(0);
  const [altSort, setAltSort]         = useState<"score" | "line" | "odds">("score");
  const [altExpanded, setAltExpanded] = useState<number | null>(null);

  // Active tab
  const [tab, setTab] = useState<"picks" | "alt">("picks");

  // Load status + alt props on mount
  useEffect(() => {
    api.ladder.status().then(setStatus).catch(() => {});
    api.ladder.results().then(setSlips).catch(() => {});
    api.altRefresh.status().then(setRefreshStatus).catch(() => {});
    loadAltProps();
  }, []);

  function loadAltProps() {
    setAltLoading(true);
    api.altProps({ limit: 500 }).then(setAltProps).catch(() => {}).finally(() => setAltLoading(false));
  }

  // Poll while running
  useEffect(() => {
    if (status?.status === "running") {
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.ladder.status();
          setStatus(s);
          if (s.status !== "running") {
            clearInterval(pollRef.current!);
            if (s.status === "done") {
              const results = await api.ladder.results();
              setSlips(results);
              loadAltProps();     // refresh alt props table too
            }
          }
        } catch { /* ignore */ }
      }, 2000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [status?.status]);

  // Poll alt refresh while running
  useEffect(() => {
    if (refreshStatus?.status === "running") {
      refreshPollRef.current = setInterval(async () => {
        try {
          const s = await api.altRefresh.status();
          setRefreshStatus(s);
          if (s.status !== "running") {
            clearInterval(refreshPollRef.current!);
            if (s.status === "done") loadAltProps();
          }
        } catch { /* ignore */ }
      }, 2000);
    }
    return () => { if (refreshPollRef.current) clearInterval(refreshPollRef.current); };
  }, [refreshStatus?.status]);

  async function runRefresh() {
    setRefreshing(true);
    try {
      await api.altRefresh.run();
      const s = await api.altRefresh.status();
      setRefreshStatus(s);
    } catch (e) {
      console.error(e);
    } finally {
      setRefreshing(false);
    }
  }

  async function runLadder() {
    setTriggering(true);
    setSlips([]);
    setExpanded(null);
    try {
      await api.ladder.trigger();
      const s = await api.ladder.status();
      setStatus(s);
    } catch (e) {
      console.error(e);
    } finally {
      setTriggering(false);
    }
  }

  const isRunning = status?.status === "running";
  const isRefreshing = refreshStatus?.status === "running";
  const sl = status ? statusLabel[status.status] ?? statusLabel.idle : statusLabel.idle;

  // Separate single-leg from multi-leg picks
  const singles = slips.filter(s => s.type === "single");
  const multis  = slips.filter(s => s.type !== "single");

  // Filtered + sorted alt props
  const filteredAlt = altProps
    .filter(p => {
      if (altMarket && !(p.market_label ?? "").toLowerCase().includes(altMarket.toLowerCase())) return false;
      if (altPlayer && !p.player_name.toLowerCase().includes(altPlayer.toLowerCase())) return false;
      if (altMinScore && p.value_score < altMinScore) return false;
      return true;
    })
    .sort((a, b) => {
      if (altSort === "score") return b.value_score - a.value_score;
      if (altSort === "line")  return b.line - a.line;
      return (b.decimal_odds ?? 0) - (a.decimal_odds ?? 0);
    });

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ margin: "0 0 4px", fontSize: 20, fontWeight: 700 }}>🪜 Ladder Challenge</h1>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>
          Find the highest-confidence bets at near even money (1.95–2.30 decimal)
          using alternate prop lines — multiple thresholds per player priced at different odds.
        </p>
      </div>

      {/* Controls bar */}
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "16px", marginBottom: 20, display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          {/* Refresh Alt Lines button */}
          <button
            style={{ ...btn(false), padding: "8px 20px", opacity: isRefreshing ? 0.6 : 1, borderColor: "var(--accent)", color: "var(--accent)" }}
            onClick={runRefresh}
            disabled={isRefreshing}
          >
            {isRefreshing ? "Refreshing…" : "Refresh Alt Lines"}
          </button>

          {/* Run Ladder button */}
          <button
            style={{ ...btn(true), padding: "8px 20px", opacity: isRunning || triggering ? 0.6 : 1 }}
            onClick={runLadder}
            disabled={isRunning || triggering}
          >
            {isRunning || triggering ? "Building…" : "Run Ladder"}
          </button>

          {/* Odds window badge */}
          <div style={{ marginLeft: "auto", padding: "4px 12px", borderRadius: 20, background: "var(--surface2)", border: "1px solid var(--border)", fontSize: 12, color: "var(--accent)", fontWeight: 600 }}>
            Target: 1.95 – 2.30
          </div>
        </div>

        {/* Status line */}
        <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 12, flexWrap: "wrap" }}>
          {/* Alt refresh status */}
          {refreshStatus && refreshStatus.status !== "idle" && (
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ color: "var(--muted)" }}>Refresh:</span>
              <span style={{ color: (statusLabel[refreshStatus.status] ?? statusLabel.idle).color, fontWeight: 600 }}>
                {(statusLabel[refreshStatus.status] ?? statusLabel.idle).text}
              </span>
              {refreshStatus.status === "running" && refreshStatus.props_total > 0 && (
                <span style={{ color: "var(--muted)" }}>{refreshStatus.props_graded}/{refreshStatus.props_total} graded</span>
              )}
              {refreshStatus.error && (
                <span style={{ color: "var(--red)", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{refreshStatus.error}</span>
              )}
            </div>
          )}

          {/* Ladder status */}
          {status && status.status !== "idle" && (
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ color: "var(--muted)" }}>Ladder:</span>
              <span style={{ color: sl.color, fontWeight: 600 }}>{sl.text}</span>
              {status.status === "done" && (
                <span style={{ color: "var(--muted)" }}>{slips.length} picks found</span>
              )}
              {status.error && (
                <span style={{ color: "var(--red)", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{status.error}</span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Tab toggle */}
      <div style={{ display: "flex", gap: 6, marginBottom: 20 }}>
        <button style={btn(tab === "picks")} onClick={() => setTab("picks")}>
          🎯 Ladder Picks {slips.length > 0 && `(${slips.length})`}
        </button>
        <button style={btn(tab === "alt")} onClick={() => setTab("alt")}>
          📊 Alt Lines Browser {altProps.length > 0 && `(${altProps.length})`}
        </button>
      </div>

      {/* ═════════════ TAB: Ladder Picks ═════════════ */}
      {tab === "picks" && (
        <>
          {slips.length === 0 && !isRunning && !triggering && (
            <div style={{ color: "var(--muted)", padding: "40px 0", textAlign: "center", fontSize: 14 }}>
              {status?.status === "idle" || !status
                ? 'Click "Run Ladder" to search for near even money picks using alternate lines.'
                : status?.status === "no_games" ? "No NBA games tonight."
                : status?.status === "no_props" ? "No alternate props available for tonight's games."
                : "No ladder picks found."}
            </div>
          )}

          {/* Single-leg picks */}
          {singles.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
                Single Picks
                <span style={{ fontSize: 11, fontWeight: 400, color: "var(--muted)" }}>— one leg at even money</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {singles.map((slip, idx) => (
                  <SlipCard key={`s-${idx}`} slip={slip} idx={idx} expanded={expanded} setExpanded={setExpanded} prefix="s" />
                ))}
              </div>
            </div>
          )}

          {/* Multi-leg parlays */}
          {multis.length > 0 && (
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
                Parlays at ~2.0
                <span style={{ fontSize: 11, fontWeight: 400, color: "var(--muted)" }}>— 2–4 legs combining to even money</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                {multis.map((slip, idx) => (
                  <SlipCard key={`m-${idx}`} slip={slip} idx={idx} expanded={expanded} setExpanded={setExpanded} prefix="m" />
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* ═════════════ TAB: Alt Lines Browser ═════════════ */}
      {tab === "alt" && (
        <>
          {/* Filters */}
          <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "14px 16px", marginBottom: 16, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
            <div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Player</div>
              <input style={{ ...S, width: 140 }} placeholder="Search…" value={altPlayer} onChange={e => setAltPlayer(e.target.value)} />
            </div>
            <div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Market</div>
              <input style={{ ...S, width: 130 }} placeholder="e.g. Points" value={altMarket} onChange={e => setAltMarket(e.target.value)} />
            </div>
            <div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Min Score: <strong style={{ color: "var(--text)" }}>{altMinScore || "All"}</strong></div>
              <input type="range" min={0} max={90} step={5} value={altMinScore} onChange={e => setAltMinScore(Number(e.target.value))} style={{ width: 120, accentColor: "var(--accent)" }} />
            </div>
            <div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Sort</div>
              <select style={{ ...S, width: 100 }} value={altSort} onChange={e => setAltSort(e.target.value as "score" | "line" | "odds")}>
                <option value="score">Score ↓</option>
                <option value="line">Line ↓</option>
                <option value="odds">Odds ↓</option>
              </select>
            </div>
            <div style={{ marginLeft: "auto", fontSize: 12, color: "var(--muted)" }}>
              {filteredAlt.length} prop{filteredAlt.length !== 1 ? "s" : ""}
            </div>
          </div>

          {altLoading ? (
            <div style={{ color: "var(--muted)", padding: "40px 0", textAlign: "center" }}>Loading alt lines…</div>
          ) : altProps.length === 0 ? (
            <div style={{ color: "var(--muted)", padding: "40px 0", textAlign: "center", fontSize: 14 }}>
              No alt lines available yet. Click <strong style={{ color: "var(--text)" }}>Refresh Alt Lines</strong> to fetch and grade alternate props for tonight&apos;s games.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {/* Table header */}
              <div style={{ display: "grid", gridTemplateColumns: "38px 40px 1fr 120px 70px 60px 70px 60px 90px 52px", gap: "0 10px", padding: "8px 12px", fontSize: 11, color: "var(--muted)", fontWeight: 600, borderBottom: "1px solid var(--border)" }}>
                <span>Score</span>
                <span></span>
                <span>Player</span>
                <span>Market</span>
                <span>Line</span>
                <span>Side</span>
                <span>Odds</span>
                <span>Reco</span>
                <span>Book</span>
                <span></span>
              </div>

              {filteredAlt.map(p => (
                <div key={p.id}>
                  <div
                    style={{ display: "grid", gridTemplateColumns: "38px 40px 1fr 120px 70px 60px 70px 60px 90px 52px", gap: "0 10px", padding: "8px 12px", alignItems: "center", background: altExpanded === p.id ? "var(--surface)" : "transparent", borderBottom: "1px solid var(--border)", cursor: "pointer" }}
                    onClick={() => setAltExpanded(altExpanded === p.id ? null : p.id)}
                  >
                    <ScoreBadge score={p.value_score} />
                    <PlayerHeadshot playerId={p.nba_player_id} size={36} />
                    <span style={{ fontWeight: 600, fontSize: 13 }}>{p.player_name}</span>
                    <span style={{ fontSize: 12, color: "var(--muted)" }}>{p.market_label}</span>
                    <span style={{ fontSize: 13, fontWeight: 600 }}>{p.line}</span>
                    <span style={{ fontSize: 12, color: p.side === "over" ? "var(--green)" : "var(--red)" }}>{(p.side ?? "over").toUpperCase()}</span>
                    <span style={{ fontSize: 13, color: "var(--accent)", fontWeight: 600 }}>{(p.decimal_odds ?? 0).toFixed(2)}</span>
                    <span style={{ fontSize: 11, color: scoreColor(p.value_score) }}>{p.recommendation?.replace(" Value", "")}</span>
                    <span style={{ fontSize: 11, color: "var(--muted)" }}>{p.is_paddy_power ? "🍀 PP" : bookmakerLabel(p.bookmaker)}</span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        addLeg({
                          propId: p.id,
                          playerName: p.player_name,
                          playerId: p.nba_player_id,
                          market: p.market,
                          marketLabel: p.market_label,
                          line: p.line,
                          side: p.side ?? "over",
                          decimalOdds: p.decimal_odds ?? 0,
                          valueScore: p.value_score,
                          bookmaker: p.bookmaker,
                          matchup: p.matchup,
                        });
                      }}
                      disabled={isInSlip(p.id)}
                      style={{
                        padding: "3px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
                        border: isInSlip(p.id) ? "1px solid var(--green)" : "1px solid var(--accent)",
                        background: isInSlip(p.id) ? "transparent" : "transparent",
                        color: isInSlip(p.id) ? "var(--green)" : "var(--accent)",
                        cursor: isInSlip(p.id) ? "default" : "pointer",
                      }}
                    >
                      {isInSlip(p.id) ? "In Slip" : "+ Add"}
                    </button>
                  </div>

                  {/* Expanded factor detail */}
                  {altExpanded === p.id && (
                    <div style={{ padding: "12px 16px", background: "var(--surface)", borderBottom: "1px solid var(--border)" }}>
                      <FactorGrid factors={
                        ([
                          ["Consistency",    p.score_consistency,    0.38],
                          ["vs Opponent",    p.score_vs_opponent,    0.20],
                          ["Home/Away",      p.score_home_away,      0.12],
                          ["Injury Context", p.score_injury,         0.12],
                          ["Team Context",   p.score_team_context,   0.05],
                          ["Season Average", p.score_season_avg,     0.03],
                          ["Blowout Risk",   p.score_blowout_risk,   0.01],
                          ["Volume & Usage", p.score_volume_context, 0.09],
                        ] as [string, number | null, number][])
                          .filter(([, val]) => val != null)
                          .map(([name, score, weight]) => ({ name, score: score!, weight }))
                      } />
                      {p.matchup && <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 8 }}>{p.matchup}</div>}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ─── Shared slip card ─────────────────────────────────────────────────────────

function SlipCard({
  slip, idx, expanded, setExpanded, prefix,
}: {
  slip: Slip;
  idx: number;
  expanded: number | null;
  setExpanded: (v: number | null) => void;
  prefix: string;
}) {
  const cardKey = prefix === "s" ? -(idx + 1) : idx;   // unique key for expand state
  const isExpanded = expanded === cardKey;

  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
      {/* Header */}
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
          <div>
            <span style={{ fontSize: 11, color: "var(--muted)" }}>Odds</span>
            <div style={{ fontSize: 20, fontWeight: 700, color: "var(--accent)" }}>{slip.combined_odds.toFixed(2)}</div>
          </div>
          <div>
            <span style={{ fontSize: 11, color: "var(--muted)" }}>Avg Score</span>
            <div style={{ fontSize: 18, fontWeight: 700 }}>{slip.avg_value_score.toFixed(1)}</div>
          </div>
          <div>
            <span style={{ fontSize: 11, color: "var(--muted)" }}>Legs</span>
            <div style={{ fontSize: 18, fontWeight: 700 }}>{slip.legs.length}</div>
          </div>
          {slip.has_correlated_legs && (
            <span style={{ fontSize: 11, color: "var(--orange)", background: "#2d2a1e", padding: "2px 8px", borderRadius: 4 }}>⚠ correlated</span>
          )}
        </div>
        <button style={btn(isExpanded)} onClick={() => setExpanded(isExpanded ? null : cardKey)}>
          {isExpanded ? "Hide detail" : "View detail"}
        </button>
      </div>

      {/* Legs summary */}
      <div style={{ padding: "12px 16px" }}>
        {slip.legs.map((leg, li) => (
          <div key={li} style={{ display: "flex", alignItems: "center", gap: 14, padding: "6px 0", borderBottom: li < slip.legs.length - 1 ? "1px solid var(--border)" : "none" }}>
            <ScoreBadge score={leg.value_score} />
            <PlayerHeadshot playerId={leg.player_id} size={40} />
            <div style={{ flex: 1 }}>
              <span style={{ fontWeight: 600 }}>{leg.player_name}</span>
              <span style={{ color: "var(--muted)", marginLeft: 8, fontSize: 13 }}>
                {(leg.side ?? "over").toUpperCase()} {leg.line} {leg.market_label}
              </span>
            </div>
            <div style={{ color: "var(--accent)", fontSize: 13 }}>{leg.over_odds.toFixed(2)}</div>
            <div style={{ fontSize: 12, color: "var(--muted)", minWidth: 90, textAlign: "right" }}>
              {leg.is_paddy_power ? "🍀 PP" : bookmakerLabel(leg.bookmaker)}
            </div>
            <div style={{ fontSize: 11, color: "var(--muted)", minWidth: 110, textAlign: "right" }}>{leg.game}</div>
          </div>
        ))}
      </div>

      {/* Expanded factor detail */}
      {isExpanded && (
        <div style={{ borderTop: "1px solid var(--border)", background: "var(--bg)" }}>
          {slip.legs.map((leg, li) => (
            <div key={li} style={{ padding: "16px 20px", borderBottom: li < slip.legs.length - 1 ? "1px solid var(--border)" : "none" }}>
              <div style={{ fontWeight: 600, marginBottom: 10 }}>
                {leg.player_name} — {(leg.side ?? "over").toUpperCase()} {leg.line} {leg.market_label}
                <span style={{ color: "var(--muted)", fontWeight: 400, marginLeft: 8, fontSize: 12 }}>{leg.game}</span>
              </div>
              <FactorGrid factors={leg.factors} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
