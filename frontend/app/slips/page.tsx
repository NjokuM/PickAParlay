"use client";

import { useEffect, useState } from "react";
import { api, Slip } from "@/lib/api";
import { FactorGrid } from "@/components/FactorBar";
import { ScoreBadge } from "@/components/Badge";

function bookmakerLabel(b: string) {
  const m: Record<string, string> = { paddypower: "Paddy Power", draftkings: "DraftKings", fanduel: "FanDuel", betmgm: "BetMGM" };
  return m[b] ?? b;
}

export default function SlipsPage() {
  const [odds, setOdds]         = useState("");            // empty = best-value mode
  const [legs, setLegs]         = useState("");
  const [minScore, setMinScore] = useState(50);
  const [bookmaker, setBookmaker] = useState("");
  const [books, setBooks]       = useState<string[]>([]);
  const [slips, setSlips]       = useState<Slip[]>([]);
  const [legFilter, setLegFilter] = useState<"all"|"2"|"3"|"4">("all");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [saved, setSaved]       = useState<Record<number, boolean>>({});

  useEffect(() => { api.bookmakers().then(setBooks).catch(() => {}); }, []);

  const filteredSlips = legFilter === "all"
    ? slips
    : slips.filter(s => s.legs.length === Number(legFilter));

  async function buildSlips() {
    setLoading(true); setError(null); setSlips([]); setExpanded(null); setLegFilter("all");
    try {
      const result = await api.slips({
        odds: odds || undefined,
        legs: legs ? Number(legs) : undefined,
        min_score: minScore,
        bookmaker: bookmaker || undefined,
      });
      setSlips(result);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally { setLoading(false); }
  }

  async function saveSlip(idx: number) {
    try {
      await api.saveSlip({ odds: odds || undefined, slip_index: idx, bookmaker: bookmaker || undefined, min_score: minScore, legs: legs ? Number(legs) : undefined });
      setSaved(s => ({ ...s, [idx]: true }));
    } catch (e: unknown) { alert((e as Error).message); }
  }

  const S: React.CSSProperties = { background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6, padding: "6px 10px", color: "var(--text)", fontSize: 13, outline: "none" };
  const btn = (active?: boolean): React.CSSProperties => ({ padding: "6px 14px", borderRadius: 6, border: "1px solid var(--border)", background: active ? "var(--accent)" : "var(--surface2)", color: active ? "#0d1117" : "var(--text)", cursor: "pointer", fontSize: 13, fontWeight: active ? 600 : 400 });

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ margin: "0 0 4px", fontSize: 20, fontWeight: 700 }}>Build Slips</h1>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>Instant — loads from today&apos;s cached props, no API credits used.</p>
      </div>

      {/* Controls */}
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "16px", marginBottom: 20, display: "flex", flexWrap: "wrap", gap: 12, alignItems: "flex-end" }}>
        <div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>
            Target Odds
            {!odds && <span style={{ marginLeft: 6, color: "var(--accent)", fontWeight: 600 }}>Best Value</span>}
          </div>
          <input style={{ ...S, width: 110 }} value={odds} onChange={e => setOdds(e.target.value)}
            placeholder="Any (Best Value)" onKeyDown={e => e.key === "Enter" && buildSlips()} />
          <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 3 }}>e.g. 4/1 · 5.0 · +400</div>
        </div>

        <div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Legs (optional)</div>
          <select style={{ ...S, width: 100 }} value={legs} onChange={e => setLegs(e.target.value)}>
            <option value="">Auto</option>
            {[2,3,4,5,6].map(n => <option key={n} value={n}>{n} legs</option>)}
          </select>
        </div>

        <div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Sportsbook</div>
          <select style={{ ...S, minWidth: 120 }} value={bookmaker} onChange={e => setBookmaker(e.target.value)}>
            <option value="">All Books</option>
            {books.map(b => <option key={b} value={b}>{bookmakerLabel(b)}</option>)}
          </select>
        </div>

        <div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Min Score: <strong style={{ color: "var(--text)" }}>{minScore}</strong></div>
          <input type="range" min={40} max={90} step={5} value={minScore} onChange={e => setMinScore(Number(e.target.value))} style={{ width: 120, accentColor: "var(--accent)" }} />
        </div>

        <button style={{ ...btn(true), padding: "8px 20px" }} onClick={buildSlips} disabled={loading}>
          {loading ? "Building…" : "Build Slips"}
        </button>
      </div>

      {error && (
        <div style={{ padding: "10px 14px", borderRadius: 6, background: "#2d1e1e", border: "1px solid var(--red)", color: "var(--red)", marginBottom: 16, fontSize: 13 }}>
          {error.includes("cached") ? "No cached props — go to Tonight and click ↻ Refresh first." : error}
        </div>
      )}

      {!loading && slips.length === 0 && !error && (
        <div style={{ color: "var(--muted)", padding: "40px 0", textAlign: "center" }}>
          Click <strong style={{ color: "var(--text)" }}>Build Slips</strong> — leave odds blank for best-value combos.
        </div>
      )}

      {/* Leg-count filter toggle — only shown when results exist */}
      {slips.length > 0 && (
        <div style={{ display: "flex", gap: 6, marginBottom: 16, alignItems: "center" }}>
          <span style={{ fontSize: 12, color: "var(--muted)", marginRight: 4 }}>Filter:</span>
          {(["all", "2", "3", "4"] as const).map(f => (
            <button
              key={f}
              style={btn(legFilter === f)}
              onClick={() => setLegFilter(f)}
            >
              {f === "all" ? "All" : `${f}-Leg`}
            </button>
          ))}
          <span style={{ fontSize: 12, color: "var(--muted)", marginLeft: 8 }}>
            {filteredSlips.length} slip{filteredSlips.length !== 1 ? "s" : ""}
          </span>
        </div>
      )}

      {/* Slip cards — preserve original index for save/expand operations */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {slips
          .map((slip, originalIdx) => ({ slip, originalIdx }))
          .filter(({ slip }) => legFilter === "all" || slip.legs.length === Number(legFilter))
          .map(({ slip, originalIdx: idx }) => (
          <div key={idx} style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
            {/* Slip header */}
            <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
              <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                <div>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>Combined Odds</span>
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
              <div style={{ display: "flex", gap: 8 }}>
                <button style={btn(expanded === idx)} onClick={() => setExpanded(expanded === idx ? null : idx)}>
                  {expanded === idx ? "Hide detail" : "View detail"}
                </button>
                <button
                  style={{ ...btn(false), color: saved[idx] ? "var(--green)" : "var(--text)", borderColor: saved[idx] ? "var(--green)" : "var(--border)" }}
                  onClick={() => saveSlip(idx)}
                  disabled={saved[idx]}
                >
                  {saved[idx] ? "✓ Saved" : "Save Slip"}
                </button>
              </div>
            </div>

            {/* Legs summary */}
            <div style={{ padding: "12px 16px" }}>
              {slip.legs.map((leg, li) => (
                <div key={li} style={{ display: "flex", alignItems: "center", gap: 12, padding: "6px 0", borderBottom: li < slip.legs.length - 1 ? "1px solid var(--border)" : "none" }}>
                  <ScoreBadge score={leg.value_score} />
                  <div style={{ flex: 1 }}>
                    <span style={{ fontWeight: 600 }}>{leg.player_name}</span>
                    <span style={{ color: "var(--muted)", marginLeft: 8, fontSize: 13 }}>{(leg.side ?? "over").toUpperCase()} {leg.line} {leg.market_label}</span>
                  </div>
                  <div style={{ color: "var(--accent)", fontSize: 13 }}>{leg.over_odds.toFixed(2)}</div>
                  <div style={{ fontSize: 12, color: "var(--muted)", minWidth: 90, textAlign: "right" }}>{leg.is_paddy_power ? "🍀 PP" : leg.bookmaker}</div>
                  <div style={{ fontSize: 11, color: "var(--muted)", minWidth: 110, textAlign: "right" }}>{leg.game}</div>
                </div>
              ))}
            </div>

            {/* Expanded detail */}
            {expanded === idx && (
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
        ))}
      </div>
    </div>
  );
}
