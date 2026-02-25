"""
PickAParlay — NBA Bet Builder
Entry point. Wires all modules together.

Usage:
  python main.py --odds 4/1
  python main.py --odds 5.0 --legs 4
  python main.py --odds "+400" --min-score 70
  python main.py --odds 4/1 --legs 3 --verbose
"""
from __future__ import annotations

import re
import sys
import click

# Ensure src is importable
import os
sys.path.insert(0, os.path.dirname(__file__))

import config
from src import display
from src.api import nba_stats, injury_api, odds_api
from src.analysis import prop_grader, bet_builder
from src.models import NBAGame, PlayerProp


# ---------------------------------------------------------------------------
# Odds parser
# ---------------------------------------------------------------------------

def parse_odds(odds_str: str) -> float:
    """
    Accept multiple formats and return decimal odds:
      "4/1"   → 5.0
      "5.0"   → 5.0
      "+400"  → 5.0
      "-110"  → 1.909
    """
    odds_str = odds_str.strip()

    # Fractional: "4/1"
    if "/" in odds_str:
        parts = odds_str.split("/")
        try:
            return round(int(parts[0]) / int(parts[1]) + 1, 4)
        except (ValueError, ZeroDivisionError):
            raise click.BadParameter(f"Invalid fractional odds: {odds_str}")

    # American: "+400" or "-110"
    if odds_str.startswith("+") or (odds_str.startswith("-") and not odds_str[1:].replace(".", "").isdigit() is False):
        try:
            american = float(odds_str)
            if american > 0:
                return round(american / 100 + 1, 4)
            else:
                return round(100 / abs(american) + 1, 4)
        except ValueError:
            pass

    # Decimal
    try:
        val = float(odds_str)
        if val <= 1.0:
            raise click.BadParameter(f"Decimal odds must be > 1.0, got {val}")
        return round(val, 4)
    except ValueError:
        raise click.BadParameter(f"Cannot parse odds: {odds_str}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.option(
    "--odds", "-o",
    required=True,
    help='Target odds. Accepts fractional ("4/1"), decimal ("5.0"), or American ("+400").',
)
@click.option(
    "--legs", "-l",
    type=int,
    default=None,
    help="Exact number of legs. Omit to let the system auto-determine.",
)
@click.option(
    "--min-score", "-m",
    type=float,
    default=None,
    help=f"Minimum value score for props (default: {config.MIN_VALUE_SCORE}). Use 70+ for Strong/Good only.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Show full factor breakdown for every eligible prop.",
)
@click.option(
    "--season",
    default="2024-25",
    show_default=True,
    help="NBA season string.",
)
def main(
    odds: str,
    legs: int | None,
    min_score: float | None,
    verbose: bool,
    season: str,
) -> None:
    display.print_header()
    display.print_credits()

    # Parse target odds
    try:
        target_decimal = parse_odds(odds)
    except click.BadParameter as e:
        display.console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    display.console.print(
        f"Target odds: [cyan]{target_decimal:.3f}[/cyan]  "
        f"({odds})  "
        f"Legs: {'auto' if legs is None else legs}  "
        f"Min score: {min_score or config.MIN_VALUE_SCORE}\n"
    )

    with display.make_progress() as progress:

        # Step 1: Tonight's games
        task = progress.add_task("Fetching tonight's games...", total=None)
        games = nba_stats.get_todays_games()
        progress.update(task, completed=True, description="Tonight's games loaded ✓")

    if not games:
        display.print_no_games()
        sys.exit(0)

    display.print_games_table(games)

    with display.make_progress() as progress:

        # Step 2: Injury report
        task = progress.add_task("Loading injury report...", total=None)
        injuries = injury_api.get_injury_report()
        progress.update(task, completed=True, description=f"Injuries loaded ({len(injuries)} reports) ✓")

        # Step 3: Fetch odds API events and match to games
        task = progress.add_task("Fetching Odds API events...", total=None)
        events = odds_api.get_events()
        for game in games:
            event_id = odds_api.match_game_to_event(game, events)
            if event_id:
                game.odds_event_id = event_id
        progress.update(task, completed=True, description="Events matched ✓")

        # Step 4: Fetch all player props
        task = progress.add_task("Fetching player props...", total=len(games))
        all_raw_props: list[dict] = []
        for game in games:
            if game.odds_event_id:
                raw = odds_api.get_player_props_for_event(game.odds_event_id)
                # Resolve player IDs
                player_id_map: dict[str, int] = {}
                for rp in raw:
                    name = rp["player_name"]
                    if name not in player_id_map:
                        pid = nba_stats.get_player_id(name)
                        if pid:
                            player_id_map[name] = pid

                props = odds_api.build_player_props(raw, game, player_id_map)
                all_raw_props.extend(props)
            progress.advance(task)
        progress.update(task, description=f"Props loaded ({len(all_raw_props)} candidates) ✓")

    if not all_raw_props:
        display.print_no_props()
        sys.exit(0)

    # Step 5: Grade all props
    display.console.print(f"\nAnalysing [bold]{len(all_raw_props)}[/bold] props across {len(games)} game(s)...\n")

    valued_props = []
    below_threshold: list[tuple] = []   # (prop_name, market, score) for diagnostics
    skipped_no_data: int = 0
    skipped_injured: int = 0
    errors: list[str] = []

    with display.make_progress() as progress:
        task = progress.add_task("Grading props...", total=len(all_raw_props))
        for i, prop in enumerate(all_raw_props, 1):
            market_label = config.MARKET_MAP.get(prop.market, {}).get("label", prop.market)
            progress.update(
                task,
                description=f"[{i}/{len(all_raw_props)}] {prop.player_name} — {market_label}",
            )
            try:
                vp = prop_grader.grade_prop(prop, injuries, season=season)
                if vp is None:
                    skipped_no_data += 1
                elif vp.value_score >= (min_score or config.MIN_VALUE_SCORE):
                    valued_props.append(vp)
                else:
                    below_threshold.append((
                        prop.player_name,
                        market_label,
                        vp.value_score,
                        vp.recommendation,
                    ))
            except Exception as e:
                errors.append(f"{prop.player_name} / {prop.market}: {type(e).__name__}: {e}")
            progress.advance(task)
        progress.update(task, description=f"Grading complete — {len(valued_props)} eligible props ✓")

    # Always print a grading summary so the user knows what happened
    threshold = min_score or config.MIN_VALUE_SCORE
    display.console.print(
        f"\n[dim]Grading summary:[/dim] "
        f"[green]{len(valued_props)} above threshold ({threshold})[/green]  |  "
        f"[yellow]{len(below_threshold)} scored below threshold[/yellow]  |  "
        f"[dim]{skipped_no_data} skipped (no data/injured)[/dim]  |  "
        f"[red]{len(errors)} errors[/red]\n"
    )

    if errors and verbose:
        display.console.print("[bold red]Errors during grading:[/bold red]")
        for err in errors[:10]:
            display.console.print(f"  [red]• {err}[/red]")
        if len(errors) > 10:
            display.console.print(f"  [red]... and {len(errors) - 10} more[/red]")
        display.console.print()

    if not valued_props:
        # Show diagnostic: what DID score, even if below threshold
        if below_threshold:
            below_threshold.sort(key=lambda x: x[2], reverse=True)
            display.console.print(
                f"[yellow]No props met the minimum value score of {threshold}. "
                f"Top {min(10, len(below_threshold))} props that scored below threshold:[/yellow]\n"
            )
            for name, market, score, rec in below_threshold[:10]:
                score_colour = "yellow" if score >= 40 else "red"
                display.console.print(
                    f"  [{score_colour}]{score:.1f}/100[/{score_colour}]  "
                    f"[bold]{name}[/bold]  {market}  [dim]({rec})[/dim]"
                )
            display.console.print(
                f"\n[dim]Tip: run with --min-score {max(10, int(below_threshold[0][2]) - 5)} "
                f"to include the top-scoring props, or --verbose to see full factor breakdowns.[/dim]"
            )
        else:
            display.console.print(
                "[yellow]No props were scored at all. "
                "This usually means player IDs couldn't be resolved or game logs are empty. "
                "Run with --verbose for more detail.[/yellow]"
            )
        sys.exit(0)

    # Step 6: Show all eligible props (brief table)
    display.print_props_table(valued_props)

    # Verbose: full factor breakdown for eligible props + top below-threshold props
    if verbose:
        display.console.print()
        display.console.rule("[bold]Full Factor Breakdowns — Eligible Props[/bold]")
        for i, vp in enumerate(
            sorted(valued_props, key=lambda v: v.value_score, reverse=True), 1
        ):
            display.print_valued_prop(vp, rank=i)

    # Step 7: Build bet slips
    display.console.print("\nBuilding bet combinations...\n")
    slips = bet_builder.build_slips(
        valued_props,
        target_decimal=target_decimal,
        n_legs=legs,
        min_score=min_score,
    )

    if not slips:
        display.print_no_slips(target_decimal)
        sys.exit(0)

    # Step 8: Display slips
    display.print_slips_header(len(slips), target_decimal)
    for i, slip in enumerate(slips, 1):
        display.print_slip(slip, rank=i)

    # Final credits reminder
    display.console.print()
    display.print_credits()


if __name__ == "__main__":
    main()
