#!/usr/bin/env python3
"""
pick-analysis report — formats src.database.get_analytics() into a
readable markdown report. Same query logic the /api/analytics endpoint
serves, so this always matches what the live app would show.

Usage:
    python .claude/skills/pick-analysis/report.py [--min-score 65] [--db PATH]

Exits with a clear message (not a stack trace, not fabricated numbers) if
no database or no graded picks are found.
"""
from __future__ import annotations

import argparse
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, _REPO_ROOT)


def _pct(x: float | None) -> str:
    return f"{x:.1f}%" if x is not None else "n/a"


def _section_report(label: str, section: dict, total_slips_note: str = "") -> list[str]:
    lines: list[str] = []
    picks = section["picks"]
    lines.append(f"\n## {label}\n")

    if picks["total"] == 0:
        lines.append(f"No graded {label.lower()} picks yet.")
        return lines

    lines.append(
        f"- **Sample:** {picks['total']} graded picks "
        f"({picks['hits']} hit / {picks['misses']} miss)"
    )
    lines.append(f"- **Hit rate:** {picks['hit_rate']*100:.1f}%")
    lines.append(
        f"- **ROI:** {_pct(picks['roi_pct'])}  "
        f"(implied market probability: {_pct(picks['implied_prob_pct'])}, "
        f"edge: {_pct(picks['edge_pct'])})"
    )
    if picks["avg_decimal_odds"]:
        lines.append(f"- **Avg odds:** {picks['avg_decimal_odds']:.2f}")
    if picks["total"] < 30:
        lines.append(
            f"- ⚠️ **Sample size warning:** only {picks['total']} graded picks — "
            "treat every breakdown below as directional, not conclusive."
        )

    # Value-score calibration
    vcal = section.get("value_calibration", [])
    if vcal:
        lines.append("\n**Value-score calibration** (bucket → hit rate / ROI / edge):\n")
        lines.append("| Score bucket | N | Hit rate | ROI | Edge |")
        lines.append("|---|---|---|---|---|")
        prev_hr = None
        broke_monotonic = []
        for row in vcal:
            hr = row["hits"] / row["total"] * 100 if row["total"] else 0
            lines.append(
                f"| {row['bucket']}-{row['bucket']+5} | {row['total']} | "
                f"{hr:.1f}% | {_pct(row.get('roi_pct'))} | {_pct(row.get('edge_pct'))} |"
            )
            if prev_hr is not None and row["total"] >= 10 and hr < prev_hr - 5:
                broke_monotonic.append(row["bucket"])
            prev_hr = hr if row["total"] >= 10 else prev_hr
        if broke_monotonic:
            lines.append(
                f"\n⚠️ Hit rate drops at bucket(s) {broke_monotonic} despite a higher "
                "score than the bucket below — score isn't cleanly monotonic there "
                "(on buckets with ≥10 picks)."
            )

    # Factor calibration
    fcal = section.get("factor_calibration", {})
    if fcal:
        lines.append("\n**Per-factor calibration** (does this factor's own score predict the outcome?):\n")
        for factor_name, buckets in fcal.items():
            usable = [b for b in buckets if b["total"] >= 10]
            if not usable:
                lines.append(f"- {factor_name}: not enough data per bucket to assess")
                continue
            low = usable[0]
            high = usable[-1]
            low_hr = low["hits"] / low["total"] * 100
            high_hr = high["hits"] / high["total"] * 100
            spread = high_hr - low_hr
            verdict = (
                "predictive" if spread >= 10 else
                "weak / flat" if abs(spread) < 10 else
                "INVERTED — higher score hits LESS"
            )
            lines.append(
                f"- **{factor_name}**: {low['bucket']}-bucket hit rate {low_hr:.0f}% → "
                f"{high['bucket']}-bucket hit rate {high_hr:.0f}% ({spread:+.0f}pp) → {verdict}"
            )

    # By market
    by_market = section.get("by_market", [])
    if by_market:
        lines.append("\n**By market:**\n")
        lines.append("| Market | N | Hit rate | ROI | Edge |")
        lines.append("|---|---|---|---|---|")
        for row in by_market:
            hr = row["hits"] / row["total"] * 100 if row["total"] else 0
            lines.append(
                f"| {row['market_label']} | {row['total']} | {hr:.1f}% | "
                f"{_pct(row.get('roi_pct'))} | {_pct(row.get('edge_pct'))} |"
            )

    # By side
    by_side = section.get("by_side", [])
    if by_side:
        lines.append("\n**By side:**\n")
        for row in by_side:
            hr = row["hits"] / row["total"] * 100 if row["total"] else 0
            lines.append(f"- {row['side']}: {row['total']} picks, {hr:.1f}% hit rate")

    # Threshold table
    tt = section.get("threshold_table", [])
    if tt:
        lines.append("\n**Minimum score threshold comparison:**\n")
        lines.append("| Min score | N | Hit rate | ROI | Edge |")
        lines.append("|---|---|---|---|---|")
        for row in tt:
            lines.append(
                f"| {row['min_score']}+ | {row['total']} | {row['hit_rate_pct']:.1f}% | "
                f"{_pct(row.get('roi_pct'))} | {_pct(row.get('edge_pct'))} |"
            )
        positive_roi = [r for r in tt if r.get("roi_pct") is not None and r["roi_pct"] > 0 and r["total"] >= 20]
        if positive_roi:
            best = min(positive_roi, key=lambda r: r["min_score"])
            lines.append(
                f"\n→ Lowest threshold with reliably positive ROI (≥20 picks): "
                f"**{best['min_score']}+** ({best['total']} picks, {_pct(best['roi_pct'])} ROI)."
            )
        else:
            lines.append("\n→ No threshold shows positive ROI on ≥20 picks yet.")

    # Daily trend / PnL
    daily_trend = section.get("daily_trend", [])
    daily_pnl = section.get("daily_pnl", [])
    if daily_trend:
        lines.append(f"\n**Daily trend:** {len(daily_trend)} days with graded picks "
                      f"({daily_trend[0]['game_date']} → {daily_trend[-1]['game_date']}).")
    if daily_pnl:
        cumulative = 0.0
        for row in daily_pnl:
            cumulative += row["day_roi_units"] or 0
        lines.append(f"**Cumulative P&L (flat stake units):** {cumulative:+.2f}")

    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="PickAParlay season analysis report")
    parser.add_argument("--min-score", type=int, default=65)
    parser.add_argument("--db", default=None, help="Override DATABASE_PATH")
    args = parser.parse_args()

    if args.db:
        os.environ["DATABASE_PATH"] = os.path.abspath(args.db)

    import config

    if not os.path.exists(config.DATABASE_PATH):
        print(
            f"No database found at {config.DATABASE_PATH}.\n"
            "This is expected in a fresh checkout — pickaparlay.db is git-ignored "
            "and lives on the production Fly volume. See SKILL.md for how to get a "
            "copy (fly ssh sftp get, or query /api/analytics directly).\n\n"
            "Not generating a report against no data."
        )
        sys.exit(1)

    import src.database as database

    data = database.get_analytics(min_score=args.min_score)

    regular_total = data["regular"]["picks"]["total"]
    alt_total = data["alt"]["picks"]["total"]
    if regular_total == 0 and alt_total == 0:
        print(
            f"Database found at {config.DATABASE_PATH} but it has zero graded picks "
            "(leg_result is NULL for everything, or the table is empty).\n"
            "Nothing to analyze yet — this is a legitimate finding (no data), not an "
            "error to work around. Report that plainly rather than inventing numbers."
        )
        sys.exit(1)

    lines: list[str] = [
        f"# PickAParlay Season Analysis",
        f"\nDatabase: `{config.DATABASE_PATH}`  |  Threshold used: min_score ≥ {args.min_score}",
    ]
    lines += _section_report("Regular Lines", data["regular"])
    lines += _section_report("Alternate Lines", data["alt"])

    slips = data.get("slips", {})
    if slips.get("total_slips"):
        lines.append("\n## Saved Slips (parlay-level, mixes regular + alt)\n")
        lines.append(
            f"- {slips['wins']}/{slips['total_slips']} wins "
            f"({slips['win_rate']*100:.1f}%)  |  P&L: {slips['total_pnl']:+.2f}"
        )

    print("\n".join(lines))


if __name__ == "__main__":
    main()
