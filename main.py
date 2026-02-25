"""
PickAParlay — NBA Bet Builder
Entry point. Wires all modules together.

Usage (subcommands):
  python main.py refresh                          # fetch + grade, cache results
  python main.py slips --odds 4/1                # instant slip builder from cache
  python main.py slips --odds 4/1 --bookmaker paddypower --save
  python main.py history                          # show saved slips + outcomes

Legacy (still works):
  python main.py --odds 4/1
  python main.py --odds 5.0 --legs 4
  python main.py --odds "+400" --min-score 70
  python main.py --odds 4/1 --legs 3 --verbose
"""
from __future__ import annotations

import dataclasses
import sys
import click

# Ensure src is importable
import os
sys.path.insert(0, os.path.dirname(__file__))

import config
from src import display
from src.api import nba_stats, injury_api, odds_api
from src.analysis import prop_grader, bet_builder
from src.models import NBAGame, PlayerProp, FactorResult, ValuedProp
import src.cache as cache
import src.database as database


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
# ValuedProp reconstruction (cache → objects)
# ---------------------------------------------------------------------------

def _vp_from_dict(d: dict) -> ValuedProp:
    """Reconstruct a ValuedProp from its dataclasses.asdict() representation."""
    game_d = d["prop"]["game"]
    game = NBAGame(**game_d)

    prop_d = dict(d["prop"])
    prop_d["game"] = game
    prop = PlayerProp(**prop_d)

    factors = [FactorResult(**f) for f in d["factors"]]

    return ValuedProp(
        prop=prop,
        value_score=d["value_score"],
        factors=factors,
        recommendation=d["recommendation"],
        backing_data=d.get("backing_data", {}),
        suspicious_line=d.get("suspicious_line", False),
        suspicious_reason=d.get("suspicious_reason", ""),
    )


# ---------------------------------------------------------------------------
# Shared pipeline (steps 1–5)
# ---------------------------------------------------------------------------

def _run_pipeline(
    season: str,
    verbose: bool,
) -> tuple[list, list, list[ValuedProp], int]:
    """
    Full fetch + grade pipeline.

    Returns (games, all_raw_props, all_valued_props, error_count).
    all_valued_props contains ALL scored props regardless of min_score —
    callers are responsible for filtering.
    """
    with display.make_progress() as progress:
        task = progress.add_task("Fetching tonight's games...", total=None)
        games = nba_stats.get_todays_games()
        progress.update(task, completed=True, description="Tonight's games loaded ✓")

    if not games:
        display.print_no_games()
        return games, [], [], 0

    display.print_games_table(games)

    with display.make_progress() as progress:

        task = progress.add_task("Loading injury report...", total=None)
        injuries = injury_api.get_injury_report()
        progress.update(task, completed=True, description=f"Injuries loaded ({len(injuries)} reports) ✓")

        task = progress.add_task("Fetching Odds API events...", total=None)
        events = odds_api.get_events()
        for game in games:
            event_id = odds_api.match_game_to_event(game, events)
            if event_id:
                game.odds_event_id = event_id
        progress.update(task, completed=True, description="Events matched ✓")

        task = progress.add_task("Fetching player props...", total=len(games))
        all_raw_props: list = []
        for game in games:
            if game.odds_event_id:
                raw = odds_api.get_player_props_for_event(game.odds_event_id)
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
        return games, [], [], 0

    display.console.print(
        f"\nAnalysing [bold]{len(all_raw_props)}[/bold] props across {len(games)} game(s)...\n"
    )

    all_valued_props: list[ValuedProp] = []
    errors: list[str] = []
    skipped_no_data = 0

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
                else:
                    all_valued_props.append(vp)
            except Exception as e:
                errors.append(f"{prop.player_name} / {prop.market}: {type(e).__name__}: {e}")
            progress.advance(task)
        progress.update(task, description=f"Grading complete — {len(all_valued_props)} props scored ✓")

    display.console.print(
        f"\n[dim]Grading summary:[/dim] "
        f"[green]{len(all_valued_props)} props scored[/green]  |  "
        f"[dim]{skipped_no_data} skipped (no data)[/dim]  |  "
        f"[red]{len(errors)} errors[/red]\n"
    )

    if errors and verbose:
        display.console.print("[bold red]Errors during grading:[/bold red]")
        for err in errors[:10]:
            display.console.print(f"  [red]• {err}[/red]")
        if len(errors) > 10:
            display.console.print(f"  [red]... and {len(errors) - 10} more[/red]")
        display.console.print()

    return games, all_raw_props, all_valued_props, len(errors)


# ---------------------------------------------------------------------------
# Slip display helper (shared between legacy and slips subcommand)
# ---------------------------------------------------------------------------

def _display_and_build_slips(
    all_valued_props: list[ValuedProp],
    odds_str: str,
    target_decimal: float,
    legs: int | None,
    min_score: float | None,
    bookmaker: str | None,
    verbose: bool,
) -> list:
    """Filter props, display table, build + display slips. Returns slip list."""
    threshold = min_score if min_score is not None else config.MIN_VALUE_SCORE
    eligible = [vp for vp in all_valued_props if vp.value_score >= threshold]
    below = [vp for vp in all_valued_props if vp.value_score < threshold]

    if not eligible:
        if below:
            below.sort(key=lambda v: v.value_score, reverse=True)
            display.console.print(
                f"[yellow]No props met the minimum score of {threshold}. "
                f"Top {min(10, len(below))} below threshold:[/yellow]\n"
            )
            for vp in below[:10]:
                ml = config.MARKET_MAP.get(vp.prop.market, {}).get("label", vp.prop.market)
                score_col = "yellow" if vp.value_score >= 40 else "red"
                display.console.print(
                    f"  [{score_col}]{vp.value_score:.1f}/100[/{score_col}]  "
                    f"[bold]{vp.prop.player_name}[/bold]  {ml}  "
                    f"[dim]({vp.recommendation})[/dim]"
                )
            display.console.print(
                f"\n[dim]Tip: run with --min-score {max(10, int(below[0].value_score) - 5)} "
                "to include the top-scoring props.[/dim]"
            )
        else:
            display.console.print(
                "[yellow]No props were scored. Check --verbose for detail.[/yellow]"
            )
        return []

    display.print_props_table(eligible)

    if verbose:
        display.console.print()
        display.console.rule("[bold]Full Factor Breakdowns — Eligible Props[/bold]")
        for i, vp in enumerate(
            sorted(eligible, key=lambda v: v.value_score, reverse=True), 1
        ):
            display.print_valued_prop(vp, rank=i)

    display.console.print("\nBuilding bet combinations...\n")
    slips_result = bet_builder.build_slips(
        eligible,
        target_decimal=target_decimal,
        n_legs=legs,
        min_score=min_score,
        bookmaker=bookmaker,
    )

    if not slips_result:
        display.print_no_slips(target_decimal)
        return []

    display.print_slips_header(len(slips_result), target_decimal)
    for i, slip in enumerate(slips_result, 1):
        display.print_slip(slip, rank=i)

    return slips_result


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group(invoke_without_command=True)
@click.pass_context
@click.option(
    "--odds", "-o",
    default=None,
    help='[Legacy] Target odds. Accepts "4/1", "5.0", "+400".',
)
@click.option(
    "--legs", "-l",
    type=int,
    default=None,
    help="[Legacy] Exact number of legs.",
)
@click.option(
    "--min-score", "-m",
    type=float,
    default=None,
    help=f"[Legacy] Minimum value score (default: {config.MIN_VALUE_SCORE}).",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Show full factor breakdown.",
)
@click.option(
    "--season",
    default=config.DEFAULT_SEASON,
    show_default=True,
    help="NBA season string.",
)
def cli(
    ctx: click.Context,
    odds: str | None,
    legs: int | None,
    min_score: float | None,
    verbose: bool,
    season: str,
) -> None:
    """PickAParlay — NBA Bet Builder.

    \b
    Subcommands:
      refresh   Fetch & grade all props (once per day)
      slips     Build bet slips from cached props (instant)
      history   Show saved slips and outcomes

    \b
    Legacy (no subcommand):
      python main.py --odds 4/1
    """
    if ctx.invoked_subcommand is not None:
        return  # A subcommand handles everything

    # Legacy mode: --odds is required
    if not odds:
        click.echo(ctx.get_help())
        return

    database.init_db()
    display.print_header()
    display.print_credits()

    try:
        target_decimal = parse_odds(odds)
    except click.BadParameter as e:
        display.console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    display.console.print(
        f"Target odds: [cyan]{target_decimal:.3f}[/cyan]  ({odds})  "
        f"Legs: {'auto' if legs is None else legs}  "
        f"Min score: {min_score or config.MIN_VALUE_SCORE}\n"
    )

    games, all_raw_props, all_valued_props, _ = _run_pipeline(season, verbose)

    if not all_valued_props:
        sys.exit(0)

    _display_and_build_slips(
        all_valued_props,
        odds_str=odds,
        target_decimal=target_decimal,
        legs=legs,
        min_score=min_score,
        bookmaker=None,
        verbose=verbose,
    )

    display.console.print()
    display.print_credits()


# ---------------------------------------------------------------------------
# refresh subcommand
# ---------------------------------------------------------------------------

@cli.command("refresh")
@click.option(
    "--season",
    default=config.DEFAULT_SEASON,
    show_default=True,
    help="NBA season string.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Show grading errors in detail.",
)
def refresh_cmd(season: str, verbose: bool) -> None:
    """Fetch & grade all props. Caches results; saves a grading run to the DB.

    Run this once per day. Then use 'slips' to build bet slips instantly
    without burning any Odds API credits.
    """
    database.init_db()
    display.print_header()
    display.print_credits()

    games, all_raw_props, all_valued_props, error_count = _run_pipeline(season, verbose)

    if not all_valued_props:
        display.console.print("[yellow]No props were scored — nothing cached.[/yellow]")
        return

    # Serialise ALL scored props to cache (threshold-agnostic)
    prop_dicts = [dataclasses.asdict(vp) for vp in all_valued_props]
    cache.save_scored_props(prop_dicts)

    above_threshold = sum(
        1 for vp in all_valued_props if vp.value_score >= config.MIN_VALUE_SCORE
    )

    # Record grading run in DB
    run_id = database.save_grading_run(
        season=season,
        games_count=len(games),
        props_total=len(all_raw_props),
        props_graded=len(all_valued_props),
        props_eligible=above_threshold,
    )

    display.console.print(
        f"[green]✓ Cached {len(all_valued_props)} scored props "
        f"({above_threshold} above default threshold of {config.MIN_VALUE_SCORE}).[/green]"
    )
    display.console.print(
        f"[green]✓ Grading run #{run_id} saved to database.[/green]"
    )
    display.console.print(
        "\n[dim]Next step: [bold]python main.py slips --odds 4/1[/bold][/dim]"
    )

    display.console.print()
    display.print_credits()


# ---------------------------------------------------------------------------
# slips subcommand
# ---------------------------------------------------------------------------

@cli.command("slips")
@click.option(
    "--odds", "-o",
    required=True,
    help='Target odds. Accepts "4/1", "5.0", "+400".',
)
@click.option(
    "--legs", "-l",
    type=int,
    default=None,
    help="Exact number of legs. Omit to auto-determine.",
)
@click.option(
    "--min-score", "-m",
    type=float,
    default=None,
    help=f"Minimum value score (default: {config.MIN_VALUE_SCORE}). Use 70+ for Strong/Good only.",
)
@click.option(
    "--bookmaker", "-b",
    default=None,
    help='Filter by bookmaker: "paddypower" or e.g. "draftkings". Omit for all.',
)
@click.option(
    "--save",
    is_flag=True,
    default=False,
    help="Save the top slip to the database.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Show full factor breakdown for all eligible props.",
)
def slips_cmd(
    odds: str,
    legs: int | None,
    min_score: float | None,
    bookmaker: str | None,
    save: bool,
    verbose: bool,
) -> None:
    """Build bet slips from today's cached props (instant — no API calls).

    Run 'refresh' first to fetch and cache today's props.
    Then call 'slips' as many times as you like with different odds targets
    without using any Odds API credits.
    """
    database.init_db()
    display.print_header()

    try:
        target_decimal = parse_odds(odds)
    except click.BadParameter as e:
        display.console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    # Load cached props
    raw_dicts = cache.load_scored_props_raw()
    if not raw_dicts:
        display.console.print(
            "[yellow]No cached props found for today. "
            "Run [bold]python main.py refresh[/bold] first.[/yellow]"
        )
        sys.exit(1)

    # Reconstruct ValuedProp objects
    all_valued_props: list[ValuedProp] = []
    failed = 0
    for d in raw_dicts:
        try:
            all_valued_props.append(_vp_from_dict(d))
        except Exception:
            failed += 1

    display.console.print(
        f"[dim]Loaded {len(all_valued_props)} cached props from today"
        + (f" ({failed} malformed entries skipped)" if failed else "")
        + ".[/dim]\n"
    )

    bookie_str = f"  Bookmaker: [bold]{bookmaker}[/bold]" if bookmaker else ""
    display.console.print(
        f"Target odds: [cyan]{target_decimal:.3f}[/cyan]  ({odds})  "
        f"Legs: {'auto' if legs is None else legs}  "
        f"Min score: {min_score or config.MIN_VALUE_SCORE}"
        + bookie_str + "\n"
    )

    slips_result = _display_and_build_slips(
        all_valued_props,
        odds_str=odds,
        target_decimal=target_decimal,
        legs=legs,
        min_score=min_score,
        bookmaker=bookmaker,
        verbose=verbose,
    )

    # Optionally save the top slip
    if save and slips_result:
        run_id = database.get_latest_run_id()
        slip_id = database.save_slip(
            slip=slips_result[0],
            target_odds_str=odds,
            run_id=run_id,
            bookmaker_filter=bookmaker,
        )
        display.console.print(
            f"\n[green]✓ Top slip saved to database (ID: {slip_id}). "
            "View with [bold]python main.py history[/bold].[/green]"
        )
    elif save and not slips_result:
        display.console.print("[yellow]No slips to save.[/yellow]")

    display.console.print()
    display.print_credits()


# ---------------------------------------------------------------------------
# history subcommand
# ---------------------------------------------------------------------------

@cli.command("history")
@click.option(
    "--limit", "-n",
    default=20,
    show_default=True,
    help="Maximum number of slips to display.",
)
def history_cmd(limit: int) -> None:
    """Show saved bet slips and outcomes from the database."""
    database.init_db()
    display.print_header()

    from rich.table import Table
    from rich import box as rich_box

    slips_data = database.get_history(limit=limit)

    if not slips_data:
        display.console.print(
            "[yellow]No saved slips yet. "
            "Use [bold]python main.py slips --odds 4/1 --save[/bold] to save a slip.[/yellow]"
        )
        return

    table = Table(
        title=f"Saved Bet Slips (last {limit})",
        box=rich_box.SIMPLE_HEAVY,
        show_lines=True,
    )
    table.add_column("ID", style="dim", justify="right")
    table.add_column("Saved At")
    table.add_column("Target", justify="right")
    table.add_column("Combined", justify="right", style="cyan")
    table.add_column("Avg Score", justify="right")
    table.add_column("Bookmaker")
    table.add_column("Legs")
    table.add_column("Outcome", justify="center")

    for s in slips_data:
        outcome = s.get("outcome") or "—"
        outcome_style = {
            "WIN":  "bold green",
            "LOSS": "bold red",
            "VOID": "yellow",
        }.get(outcome, "dim")

        legs_text = _legs_summary(s.get("legs", []))

        table.add_row(
            str(s["id"]),
            str(s.get("saved_at", ""))[:16],
            s.get("target_odds_str") or f"{s.get('target_decimal', 0):.2f}",
            f"{s.get('combined_odds', 0):.2f}",
            f"{s.get('avg_value_score', 0):.1f}/100",
            s.get("bookmaker_filter") or "any",
            legs_text,
            f"[{outcome_style}]{outcome}[/{outcome_style}]",
        )

    display.console.print(table)

    # Aggregate analytics
    analytics = database.get_analytics()
    overall = analytics.get("overall", {})
    if overall.get("total_slips", 0) > 0:
        pnl = overall["total_pnl"]
        pnl_col = "green" if pnl >= 0 else "red"
        pnl_sign = "+" if pnl >= 0 else ""
        display.console.print(
            f"\n[dim]Overall: "
            f"[bold]{overall['wins']}/{overall['total_slips']}[/bold] wins "
            f"({overall['win_rate']:.1%})  |  "
            f"P&L: [{pnl_col}][bold]{pnl_sign}{pnl:.2f}[/bold][/{pnl_col}][/dim]"
        )

        by_market = analytics.get("by_market", [])
        if by_market:
            display.console.print("\n[dim]Hit rate by market:[/dim]")
            for row in by_market:
                if row["total"] > 0:
                    hit_rate = row["hits"] / row["total"]
                    col = "green" if hit_rate >= 0.5 else "yellow"
                    display.console.print(
                        f"  [dim]{row['market_label']:25s}[/dim] "
                        f"[{col}]{row['hits']}/{row['total']} ({hit_rate:.1%})[/{col}]"
                    )


def _legs_summary(legs: list[dict]) -> str:
    """Compact multi-line legs summary for the history table."""
    if not legs:
        return "—"
    parts = []
    for leg in legs:
        result = leg.get("leg_result")
        icon = {"HIT": "[green]✓[/green]", "MISS": "[red]✗[/red]"}.get(result, "[dim]·[/dim]")
        market_label = leg.get("market_label") or leg.get("market", "?")
        parts.append(
            f"{icon} [bold]{leg.get('player_name', '?')}[/bold] "
            f"OVER {leg.get('line', '?')} {market_label}"
        )
    return "\n".join(parts)


if __name__ == "__main__":
    cli()
