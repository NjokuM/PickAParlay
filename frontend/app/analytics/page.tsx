"use client";

import { useEffect, useState } from "react";
import { api, Analytics } from "@/lib/api";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, ReferenceLine, CartesianGrid, Legend,
} from "recharts";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function pct(hits: number, total: number) {
  return total ? Math.round((hits / total) * 100) : 0;
}

function pctColor(p: number) {
  return p >= 60 ? "var(--green)" : p >= 48 ? "var(--accent)" : "var(--red)";
}

const CARD: React.CSSProperties = {
  background: "var(--surface)", border: "1px solid var(--border)",
  borderRadius: 8, padding: 20,
};

const FACTOR_ORDER = [
  "Consistency", "vs Opponent", "Home/Away", "Injury",
  "Team Context", "Season Avg", "Blowout Risk", "Volume & Usage",
];

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const [data, setData]       = useState<Analytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeFactor, setActiveFactor] = useState("Consistency");

  useEffect(() => {
    api.analytics().then(setData).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) return <div style={{ color: "var(--muted)", padding: "60px 0", textAlign: "center" }}>Loading…</div>;
  if (!data) return null;

  const { picks, slips, value_calibration, factor_calibration, by_market, by_side, daily_trend } = data;
  const noData = picks.total === 0;

  // ── Derived chart data ────────────────────────────────────────────────

  const valCalData = value_calibration.map(r => ({
    bucket: `${r.bucket}–${r.bucket + 4}`,
    bucket_mid: r.bucket + 2.5,
    actual_pct: pct(r.hits, r.total),
    sample: r.total,
    hits: r.hits,
  }));

  const activeFactorData = (factor_calibration[activeFactor] ?? []).map(r => ({
    bucket: `${r.bucket}–${r.bucket + 9}`,
    actual_pct: pct(r.hits, r.total),
    ideal: Math.min(100, r.bucket + 5),
    sample: r.total,
    hits: r.hits,
  }));

  const marketData = by_market.map(r => ({
    name: r.market_label,
    hit_pct: pct(r.hits, r.total),
    total: r.total,
    hits: r.hits,
  }));

  const overRow  = by_side.find(r => r.side === "over");
  const underRow = by_side.find(r => r.side === "under");

  const trendData = daily_trend.map(r => ({
    date: r.game_date.slice(5),   // "MM-DD"
    hit_pct: pct(r.hits, r.total),
    total: r.total,
    hits: r.hits,
  }));

  // ── Factor summary: overall hit rate per factor's high-score bracket ──
  const factorSummary = FACTOR_ORDER.map(name => {
    const buckets = factor_calibration[name] ?? [];
    const highBuckets = buckets.filter(b => b.bucket >= 60);
    const totalHigh = highBuckets.reduce((s, b) => s + b.total, 0);
    const hitsHigh  = highBuckets.reduce((s, b) => s + b.hits, 0);
    const allTotal  = buckets.reduce((s, b) => s + b.total, 0);
    const allHits   = buckets.reduce((s, b) => s + b.hits, 0);
    return {
      name,
      overall_pct: pct(allHits, allTotal),
      overall_n:   allTotal,
      high_pct:    pct(hitsHigh, totalHigh),
      high_n:      totalHigh,
    };
  });

  // ── Pill style helper ────────────────────────────────────────────────
  const pill = (active: boolean): React.CSSProperties => ({
    padding: "4px 12px", borderRadius: 4, border: "1px solid var(--border)",
    background: active ? "var(--accent)" : "var(--surface2)",
    color: active ? "#0d1117" : "var(--muted)",
    cursor: "pointer", fontSize: 12, fontWeight: active ? 600 : 400,
  });

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: "0 0 4px", fontSize: 20, fontWeight: 700 }}>📈 Analytics</h1>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>
          Model accuracy from all graded picks (is_best_side = 1).
          {noData && " Run a refresh then check results to see data here."}
        </p>
      </div>

      {/* ── KPI Row ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12, marginBottom: 24 }}>
        {[
          { label: "Total Picks", value: picks.total, color: "var(--text)" },
          { label: "Pick Hit Rate",
            value: picks.total > 0 ? `${(picks.hit_rate * 100).toFixed(1)}%` : "—",
            color: picks.hit_rate >= 0.55 ? "var(--green)" : picks.hit_rate >= 0.48 ? "var(--accent)" : "var(--red)" },
          { label: "Hits / Misses", value: `${picks.hits} / ${picks.misses}`, color: "var(--text)" },
          { label: "OVER Hit Rate",
            value: overRow ? `${pct(overRow.hits, overRow.total)}%` : "—",
            sub: overRow ? `(n=${overRow.total})` : "",
            color: overRow && pct(overRow.hits, overRow.total) >= 55 ? "var(--green)" : "var(--accent)" },
          { label: "UNDER Hit Rate",
            value: underRow ? `${pct(underRow.hits, underRow.total)}%` : "—",
            sub: underRow ? `(n=${underRow.total})` : "",
            color: underRow && pct(underRow.hits, underRow.total) >= 55 ? "var(--green)" : "var(--accent)" },
        ].map(({ label, value, color, sub }) => (
          <div key={label} style={CARD}>
            <div style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>{label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color }}>{value}</div>
            {sub && <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>{sub}</div>}
          </div>
        ))}
      </div>

      {noData ? (
        <div style={{ ...CARD, padding: "60px 20px", textAlign: "center", color: "var(--muted)" }}>
          No graded picks yet. Refresh props → let games finish → check results.
        </div>
      ) : (
        <>
          {/* ── Row 1: Value Score Calibration + Daily Trend ── */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            {/* Value Score Calibration */}
            <div style={CARD}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Value Score Calibration</div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12 }}>
                Hit rate by value score bucket — does a higher score mean more hits?
              </div>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={valCalData} margin={{ left: 0, right: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="bucket" tick={{ fill: "var(--muted)", fontSize: 10 }} />
                  <YAxis domain={[0, 100]} tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={v => `${v}%`} />
                  <Tooltip
                    contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6 }}
                    formatter={(v, _, p) => [
                      `${v}% (${(p.payload as Record<string, number>).hits}/${(p.payload as Record<string, number>).sample})`, "Hit Rate"
                    ]}
                  />
                  <ReferenceLine y={50} stroke="var(--muted)" strokeDasharray="4 4" label={{ value: "50%", fill: "var(--muted)", fontSize: 10 }} />
                  <Bar dataKey="actual_pct" fill="var(--accent)" radius={[3, 3, 0, 0]} name="Hit %" />
                </BarChart>
              </ResponsiveContainer>
              {/* Sample size table */}
              <div style={{ marginTop: 8 }}>
                {valCalData.map(r => (
                  <div key={r.bucket} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--muted)", marginBottom: 2 }}>
                    <span>Score {r.bucket}</span>
                    <span style={{ color: pctColor(r.actual_pct) }}>
                      {r.actual_pct}% hit rate <span style={{ color: "var(--muted)" }}>(n={r.sample})</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Daily Trend */}
            <div style={CARD}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Daily Hit Rate Trend</div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12 }}>
                How picks are performing day-over-day.
              </div>
              {trendData.length > 1 ? (
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={trendData} margin={{ left: 0, right: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis dataKey="date" tick={{ fill: "var(--muted)", fontSize: 10 }} />
                    <YAxis domain={[0, 100]} tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={v => `${v}%`} />
                    <Tooltip
                      contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6 }}
                      formatter={(v, _, p) => [
                        `${v}% (${(p.payload as Record<string, number>).hits}/${(p.payload as Record<string, number>).total})`, "Hit Rate"
                      ]}
                    />
                    <ReferenceLine y={50} stroke="var(--muted)" strokeDasharray="4 4" />
                    <Line type="monotone" dataKey="hit_pct" stroke="var(--accent)" strokeWidth={2} dot={{ fill: "var(--accent)", r: 4 }} name="Hit %" />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8, paddingTop: 20 }}>
                  {trendData.map(r => (
                    <div key={r.date} style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                      <span>{r.date}</span>
                      <span style={{ color: pctColor(r.hit_pct), fontWeight: 600 }}>
                        {r.hit_pct}% ({r.hits}/{r.total})
                      </span>
                    </div>
                  ))}
                  <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 8 }}>
                    Line chart will appear after 2+ days of data.
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* ── Row 2: Hit rate by Market + Factor Summary Table ── */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            {/* Market breakdown */}
            {marketData.length > 0 && (
              <div style={CARD}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 16 }}>Hit Rate by Market</div>
                <ResponsiveContainer width="100%" height={Math.max(200, marketData.length * 30)}>
                  <BarChart data={marketData} layout="vertical" margin={{ left: 10, right: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis type="number" domain={[0, 100]} tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={v => `${v}%`} />
                    <YAxis type="category" dataKey="name" tick={{ fill: "var(--muted)", fontSize: 11 }} width={100} />
                    <Tooltip
                      contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6 }}
                      formatter={(v, _, p) => [
                        `${v}% (${(p.payload as Record<string, number>).hits}/${(p.payload as Record<string, number>).total})`, "Hit Rate"
                      ]}
                    />
                    <ReferenceLine x={50} stroke="var(--muted)" strokeDasharray="4 4" />
                    <Bar dataKey="hit_pct" fill="var(--accent)" radius={[0, 3, 3, 0]} name="Hit %" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Factor Summary Table */}
            <div style={CARD}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Factor Performance Summary</div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12 }}>
                Overall hit rate vs. high-score (60+) hit rate per factor.
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 90px 90px", gap: 0, fontSize: 11, color: "var(--muted)", padding: "6px 0", borderBottom: "1px solid var(--border)", fontWeight: 600 }}>
                <span>Factor</span>
                <span>Overall</span>
                <span>Score 60+</span>
              </div>
              {factorSummary.map(f => (
                <div
                  key={f.name}
                  style={{
                    display: "grid", gridTemplateColumns: "1fr 90px 90px", gap: 0,
                    fontSize: 12, padding: "6px 0", borderBottom: "1px solid var(--border)",
                    cursor: "pointer",
                    background: activeFactor === f.name ? "var(--surface2)" : "transparent",
                  }}
                  onClick={() => setActiveFactor(f.name)}
                >
                  <span style={{ fontWeight: activeFactor === f.name ? 600 : 400 }}>{f.name}</span>
                  <span style={{ color: pctColor(f.overall_pct) }}>
                    {f.overall_pct}% <span style={{ color: "var(--muted)" }}>({f.overall_n})</span>
                  </span>
                  <span style={{ color: pctColor(f.high_pct) }}>
                    {f.high_n > 0 ? `${f.high_pct}%` : "—"} <span style={{ color: "var(--muted)" }}>({f.high_n})</span>
                  </span>
                </div>
              ))}
              <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 8 }}>
                Click a factor to see its calibration chart below.
              </div>
            </div>
          </div>

          {/* ── Row 3: Factor Calibration Chart ── */}
          <div style={CARD}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
              <div style={{ fontSize: 14, fontWeight: 600 }}>Factor Calibration: {activeFactor}</div>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                {FACTOR_ORDER.map(f => (
                  <button key={f} style={pill(activeFactor === f)} onClick={() => setActiveFactor(f)}>
                    {f}
                  </button>
                ))}
              </div>
            </div>
            <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12 }}>
              If the factor is well-calibrated, actual hit rate (orange) should follow the ideal line (grey).
              Divergence means the factor score doesn&apos;t predict hit rate at that level.
            </div>
            {activeFactorData.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={250}>
                  <LineChart data={activeFactorData} margin={{ left: 0, right: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis dataKey="bucket" tick={{ fill: "var(--muted)", fontSize: 10 }} />
                    <YAxis domain={[0, 100]} tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={v => `${v}%`} />
                    <Tooltip
                      contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6 }}
                      formatter={(v) => [`${v}%`]}
                    />
                    <Legend wrapperStyle={{ fontSize: 11, color: "var(--muted)" }} />
                    <Line type="monotone" dataKey="actual_pct" stroke="var(--accent)" strokeWidth={2} dot={{ fill: "var(--accent)", r: 4 }} name="Actual Hit %" />
                    <Line type="monotone" dataKey="ideal" stroke="var(--border)" strokeWidth={1} strokeDasharray="4 4" dot={false} name="Perfect Calibration" />
                  </LineChart>
                </ResponsiveContainer>
                <div style={{ marginTop: 8, display: "grid", gridTemplateColumns: "1fr 1fr", gap: "2px 24px" }}>
                  {activeFactorData.map(r => (
                    <div key={r.bucket} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--muted)" }}>
                      <span>{r.bucket}</span>
                      <span style={{ color: pctColor(r.actual_pct) }}>
                        {r.actual_pct}% <span style={{ color: "var(--muted)" }}>(n={r.sample})</span>
                      </span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div style={{ color: "var(--muted)", padding: 20, textAlign: "center", fontSize: 13 }}>
                No data for {activeFactor} — check results first.
              </div>
            )}
          </div>

          {/* ── Slip Stats (secondary) ── */}
          {slips.total_slips > 0 && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--muted)", marginBottom: 8 }}>Bet Slip Stats</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
                <div style={CARD}>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Slips Recorded</div>
                  <div style={{ fontSize: 20, fontWeight: 700 }}>{slips.total_slips}</div>
                </div>
                <div style={CARD}>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Slip Win Rate</div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: slips.win_rate >= 0.5 ? "var(--green)" : "var(--red)" }}>
                    {(slips.win_rate * 100).toFixed(1)}%
                  </div>
                </div>
                <div style={CARD}>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Total P&L</div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: slips.total_pnl >= 0 ? "var(--green)" : "var(--red)" }}>
                    {slips.total_pnl >= 0 ? "+" : ""}{slips.total_pnl.toFixed(2)}
                  </div>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
