"use client";

import { createContext, useContext, useState, useCallback, ReactNode } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SlipLegItem {
  propId: number;         // graded_props.id
  playerName: string;
  playerId: number | null;
  market: string;
  marketLabel: string;
  line: number;
  side: string;
  decimalOdds: number;
  valueScore: number;
  bookmaker: string;
  matchup: string | null;
}

interface SlipBuilderState {
  legs: SlipLegItem[];
  addLeg: (item: SlipLegItem) => void;
  removeLeg: (propId: number) => void;
  clearSlip: () => void;
  isInSlip: (propId: number) => boolean;
  combinedOdds: number;
  avgScore: number;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const SlipBuilderContext = createContext<SlipBuilderState | null>(null);

export function SlipBuilderProvider({ children }: { children: ReactNode }) {
  const [legs, setLegs] = useState<SlipLegItem[]>([]);

  const addLeg = useCallback((item: SlipLegItem) => {
    setLegs((prev) =>
      prev.some((l) => l.propId === item.propId) ? prev : [...prev, item],
    );
  }, []);

  const removeLeg = useCallback((propId: number) => {
    setLegs((prev) => prev.filter((l) => l.propId !== propId));
  }, []);

  const clearSlip = useCallback(() => setLegs([]), []);

  const isInSlip = useCallback(
    (propId: number) => legs.some((l) => l.propId === propId),
    [legs],
  );

  const combinedOdds = legs.reduce((acc, l) => acc * l.decimalOdds, 1.0);
  const avgScore =
    legs.length > 0
      ? legs.reduce((acc, l) => acc + l.valueScore, 0) / legs.length
      : 0;

  return (
    <SlipBuilderContext.Provider
      value={{ legs, addLeg, removeLeg, clearSlip, isInSlip, combinedOdds, avgScore }}
    >
      {children}
    </SlipBuilderContext.Provider>
  );
}

export function useSlipBuilder() {
  const ctx = useContext(SlipBuilderContext);
  if (!ctx) throw new Error("useSlipBuilder must be used inside <SlipBuilderProvider>");
  return ctx;
}
