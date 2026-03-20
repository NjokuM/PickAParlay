/** Human-readable bookmaker names */
const BOOKMAKER_LABELS: Record<string, string> = {
  bet365: "Bet365",
  paddypower: "Paddy Power",
  draftkings: "DraftKings",
  fanduel: "FanDuel",
  betmgm: "BetMGM",
  bovada: "Bovada",
  betonlineag: "BetOnline",
  pinnacle: "Pinnacle",
  betrivers: "BetRivers",
  neds: "Neds",
  ladbrokes_au: "Ladbrokes AU",
  sportsbet: "Sportsbet",
  pointsbetau: "PointsBet AU",
  unibet: "Unibet",
};

export function bookmakerLabel(b: string): string {
  return BOOKMAKER_LABELS[b] ?? b;
}
