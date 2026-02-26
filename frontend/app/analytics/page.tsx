"use client";

import { useEffect, useState } from "react";
import { api, Analytics } from "@/lib/api";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, ReferenceLine, CartesianGrid, Legend,
} from "recharts";

export default function AnalyticsPage() {
  const [data, setData]       = useState<Analytics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { api.analytics().then(setData).catch(() => {}).finally(() => setLoading(false)); }, []);

  const cardStyle: React.CSSProperties = { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "20px" };

  if (loading) return <div style={{ color: "var(--muted)", padding: "60px 0", textAlign: "center" }}>Loading…</div>;
  if (!data) return null;

  const { overall, by_market, calibration } = data;
  const noData = overall.total_slips === 0;

  const calData = calibration.map(r => ({
    bucket: `${r.bucket}–${r.bucket + 9}`,
    actual_pct: r.total > 0 ? Math.round((r.hits / r.total) * 100) : 0,
    ideal: (r.bucket + 5),   // midpoint of bucket = "perfect calibration"
    sample: r.total,
  }));

  const marketData = by_market.map(r => ({
    name: r.market_label,
    hit_pct: r.total > 0 ? Math.round((r.hits / r.total) * 100) : 0,
    total: r.total,
    hits: r.hits,
  }));

  const pnl = overall.total_pnl;
  const pnlColor = pnl >= 0 ? "var(--green)" : "var(--red)";

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: "0 0 4px", fontSize: 20, fontWeight: 700 }}>Analytics</h1>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>
          Factor calibration and accuracy from all recorded outcomes.
          {noData && " Record at least one outcome in History to see data."}
        </p>
      </div>

      {/* KPI row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 24 }}>
        {[
          { label: "Slips Recorded", value: overall.total_slips, color: "var(--text)" },
          { label: "Win Rate", value: overall.total_slips > 0 ? `${(overall.win_rate * 100).toFixed(1)}%` : "—", color: overall.win_rate >= 0.5 ? "var(--green)" : "var(--red)" },
          { label: "Wins / Losses", value: `${overall.wins} / ${overall.total_slips - overall.wins}`, color: "var(--text)" },
          { label: "Total P&L", value: overall.total_slips > 0 ? `${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}` : "—", color: pnlColor },
        ].map(({ label, value, color }) => (
          <div key={label} style={cardStyle}>
            <div style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>{label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color }}>{value}</div>
          </div>
        ))}
      </div>

      {noData ? (
        <div style={{ ...cardStyle, padding: "60px 20px", textAlign: "center", color: "var(--muted)" }}>
          No recorded outcomes yet. Save slips and mark their results in History.
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {/* Hit rate by market */}
          {marketData.length > 0 && (
            <div style={cardStyle}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 16 }}>Leg Hit Rate by Market</div>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={marketData} layout="vertical" margin={{ left: 10, right: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis type="number" domain={[0, 100]} tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={v => `${v}%`} />
                  <YAxis type="category" dataKey="name" tick={{ fill: "var(--muted)", fontSize: 11 }} width={90} />
                  <Tooltip
                    contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6 }}
                    formatter={(v, _, p) => [`${v}% (${p.payload.hits}/${p.payload.total})`, "Hit Rate"]}
                  />
                  <ReferenceLine x={50} stroke="var(--muted)" strokeDasharray="4 4" />
                  <Bar dataKey="hit_pct" fill="var(--accent)" radius={[0, 3, 3, 0]} name="Hit %" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Calibration chart */}
          {calData.length > 0 && (
            <div style={cardStyle}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Consistency Score Calibration</div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12 }}>
                If the model is well-calibrated, Actual should follow Ideal.
              </div>
              <ResponsiveContainer width="100%" height={250}>
                <LineChart data={calData} margin={{ left: 0, right: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="bucket" tick={{ fill: "var(--muted)", fontSize: 11 }} />
                  <YAxis domain={[0, 100]} tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={v => `${v}%`} />
                  <Tooltip
                    contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 6 }}
                    formatter={(v) => [`${v}%`]}
                  />
                  <Legend wrapperStyle={{ fontSize: 11, color: "var(--muted)" }} />
                  <Line type="monotone" dataKey="actual_pct" stroke="var(--accent)" strokeWidth={2} dot={{ fill: "var(--accent)" }} name="Actual Hit %" />
                  <Line type="monotone" dataKey="ideal" stroke="var(--border)" strokeWidth={1} strokeDasharray="4 4" dot={false} name="Perfect Calibration" />
                </LineChart>
              </ResponsiveContainer>
              <div style={{ marginTop: 12 }}>
                {calData.map(r => (
                  <div key={r.bucket} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--muted)", marginBottom: 2 }}>
                    <span>Score {r.bucket}</span>
                    <span>{r.actual_pct}% actual hit rate (n={r.sample})</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
