"use client";

import { createContext, useContext, useState, useEffect, ReactNode } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

export type OddsFormat = "decimal" | "fractional" | "american";

interface OddsFormatContextValue {
  format: OddsFormat;
  setFormat: (f: OddsFormat) => void;
}

// ─── Context ──────────────────────────────────────────────────────────────────

const OddsFormatContext = createContext<OddsFormatContextValue>({
  format: "decimal",
  setFormat: () => {},
});

export function OddsFormatProvider({ children }: { children: ReactNode }) {
  const [format, setFormatState] = useState<OddsFormat>("decimal");

  // Hydrate from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem("odds_format") as OddsFormat | null;
    if (saved && ["decimal", "fractional", "american"].includes(saved)) {
      setFormatState(saved);
    }
  }, []);

  const setFormat = (f: OddsFormat) => {
    setFormatState(f);
    localStorage.setItem("odds_format", f);
  };

  return (
    <OddsFormatContext.Provider value={{ format, setFormat }}>
      {children}
    </OddsFormatContext.Provider>
  );
}

export function useOddsFormat() {
  return useContext(OddsFormatContext);
}

// ─── Conversion helpers ───────────────────────────────────────────────────────

function gcd(a: number, b: number): number {
  return b === 0 ? a : gcd(b, a % b);
}

function decimalToFractional(decimal: number): string {
  const f = decimal - 1;
  if (f <= 0) return "0/1";
  // Try clean fractions with small denominators first (e.g. 10/11, 1/2, 3/4)
  for (let den = 1; den <= 20; den++) {
    const num = Math.round(f * den);
    if (num > 0 && Math.abs(num / den - f) < 0.005) {
      const g = gcd(num, den);
      return `${num / g}/${den / g}`;
    }
  }
  // Fall back to /100 precision
  const num = Math.round(f * 100);
  const g = gcd(num, 100);
  return `${num / g}/${100 / g}`;
}

function decimalToAmerican(decimal: number): string {
  if (decimal >= 2.0) {
    return `+${Math.round((decimal - 1) * 100)}`;
  }
  return `${Math.round(-100 / (decimal - 1))}`;
}

// ─── Main format function — use this everywhere odds are displayed ─────────────

export function formatOdds(
  decimal: number | null | undefined,
  format: OddsFormat,
): string {
  if (decimal == null || decimal <= 0) return "—";
  switch (format) {
    case "decimal":    return decimal.toFixed(2);
    case "fractional": return decimalToFractional(decimal);
    case "american":   return decimalToAmerican(decimal);
  }
}

// ─── Selector component — drop in anywhere ────────────────────────────────────

const FORMAT_OPTIONS: { value: OddsFormat; label: string }[] = [
  { value: "decimal",    label: "Dec"  },
  { value: "fractional", label: "Frac" },
  { value: "american",   label: "Amer" },
];

export function OddsFormatSelector({ compact = false }: { compact?: boolean }) {
  const { format, setFormat } = useOddsFormat();

  return (
    <div>
      {!compact && (
        <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
          Odds Format
        </div>
      )}
      <div style={{ display: "flex", gap: 4 }}>
        {FORMAT_OPTIONS.map(opt => (
          <button
            key={opt.value}
            onClick={() => setFormat(opt.value)}
            style={{
              padding: compact ? "3px 8px" : "4px 10px",
              borderRadius: 4,
              border: "1px solid var(--border)",
              background: format === opt.value ? "var(--accent)" : "var(--surface2)",
              color: format === opt.value ? "#0d1117" : "var(--muted)",
              cursor: "pointer",
              fontSize: compact ? 10 : 11,
              fontWeight: format === opt.value ? 700 : 400,
            }}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}
