"""
All rich output formatting. Nothing outside this module prints to the terminal.
Includes live progress indicators and the API credit counter.
"""
from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.text import Text
from rich import box
from rich.rule import Rule

import config
from src.models import ValuedProp, BetSlip, BetLeg
from src.cache import credits_summary, warn_if_low

console = Console()


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _score_colour(score: float) -> str:
    if score >= 80:
        return "bold green"
    if score >= 65:
        return "green"
    if score >= 50:
        return "yellow"
    return "red"


def _rec_colour(rec: str) -> str:
    return {
        "Strong Value": "bold green",
        "Good Value":   "green",
        "Marginal Value": "yellow",
        "Poor Value":   "red",
    }.get(rec, "white")


# ---------------------------------------------------------------------------
# Header / footer
# ---------------------------------------------------------------------------

def print_header() -> None:
    console.print()
    console.print(Panel(
        "[bold cyan]PickAParlay — NBA Bet Builder[/bold cyan]\n"
        "[dim]Powered by nba_api + The Odds API[/dim]",
        box=box.DOUBLE_EDGE,
        expand=False,
    ))
    console.print()


def print_credits() -> None:
    summary = credits_summary()
    warning = warn_if_low()
    console.print(f"[dim]{summary}[/dim]")
    if warning:
        console.print(f"[bold yellow]{warning}[/bold yellow]")
    console.print()


def print_no_games() -> None:
    console.print(Panel(
        "[yellow]No NBA games found for tonight, or all games have already started.[/yellow]",
        title="No Games",
    ))


def print_no_props() -> None:
    console.print(Panel(
        "[yellow]No player props available from The Odds API for tonight's games.\n"
        "Check your ODDS_API_KEY and try again closer to tip-off.[/yellow]",
        title="No Props",
    ))


def print_no_slips(target: float) -> None:
    console.print(Panel(
        f"[yellow]No valid bet slips found within ±{config.ODDS_TOLERANCE:.0%} of "
        f"target odds {target:.2f}.\n"
        "Try a different target (e.g. --odds 3/1) or relax --min-score.[/yellow]",
        title="No Slips Found",
    ))


# ---------------------------------------------------------------------------
# Progress bar (returns the Progress object for use as a context manager)
# ---------------------------------------------------------------------------

def make_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


# ---------------------------------------------------------------------------
# Tonight's games table
# ---------------------------------------------------------------------------

def print_games_table(games: list) -> None:
    table = Table(title="Tonight's Games", box=box.SIMPLE_HEAVY)
    table.add_column("#", style="dim")
    table.add_column("Matchup", style="cyan")
    table.add_column("Time (UTC)")

    for i, game in enumerate(games, 1):
        table.add_row(
            str(i),
            f"{game.away_team} @ {game.home_team}",
            game.game_time_utc[:16] if game.game_time_utc else "TBD",
        )
    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# ValuedProp detailed display
# ---------------------------------------------------------------------------

def print_valued_prop(vp: ValuedProp, rank: int | None = None) -> None:
    market_label = config.MARKET_MAP.get(vp.prop.market, {}).get("label", vp.prop.market)
    bookie_tag = "[PP]" if vp.prop.is_paddy_power else f"[{vp.prop.bookmaker}]"
    score_col = _score_colour(vp.value_score)
    rec_col = _rec_colour(vp.recommendation)

    rank_str = f"#{rank} " if rank else ""
    side_label = vp.backing_data.get("side", "over").upper()
    title = (
        f"{rank_str}[bold]{vp.prop.player_name}[/bold]  "
        f"{side_label} {vp.prop.line} {market_label}  "
        f"[cyan]@{vp.prop.over_odds_decimal:.2f}[/cyan]  {bookie_tag}  "
        f"[{score_col}][{vp.recommendation}: {vp.value_score}/100][/{score_col}]"
    )

    if not vp.prop.is_paddy_power:
        title += "  [dim yellow]⚠ Best available (PP not offering)[/dim yellow]"
    if vp.suspicious_line:
        title += f"\n  [bold yellow]⚠ Suspicious line: {vp.suspicious_reason}[/bold yellow]"

    lines: list[str] = []
    for factor in vp.factors:
        w_pct = f"{factor.weight * 100:.0f}%"
        f_col = _score_colour(factor.score)
        conf_str = f" [low confidence: {factor.confidence:.0%}]" if factor.confidence < 0.7 else ""
        lines.append(
            f"  [dim]{factor.name:20s} ({w_pct})[/dim]  "
            f"[{f_col}]{factor.score:.0f}/100[/{f_col}]{conf_str}"
        )
        for ev in factor.evidence:
            lines.append(f"    [dim]• {ev}[/dim]")

    console.print(Panel("\n".join(lines), title=title, box=box.ROUNDED))


# ---------------------------------------------------------------------------
# Slip display
# ---------------------------------------------------------------------------

def print_slip(slip: BetSlip, rank: int) -> None:
    odds_diff_pct = (slip.combined_decimal_odds - slip.target_decimal_odds) / slip.target_decimal_odds
    odds_diff_str = f"{odds_diff_pct:+.1%} from target"

    score_col = _score_colour(slip.total_value_score)

    title = (
        f"[bold]Slip #{rank}[/bold]  "
        f"Combined odds: [cyan]{slip.combined_decimal_odds:.2f}[/cyan]  "
        f"({_decimal_to_fractional(slip.combined_decimal_odds)})  "
        f"[dim]{odds_diff_str}[/dim]  "
        f"[{score_col}]Avg value: {slip.total_value_score}/100[/{score_col}]"
    )

    if slip.has_correlated_legs:
        title += "  [yellow][CORRELATED — SAME GAME][/yellow]"

    lines: list[str] = []
    for i, leg in enumerate(slip.legs, 1):
        vp = leg.valued_prop
        market_label = config.MARKET_MAP.get(vp.prop.market, {}).get("label", vp.prop.market)
        bookie_tag = "[PP]" if vp.prop.is_paddy_power else f"[{vp.prop.bookmaker}]"
        score_col_leg = _score_colour(vp.value_score)
        rec = vp.recommendation
        suspicious_tag = "  [bold yellow]⚠ CHECK LINE[/bold yellow]" if vp.suspicious_line else ""

        side_label = vp.backing_data.get("side", "over").upper()
        lines.append(
            f"  {i}. [bold]{vp.prop.player_name}[/bold]  "
            f"{side_label} {vp.prop.line} {market_label}  "
            f"[cyan]@{vp.prop.over_odds_decimal:.2f}[/cyan]  {bookie_tag}  "
            f"[{score_col_leg}][{rec}: {vp.value_score}/100][/{score_col_leg}]"
            f"{suspicious_tag}"
        )

        # Show top 2 evidence bullets per leg for a concise summary
        top_evidence = _top_evidence_bullets(vp)
        for bullet in top_evidence:
            lines.append(f"     [dim]• {bullet}[/dim]")

    console.print(Panel("\n".join(lines), title=title, box=box.HEAVY))


def print_slips_header(n_slips: int, target_decimal: float) -> None:
    frac = _decimal_to_fractional(target_decimal)
    console.print(Rule(
        f"[bold]Top {n_slips} Bet Slips — Target: {target_decimal:.2f} ({frac})[/bold]"
    ))
    console.print()


def _top_evidence_bullets(vp: ValuedProp) -> list[str]:
    """Return the most impactful evidence bullets across all factors."""
    bullets: list[str] = []
    # Consistency first (highest weight)
    for f in vp.factors:
        if f.name == "Consistency" and f.evidence:
            bullets.append(f.evidence[0])
            break
    # Injury warning if any
    for f in vp.factors:
        if f.name == "Injury Context":
            for ev in f.evidence:
                if "⚠" in ev or "DOUBTFUL" in ev or "OUT" in ev:
                    bullets.append(ev)
            break
    return bullets[:2]


# ---------------------------------------------------------------------------
# All valued props summary table
# ---------------------------------------------------------------------------

def print_props_table(valued_props: list[ValuedProp]) -> None:
    table = Table(
        title=f"Scored Props ({len(valued_props)} eligible)",
        box=box.SIMPLE,
        show_lines=False,
    )
    table.add_column("Player", style="bold")
    table.add_column("Market")
    table.add_column("Line", justify="right")
    table.add_column("Odds", justify="right", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Rec")
    table.add_column("Game")

    for vp in sorted(valued_props, key=lambda v: v.value_score, reverse=True):
        market_label = config.MARKET_MAP.get(vp.prop.market, {}).get("label", vp.prop.market)
        score_col = _score_colour(vp.value_score)
        flags = ""
        if vp.suspicious_line:
            flags += " ⚠"
        if not vp.prop.is_paddy_power:
            flags += " ✦"

        table.add_row(
            vp.prop.player_name + flags,
            market_label,
            str(vp.prop.line),
            f"{vp.prop.over_odds_decimal:.2f}",
            Text(f"{vp.value_score}/100", style=score_col),
            vp.recommendation,
            f"{vp.prop.game.away_team}@{vp.prop.game.home_team}",
        )

    console.print(table)
    console.print("[dim]⚠ = suspicious line  ✦ = best available (PP not offering)[/dim]")
    console.print()


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _decimal_to_fractional(decimal: float) -> str:
    """Convert decimal odds to a readable fractional string (e.g. 5.0 → 4/1)."""
    if decimal <= 1.0:
        return "N/A"
    profit = decimal - 1.0
    # Find a close fraction
    for denom in range(1, 21):
        numer = round(profit * denom)
        if abs(numer / denom - profit) < 0.02:
            return f"{numer}/{denom}"
    return f"{profit:.1f}/1"
